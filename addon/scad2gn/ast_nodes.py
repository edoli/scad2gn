from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import SourceLocation


@dataclass(slots=True)
class Node:
    location: SourceLocation


@dataclass(slots=True)
class Expression(Node):
    pass


@dataclass(slots=True)
class Literal(Expression):
    value: Any


@dataclass(slots=True)
class Identifier(Expression):
    name: str


@dataclass(slots=True)
class VectorLiteral(Expression):
    items: list[Expression]


@dataclass(slots=True)
class RangeExpression(Expression):
    start: Expression
    end: Expression
    step: Expression | None = None


@dataclass(slots=True)
class UnaryExpression(Expression):
    operator: str
    operand: Expression


@dataclass(slots=True)
class BinaryExpression(Expression):
    operator: str
    left: Expression
    right: Expression


@dataclass(slots=True)
class ParameterDefinition(Node):
    name: str
    default: Expression | None = None


@dataclass(slots=True)
class Argument(Node):
    value: Expression
    name: str | None = None


@dataclass(slots=True)
class Statement(Node):
    pass


@dataclass(slots=True)
class Assignment(Statement):
    name: str
    value: Expression


@dataclass(slots=True)
class Block(Statement):
    statements: list[Statement] = field(default_factory=list)


@dataclass(slots=True)
class Call(Statement):
    name: str
    arguments: list[Argument] = field(default_factory=list)
    child: Statement | None = None


@dataclass(slots=True)
class ModuleDefinition(Statement):
    name: str
    parameters: list[ParameterDefinition]
    body: Statement


@dataclass(slots=True)
class IfStatement(Statement):
    condition: Expression
    then_branch: Statement
    else_branch: Statement | None = None


@dataclass(slots=True)
class ForStatement(Statement):
    variable: str
    iterable: Expression
    body: Statement


@dataclass(slots=True)
class Program(Node):
    statements: list[Statement] = field(default_factory=list)
