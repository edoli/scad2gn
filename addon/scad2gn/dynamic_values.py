from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DynamicExpression:
    kind: str
    operation: str
    dependencies: frozenset[str]
    parameter_name: str | None = None
    component: int | None = None
    operator: str | None = None
    operand: Any = None
    left: Any = None
    right: Any = None


class UnsupportedDynamicParametersError(Exception):
    def __init__(self, parameter_names: set[str]) -> None:
        super().__init__(", ".join(sorted(parameter_names)))
        self.parameter_names = set(parameter_names)


def dynamic_parameter(name: str, kind: str, *, component: int | None = None) -> DynamicExpression:
    return DynamicExpression(
        kind=kind,
        operation="parameter",
        dependencies=frozenset({name}),
        parameter_name=name,
        component=component,
    )


def is_dynamic(value: Any) -> bool:
    return isinstance(value, DynamicExpression)


def contains_dynamic(value: Any) -> bool:
    if is_dynamic(value):
        return True
    if isinstance(value, list):
        return any(contains_dynamic(item) for item in value)
    if isinstance(value, tuple):
        return any(contains_dynamic(item) for item in value)
    if isinstance(value, dict):
        return any(contains_dynamic(item) for item in value.values())
    return False


def collect_dynamic_dependencies(value: Any) -> set[str]:
    if is_dynamic(value):
        return set(value.dependencies)
    if isinstance(value, list):
        dependencies: set[str] = set()
        for item in value:
            dependencies.update(collect_dynamic_dependencies(item))
        return dependencies
    if isinstance(value, tuple):
        dependencies: set[str] = set()
        for item in value:
            dependencies.update(collect_dynamic_dependencies(item))
        return dependencies
    if isinstance(value, dict):
        dependencies: set[str] = set()
        for item in value.values():
            dependencies.update(collect_dynamic_dependencies(item))
        return dependencies
    return set()
