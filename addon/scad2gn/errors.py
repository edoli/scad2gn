from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLocation:
    line: int
    column: int


class Scad2GnError(Exception):
    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        location: SourceLocation | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.location = location

    def __str__(self) -> str:
        parts = [self.message]
        if self.path:
            parts.append(f"File: {self.path}")
        if self.location:
            parts.append(f"Line: {self.location.line}, Column: {self.location.column}")
        return "\n".join(parts)


class ScadLexerError(Scad2GnError):
    pass


class ScadParseError(Scad2GnError):
    pass


class EvaluationError(Scad2GnError):
    pass


class UnsupportedFeatureError(Scad2GnError):
    pass


class BlenderConversionError(Scad2GnError):
    pass
