from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from . import ast_nodes
from .dynamic_values import (
    DynamicExpression,
    UnsupportedDynamicParametersError,
    collect_dynamic_dependencies,
    contains_dynamic,
    dynamic_parameter,
    is_dynamic,
)
from .errors import EvaluationError, SourceLocation, UnsupportedFeatureError
from .ir import BooleanNode, ConditionalNode, ExtrudeNode, IRNode, PrimitiveNode, TransformNode

TRANSFORM_BUILTINS = {"translate", "rotate", "scale", "resize", "mirror", "multmatrix"}
BOOLEAN_BUILTINS = {"union", "difference", "intersection"}
PRIMITIVE_2D_BUILTINS = {"circle", "square", "polygon"}
PRIMITIVE_3D_BUILTINS = {"cube", "sphere", "cylinder"}
EXTRUDE_BUILTINS = {"linear_extrude", "rotate_extrude"}
UNSUPPORTED_BUILTINS = {"hull", "minkowski", "offset", "projection", "surface", "import"}


@dataclass(slots=True)
class RangeValue:
    start: Any
    end: Any
    step: Any

    def expand(self) -> list[float]:
        values: list[float] = []
        current = self.start
        comparator = (lambda a, b: a <= b + 1e-9) if self.step >= 0 else (lambda a, b: a >= b - 1e-9)
        while comparator(current, self.end):
            values.append(current)
            current += self.step
        return values


@dataclass(slots=True)
class Environment:
    parent: "Environment | None" = None
    variables: dict[str, Any] = field(default_factory=dict)
    modules: dict[str, ast_nodes.ModuleDefinition] = field(default_factory=dict)
    locked_names: set[str] = field(default_factory=set)

    def child(self) -> "Environment":
        return Environment(parent=self)

    def define_variable(self, name: str, value: Any) -> None:
        if self.parent is None and name in self.locked_names:
            return
        self.variables[name] = value

    def resolve_variable(self, name: str, *, location: SourceLocation, path: str | None) -> Any:
        if name in self.variables:
            return self.variables[name]
        if self.parent is not None:
            return self.parent.resolve_variable(name, location=location, path=path)
        raise EvaluationError(f"Unknown identifier: {name}", path=path, location=location)

    def define_module(self, module: ast_nodes.ModuleDefinition) -> None:
        self.modules[module.name] = module

    def resolve_module(
        self,
        name: str,
        *,
        location: SourceLocation,
        path: str | None,
    ) -> ast_nodes.ModuleDefinition:
        if name in self.modules:
            return self.modules[name]
        if self.parent is not None:
            return self.parent.resolve_module(name, location=location, path=path)
        raise EvaluationError(f"Unknown module: {name}", path=path, location=location)


