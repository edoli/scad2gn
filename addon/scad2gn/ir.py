from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import SourceLocation


@dataclass(slots=True)
class IRNode:
    location: SourceLocation


@dataclass(slots=True)
class PrimitiveNode(IRNode):
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TransformNode(IRNode):
    kind: str
    params: dict[str, Any]
    child: IRNode


@dataclass(slots=True)
class BooleanNode(IRNode):
    kind: str
    children: list[IRNode]


@dataclass(slots=True)
class ExtrudeNode(IRNode):
    kind: str
    params: dict[str, Any]
    child: IRNode