class Evaluator:
    def __init__(self, parameters: dict[str, Any] | None = None, path: str | None = None) -> None:
        self.parameters = parameters or {}
        self.path = path

    def evaluate(self, program: ast_nodes.Program) -> IRNode | None:
        environment = Environment()
        environment.variables.update({"$fn": 0, "$fa": 12, "$fs": 2})
        environment.locked_names.update(self.parameters)
        environment.variables.update(self.parameters)
        nodes = self._evaluate_statements(program.statements, environment)
        return _combine_nodes(nodes)

    def collect_top_level_defaults(self, program: ast_nodes.Program) -> dict[str, Any]:
        environment = Environment()
        environment.variables.update({"$fn": 0, "$fa": 12, "$fs": 2})
        defaults: dict[str, Any] = {}
        for statement in program.statements:
            if isinstance(statement, ast_nodes.Assignment):
                value = self._eval_expression(statement.value, environment)
                environment.define_variable(statement.name, value)
                defaults[statement.name] = value
            elif isinstance(statement, ast_nodes.ModuleDefinition):
                environment.define_module(statement)
        return defaults

    def evaluate_parameterized(self, program: ast_nodes.Program, customizer_parameters: list[Any]) -> tuple[IRNode | None, list[Any]]:
        customizer_by_name = {parameter.name: parameter for parameter in customizer_parameters}
        parameter_values = {
            parameter.name: self.parameters.get(parameter.name, parameter.default)
            for parameter in customizer_parameters
        }
        dynamic_names = set(parameter_values)

        while True:
            environment = self._build_parameterized_environment(customizer_parameters, parameter_values, dynamic_names)
            try:
                nodes = self._evaluate_statements(program.statements, environment)
                ir = _combine_nodes(nodes)
                unsupported_dynamic = _collect_unsupported_dynamic_dependencies(ir)
                if unsupported_dynamic:
                    raise UnsupportedDynamicParametersError(unsupported_dynamic)
                used_dynamic = _collect_ir_dynamic_dependencies(ir)
                active_parameters = []
                for name in [parameter.name for parameter in customizer_parameters]:
                    if name not in dynamic_names or name not in used_dynamic:
                        continue
                    parameter = customizer_by_name[name]
                    _apply_parameter_override(parameter, parameter_values[name])
                    active_parameters.append(parameter)
                return ir, active_parameters
            except UnsupportedDynamicParametersError as error:
                removable = error.parameter_names & dynamic_names
                if not removable:
                    raise
                dynamic_names -= removable

    def _build_parameterized_environment(
        self,
        customizer_parameters: list[Any],
        parameter_values: dict[str, Any],
        dynamic_names: set[str],
    ) -> Environment:
        environment = Environment()
        environment.variables.update({"$fn": 0, "$fa": 12, "$fs": 2})

        non_customizer_overrides = {
            key: value
            for key, value in self.parameters.items()
            if key not in parameter_values
        }
        environment.locked_names.update(non_customizer_overrides)
        environment.variables.update(non_customizer_overrides)

        for parameter in customizer_parameters:
            environment.locked_names.add(parameter.name)
            value = parameter_values[parameter.name]
            if parameter.name in dynamic_names:
                environment.variables[parameter.name] = _dynamic_parameter_value(parameter)
            else:
                environment.variables[parameter.name] = value
        return environment

    def _evaluate_statements(self, statements: list[ast_nodes.Statement], environment: Environment) -> list[IRNode]:
        nodes: list[IRNode] = []
        for statement in statements:
            nodes.extend(self._evaluate_statement(statement, environment))
        return nodes

    def _evaluate_statement(self, statement: ast_nodes.Statement, environment: Environment) -> list[IRNode]:
        if isinstance(statement, ast_nodes.Assignment):
            environment.define_variable(statement.name, self._eval_expression(statement.value, environment))
            return []

        if isinstance(statement, ast_nodes.ModuleDefinition):
            environment.define_module(statement)
            return []

        if isinstance(statement, ast_nodes.Block):
            block_environment = environment.child()
            return self._evaluate_statements(statement.statements, block_environment)

        if isinstance(statement, ast_nodes.IfStatement):
            condition = self._eval_expression(statement.condition, environment)
            if is_dynamic(condition):
                then_nodes = self._evaluate_statement(statement.then_branch, environment.child())
                else_nodes = []
                if statement.else_branch is not None:
                    else_nodes = self._evaluate_statement(statement.else_branch, environment.child())
                return [
                    ConditionalNode(
                        location=statement.location,
                        condition=condition,
                        then_branch=_combine_nodes(then_nodes),
                        else_branch=_combine_nodes(else_nodes),
                    )
                ]
            branch = statement.then_branch if _truthy(condition) else statement.else_branch
            if branch is None:
                return []
            return self._evaluate_statement(branch, environment.child())

        if isinstance(statement, ast_nodes.ForStatement):
            iterable = self._eval_expression(statement.iterable, environment)
            values = _expand_iterable(iterable, location=statement.location, path=self.path)
            nodes: list[IRNode] = []
            for value in values:
                loop_environment = environment.child()
                loop_environment.define_variable(statement.variable, value)
                nodes.extend(self._evaluate_statement(statement.body, loop_environment))
            return nodes

        if isinstance(statement, ast_nodes.Call):
            return self._evaluate_call(statement, environment)

        raise EvaluationError(
            f"Unsupported statement type: {type(statement).__name__}",
            path=self.path,
            location=statement.location,
        )

    def _evaluate_call(self, call: ast_nodes.Call, environment: Environment) -> list[IRNode]:
        if call.name in UNSUPPORTED_BUILTINS:
            raise UnsupportedFeatureError(
                f"Unsupported OpenSCAD feature: {call.name}()",
                path=self.path,
                location=call.location,
            )

        positional, keyword = self._resolve_arguments(call.arguments, environment)
        tessellation = self._resolve_tessellation(keyword, environment, location=call.location)

        if call.name in PRIMITIVE_2D_BUILTINS | PRIMITIVE_3D_BUILTINS:
            if call.child is not None:
                raise EvaluationError(
                    f"Primitive {call.name}() cannot have child geometry",
                    path=self.path,
                    location=call.location,
                )
            params = dict(keyword)
            if positional:
                params["_positional"] = positional
            params["_tessellation"] = tessellation
            return [PrimitiveNode(location=call.location, kind=call.name, params=params)]

        if call.name in TRANSFORM_BUILTINS:
            if call.child is None:
                raise EvaluationError(
                    f"Transform {call.name}() requires child geometry",
                    path=self.path,
                    location=call.location,
                )
            child_nodes = self._evaluate_statement(call.child, environment.child())
            child = _combine_nodes(child_nodes)
            if child is None:
                raise EvaluationError(
                    f"Transform {call.name}() received empty child geometry",
                    path=self.path,
                    location=call.location,
                )
            params = dict(keyword)
            if positional:
                params["_positional"] = positional
            return [TransformNode(location=call.location, kind=call.name, params=params, child=child)]

        if call.name in BOOLEAN_BUILTINS:
            if call.child is None:
                raise EvaluationError(
                    f"Boolean operation {call.name}() requires child geometry",
                    path=self.path,
                    location=call.location,
                )
            child_nodes = self._evaluate_statement(call.child, environment.child())
            if not child_nodes:
                raise EvaluationError(
                    f"Boolean operation {call.name}() received empty child geometry",
                    path=self.path,
                    location=call.location,
                )
            return [BooleanNode(location=call.location, kind=call.name, children=child_nodes)]

        if call.name in EXTRUDE_BUILTINS:
            if call.child is None:
                raise EvaluationError(
                    f"Extrusion {call.name}() requires child geometry",
                    path=self.path,
                    location=call.location,
                )
            child_nodes = self._evaluate_statement(call.child, environment.child())
            child = _combine_nodes(child_nodes)
            if child is None:
                raise EvaluationError(
                    f"Extrusion {call.name}() received empty child geometry",
                    path=self.path,
                    location=call.location,
                )
            params = dict(keyword)
            if positional:
                params["_positional"] = positional
            params["_tessellation"] = tessellation
            return [ExtrudeNode(location=call.location, kind=call.name, params=params, child=child)]

        module = environment.resolve_module(call.name, location=call.location, path=self.path)
        if call.child is not None:
            raise UnsupportedFeatureError(
                f"Module children are not supported for {call.name}()",
                path=self.path,
                location=call.location,
            )

        call_environment = environment.child()
        bound = self._bind_module_arguments(module, positional, keyword, environment)
        for key, value in bound.items():
            call_environment.define_variable(key, value)
        return self._evaluate_statement(module.body, call_environment)

    def _bind_module_arguments(
        self,
        module: ast_nodes.ModuleDefinition,
        positional: list[Any],
        keyword: dict[str, Any],
        environment: Environment,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        positional_iter = iter(positional)
        for parameter in module.parameters:
            if parameter.name in keyword:
                result[parameter.name] = keyword[parameter.name]
                continue
            try:
                result[parameter.name] = next(positional_iter)
                continue
            except StopIteration:
                pass
            if parameter.default is None:
                raise EvaluationError(
                    f"Missing module argument: {parameter.name}",
                    path=self.path,
                    location=module.location,
                )
            result[parameter.name] = self._eval_expression(parameter.default, environment)

        unused_positional = list(positional_iter)
        if unused_positional:
            raise EvaluationError(
                f"Too many positional arguments for module {module.name}()",
                path=self.path,
                location=module.location,
            )

        unexpected = set(keyword).difference({parameter.name for parameter in module.parameters})
        unexpected -= {"$fn", "$fa", "$fs"}
        if unexpected:
            raise EvaluationError(
                f"Unexpected module arguments: {', '.join(sorted(unexpected))}",
                path=self.path,
                location=module.location,
            )
        return result

    def _resolve_arguments(
        self,
        arguments: list[ast_nodes.Argument],
        environment: Environment,
    ) -> tuple[list[Any], dict[str, Any]]:
        positional: list[Any] = []
        keyword: dict[str, Any] = {}
        for argument in arguments:
            value = self._eval_expression(argument.value, environment)
            if argument.name is None:
                positional.append(value)
            else:
                keyword[argument.name] = value
        return positional, keyword

    def _resolve_tessellation(
        self,
        keyword: dict[str, Any],
        environment: Environment,
        *,
        location: SourceLocation,
    ) -> dict[str, Any]:
        tessellation = {
            "fn": keyword.get("$fn", environment.resolve_variable("$fn", location=location, path=self.path)),
            "fa": keyword.get("$fa", environment.resolve_variable("$fa", location=location, path=self.path)),
            "fs": keyword.get("$fs", environment.resolve_variable("$fs", location=location, path=self.path)),
        }
        return tessellation

    def _eval_expression(self, expression: ast_nodes.Expression, environment: Environment) -> Any:
        if isinstance(expression, ast_nodes.Literal):
            return expression.value
        if isinstance(expression, ast_nodes.Identifier):
            return environment.resolve_variable(expression.name, location=expression.location, path=self.path)
        if isinstance(expression, ast_nodes.VectorLiteral):
            return [self._eval_expression(item, environment) for item in expression.items]
        if isinstance(expression, ast_nodes.RangeExpression):
            start = _coerce_number(self._eval_expression(expression.start, environment), expression.location, self.path)
            end = _coerce_number(self._eval_expression(expression.end, environment), expression.location, self.path)
            if expression.step is None:
                step = 1.0 if contains_dynamic(start) or contains_dynamic(end) or end >= start else -1.0
            else:
                step = _coerce_number(self._eval_expression(expression.step, environment), expression.location, self.path)
            if math.isclose(step, 0.0):
                raise EvaluationError("Range step cannot be zero", path=self.path, location=expression.location)
            return RangeValue(start=start, end=end, step=step)
        if isinstance(expression, ast_nodes.UnaryExpression):
            operand = self._eval_expression(expression.operand, environment)
            return _apply_unary(expression.operator, operand, location=expression.location, path=self.path)
        if isinstance(expression, ast_nodes.BinaryExpression):
            left = self._eval_expression(expression.left, environment)
            right = self._eval_expression(expression.right, environment)
            return _apply_binary(
                expression.operator,
                left,
                right,
                location=expression.location,
                path=self.path,
            )
        raise EvaluationError(
            f"Unsupported expression type: {type(expression).__name__}",
            path=self.path,
            location=expression.location,
        )


def _combine_nodes(nodes: list[IRNode]) -> IRNode | None:
    if not nodes:
        return None
    if len(nodes) == 1:
        return nodes[0]
    return BooleanNode(location=nodes[0].location, kind="union", children=nodes)


def _expand_iterable(value: Any, *, location: SourceLocation, path: str | None) -> list[Any]:
    if contains_dynamic(value):
        raise UnsupportedDynamicParametersError(collect_dynamic_dependencies(value))
    if isinstance(value, RangeValue):
        if contains_dynamic(value.start) or contains_dynamic(value.end) or contains_dynamic(value.step):
            raise UnsupportedDynamicParametersError(
                collect_dynamic_dependencies(value.start)
                | collect_dynamic_dependencies(value.end)
                | collect_dynamic_dependencies(value.step)
            )
        return value.expand()
    if isinstance(value, list):
        return list(value)
    raise EvaluationError("for() expects a list or range", path=path, location=location)


def _truthy(value: Any) -> bool:
    return bool(value)


def _coerce_number(value: Any, location: SourceLocation, path: str | None) -> float | DynamicExpression:
    if is_dynamic(value):
        if value.kind != "number":
            raise EvaluationError("Expected a numeric value", path=path, location=location)
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError("Expected a numeric value", path=path, location=location)
    return float(value)


def _apply_unary(
    operator: str,
    operand: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    if contains_dynamic(operand):
        return _apply_dynamic_unary(operator, operand, location=location, path=path)
    if operator == "+":
        return operand
    if operator == "-":
        if isinstance(operand, list):
            return [-_coerce_number(item, location, path) for item in operand]
        return -_coerce_number(operand, location, path)
    if operator == "!":
        return not _truthy(operand)
    raise EvaluationError(f"Unsupported unary operator: {operator}", path=path, location=location)


def _apply_binary(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    if operator in {"+", "-", "*", "/", "%"}:
        return _apply_arithmetic(operator, left, right, location=location, path=path)
    if contains_dynamic(left) or contains_dynamic(right):
        return _apply_dynamic_logic_or_compare(operator, left, right, location=location, path=path)
    if operator == "&&":
        return _truthy(left) and _truthy(right)
    if operator == "||":
        return _truthy(left) or _truthy(right)
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    raise EvaluationError(f"Unsupported operator: {operator}", path=path, location=location)


def _apply_arithmetic(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    if contains_dynamic(left) or contains_dynamic(right):
        return _apply_dynamic_arithmetic(operator, left, right, location=location, path=path)
    if isinstance(left, list) or isinstance(right, list):
        return _apply_vector_arithmetic(operator, left, right, location=location, path=path)

    left_number = _coerce_number(left, location, path)
    right_number = _coerce_number(right, location, path)
    return _apply_scalar_arithmetic(operator, left_number, right_number)


def _apply_vector_arithmetic(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> list[float]:
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise EvaluationError("Vector lengths must match", path=path, location=location)
        return [
            _apply_scalar_arithmetic(
                operator,
                _coerce_number(left_value, location, path),
                _coerce_number(right_value, location, path),
            )
            for left_value, right_value in zip(left, right)
        ]

    if isinstance(left, list):
        scalar = _coerce_number(right, location, path)
        return [
            _apply_scalar_arithmetic(operator, _coerce_number(value, location, path), scalar)
            for value in left
        ]

    scalar = _coerce_number(left, location, path)
    return [
        _apply_scalar_arithmetic(operator, scalar, _coerce_number(value, location, path))
        for value in right
    ]


def _apply_scalar_arithmetic(operator: str, left: float, right: float) -> float:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        return left / right
    if operator == "%":
        return left % right
    raise ValueError(operator)


def _dynamic_parameter_value(parameter: Any) -> Any:
    if parameter.kind in {"int", "float"}:
        return dynamic_parameter(parameter.name, "number")
    if parameter.kind == "bool":
        return dynamic_parameter(parameter.name, "bool")
    if parameter.kind == "string":
        return dynamic_parameter(parameter.name, "string")
    if parameter.kind == "vector":
        return [
            dynamic_parameter(parameter.name, "number", component=index)
            for index, _component_kind in enumerate(parameter.component_kinds)
        ]
    raise EvaluationError(f"Unsupported customizer parameter type: {parameter.kind}", path=None, location=None)


def _apply_dynamic_unary(
    operator: str,
    operand: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    if operator == "+":
        return operand
    if operator == "-":
        if isinstance(operand, list):
            return [_apply_dynamic_unary(operator, item, location=location, path=path) for item in operand]
        numeric_operand = _coerce_number(operand, location, path)
        return DynamicExpression(
            kind="number",
            operation="unary",
            operator=operator,
            operand=numeric_operand,
            dependencies=frozenset(collect_dynamic_dependencies(numeric_operand)),
        )
    if operator == "!":
        if isinstance(operand, list):
            raise EvaluationError("Logical negation does not support vectors", path=path, location=location)
        return DynamicExpression(
            kind="bool",
            operation="unary",
            operator=operator,
            operand=operand,
            dependencies=frozenset(collect_dynamic_dependencies(operand)),
        )
    raise EvaluationError(f"Unsupported unary operator: {operator}", path=path, location=location)


def _apply_dynamic_arithmetic(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise EvaluationError("Vector lengths must match", path=path, location=location)
        return [
            _dynamic_numeric_expression(operator, left_value, right_value, location=location, path=path)
            for left_value, right_value in zip(left, right)
        ]

    if isinstance(left, list):
        scalar = _coerce_number(right, location, path)
        return [
            _dynamic_numeric_expression(operator, value, scalar, location=location, path=path)
            for value in left
        ]

    if isinstance(right, list):
        scalar = _coerce_number(left, location, path)
        return [
            _dynamic_numeric_expression(operator, scalar, value, location=location, path=path)
            for value in right
        ]

    return _dynamic_numeric_expression(operator, left, right, location=location, path=path)


def _dynamic_numeric_expression(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> Any:
    left_number = _coerce_number(left, location, path)
    right_number = _coerce_number(right, location, path)
    if not contains_dynamic(left_number) and not contains_dynamic(right_number):
        return _apply_scalar_arithmetic(operator, float(left_number), float(right_number))
    return DynamicExpression(
        kind="number",
        operation="binary",
        operator=operator,
        left=left_number,
        right=right_number,
        dependencies=frozenset(
            collect_dynamic_dependencies(left_number) | collect_dynamic_dependencies(right_number)
        ),
    )


def _apply_dynamic_logic_or_compare(
    operator: str,
    left: Any,
    right: Any,
    *,
    location: SourceLocation,
    path: str | None,
) -> DynamicExpression:
    if isinstance(left, list) or isinstance(right, list):
        raise EvaluationError("Dynamic vector comparisons are not supported", path=path, location=location)
    if operator not in {"&&", "||", "==", "!=", "<", "<=", ">", ">="}:
        raise EvaluationError(f"Unsupported operator: {operator}", path=path, location=location)
    return DynamicExpression(
        kind="bool",
        operation="binary",
        operator=operator,
        left=left,
        right=right,
        dependencies=frozenset(collect_dynamic_dependencies(left) | collect_dynamic_dependencies(right)),
    )


def _collect_ir_dynamic_dependencies(node: IRNode | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, PrimitiveNode):
        return collect_dynamic_dependencies(node.params)
    if isinstance(node, TransformNode):
        return collect_dynamic_dependencies(node.params) | _collect_ir_dynamic_dependencies(node.child)
    if isinstance(node, ExtrudeNode):
        return collect_dynamic_dependencies(node.params) | _collect_ir_dynamic_dependencies(node.child)
    if isinstance(node, BooleanNode):
        dependencies: set[str] = set()
        for child in node.children:
            dependencies.update(_collect_ir_dynamic_dependencies(child))
        return dependencies
    if isinstance(node, ConditionalNode):
        return (
            collect_dynamic_dependencies(node.condition)
            | _collect_ir_dynamic_dependencies(node.then_branch)
            | _collect_ir_dynamic_dependencies(node.else_branch)
        )
    return set()


def _collect_unsupported_dynamic_dependencies(node: IRNode | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, PrimitiveNode):
        if node.kind == "polygon":
            return collect_dynamic_dependencies(node.params)
        return set()
    if isinstance(node, TransformNode):
        dependencies = _collect_unsupported_dynamic_dependencies(node.child)
        if node.kind in {"resize", "mirror", "multmatrix"}:
            dependencies.update(collect_dynamic_dependencies(node.params))
        if node.kind == "rotate" and "a" in node.params and "v" in node.params:
            dependencies.update(collect_dynamic_dependencies(node.params))
        return dependencies
    if isinstance(node, ExtrudeNode):
        dependencies = _collect_unsupported_dynamic_dependencies(node.child)
        if node.kind == "rotate_extrude":
            dependencies.update(collect_dynamic_dependencies(node.params))
            dependencies.update(_collect_ir_dynamic_dependencies(node.child))
        return dependencies
    if isinstance(node, BooleanNode):
        dependencies: set[str] = set()
        for child in node.children:
            dependencies.update(_collect_unsupported_dynamic_dependencies(child))
        return dependencies
    if isinstance(node, ConditionalNode):
        return (
            _collect_unsupported_dynamic_dependencies(node.then_branch)
            | _collect_unsupported_dynamic_dependencies(node.else_branch)
        )
    return set()


def _apply_parameter_override(parameter: Any, value: Any) -> None:
    parameter.default = value
    if parameter.kind == "int" and isinstance(value, float) and not value.is_integer():
        parameter.kind = "float"
        return
    if parameter.kind != "vector" or not isinstance(value, (list, tuple)):
        return

    component_kinds = list(parameter.component_kinds)
    for index, component in enumerate(value):
        if index >= len(component_kinds):
            component_kinds.append("float" if isinstance(component, float) and not component.is_integer() else "int")
            continue
        if isinstance(component, float) and not component.is_integer():
            component_kinds[index] = "float"
    parameter.component_kinds = component_kinds
