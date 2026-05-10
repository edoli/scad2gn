from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ast_nodes
from .runtime import load_program_from_file, parse_source

_SECTION_COMMENT_RE = re.compile(r"^\s*/\*\s*\[([^\]]+)\]\s*\*/\s*$")
_COMMENT_LINE_RE = re.compile(r"^\s*//(.*)$")


@dataclass(slots=True)
class CustomizerChoice:
    value: object
    label: str | None = None


@dataclass(slots=True)
class CustomizerParameter:
    name: str
    display_name: str
    kind: str
    default: object
    description: str | None = None
    section: str | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    choices: list[CustomizerChoice] = field(default_factory=list)
    component_kinds: list[str] = field(default_factory=list)


def collect_customizer_parameters(path: str | Path) -> list[CustomizerParameter]:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    program = load_program_from_file(source_path)
    return collect_customizer_parameters_from_source(source, path=str(source_path), program=program)


def collect_customizer_parameters_from_source(
    source: str,
    *,
    path: str | None = None,
    program: ast_nodes.Program | None = None,
) -> list[CustomizerParameter]:
    parsed_program = program or parse_source(source, path=path)
    first_brace = _find_first_brace_location(source)
    lines = source.splitlines()
    line_offsets = _line_offsets(source)
    section_by_line = _scan_sections(lines, first_brace.line if first_brace is not None else None)

    parameters: list[CustomizerParameter] = []
    for statement in parsed_program.statements:
        if not isinstance(statement, ast_nodes.Assignment):
            continue
        if first_brace is not None and not _location_before(statement.location, first_brace):
            continue

        literal_info = _extract_parameter_value(statement.value)
        if literal_info is None:
            continue

        section = section_by_line.get(statement.location.line)
        if section == "Hidden":
            continue

        statement_start = _offset_for_location(statement.location.line, statement.location.column, line_offsets)
        inline_hint = _extract_inline_hint(source, statement_start)
        parameter = CustomizerParameter(
            name=statement.name,
            display_name=_display_name_for_parameter(statement.name),
            kind=literal_info["kind"],
            default=literal_info["value"],
            description=_extract_description(lines, statement.location.line),
            section=section,
            component_kinds=literal_info.get("component_kinds", []),
        )
        _apply_customizer_hint(parameter, inline_hint)
        parameters.append(parameter)
    return parameters


def _extract_parameter_value(expression: ast_nodes.Expression) -> dict[str, object] | None:
    scalar = _extract_scalar_literal(expression)
    if scalar is not None:
        if isinstance(scalar, bool):
            return {"kind": "bool", "value": scalar}
        if isinstance(scalar, int):
            return {"kind": "int", "value": scalar}
        if isinstance(scalar, float):
            return {"kind": "float", "value": scalar}
        if isinstance(scalar, str):
            return {"kind": "string", "value": scalar}
        return None

    if not isinstance(expression, ast_nodes.VectorLiteral):
        return None
    if not 1 <= len(expression.items) <= 4:
        return None

    values: list[float | int] = []
    component_kinds: list[str] = []
    for item in expression.items:
        component = _extract_scalar_literal(item)
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            return None
        values.append(component)
        component_kinds.append("int" if isinstance(component, int) else "float")
    return {"kind": "vector", "value": values, "component_kinds": component_kinds}


def _extract_scalar_literal(expression: ast_nodes.Expression) -> object | None:
    if isinstance(expression, ast_nodes.Literal):
        if expression.value is None:
            return None
        return expression.value
    if isinstance(expression, ast_nodes.UnaryExpression) and expression.operator in {"+", "-"}:
        operand = _extract_scalar_literal(expression.operand)
        if isinstance(operand, bool) or not isinstance(operand, (int, float)):
            return None
        return operand if expression.operator == "+" else -operand
    return None


def _apply_customizer_hint(parameter: CustomizerParameter, hint: str | None) -> None:
    if not hint:
        return
    text = hint.strip()
    if not text:
        return

    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return

        if "," not in inner:
            range_parts = [part.strip() for part in inner.split(":")]
            if len(range_parts) == 1:
                maximum = _parse_numeric_token(range_parts[0], integer_only=parameter.kind == "int")
                if maximum is not None and parameter.kind in {"int", "float", "vector"}:
                    parameter.minimum = 0
                    parameter.maximum = maximum
                return
            if len(range_parts) in {2, 3}:
                minimum = _parse_numeric_token(range_parts[0], integer_only=False)
                maximum = _parse_numeric_token(range_parts[-1], integer_only=False)
                if minimum is not None and maximum is not None and parameter.kind in {"int", "float", "vector"}:
                    parameter.minimum = int(minimum) if parameter.kind == "int" else minimum
                    parameter.maximum = int(maximum) if parameter.kind == "int" else maximum
                    if len(range_parts) == 3:
                        step = _parse_numeric_token(range_parts[1], integer_only=False)
                        if step is not None:
                            parameter.step = int(step) if parameter.kind == "int" else step
                return

        parameter.choices = _parse_choices(inner, parameter)
        return

    if parameter.kind in {"int", "float", "vector"}:
        step = _parse_numeric_token(text, integer_only=False)
        if step is not None:
            parameter.step = int(step) if parameter.kind == "int" else step


def _parse_choices(inner: str, parameter: CustomizerParameter) -> list[CustomizerChoice]:
    if parameter.kind not in {"int", "float", "string"}:
        return []

    choices: list[CustomizerChoice] = []
    for item in [part.strip() for part in inner.split(",")]:
        if not item:
            continue
        raw_value = item
        label = None
        if ":" in item:
            raw_value, label = [part.strip() for part in item.split(":", 1)]
        value = _parse_choice_value(raw_value, parameter.kind)
        if value is None:
            return []
        choices.append(CustomizerChoice(value=value, label=label or None))
    return choices


def _parse_choice_value(raw: str, kind: str) -> object | None:
    if kind == "string":
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            parsed = parse_source(f"value = {raw};").statements[0]
            if isinstance(parsed, ast_nodes.Assignment) and isinstance(parsed.value, ast_nodes.Literal):
                return parsed.value.value
        return raw
    return _parse_numeric_token(raw, integer_only=kind == "int")


def _parse_numeric_token(raw: str, *, integer_only: bool) -> int | float | None:
    try:
        if integer_only:
            return int(raw)
        if "." not in raw and "e" not in raw.lower():
            return int(raw)
        return float(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return None


def _extract_description(lines: list[str], assignment_line: int) -> str | None:
    previous_index = assignment_line - 2
    if previous_index < 0:
        return None
    match = _COMMENT_LINE_RE.match(lines[previous_index])
    if match is None:
        return None
    description = match.group(1).strip()
    if not description or description.startswith("["):
        return None
    return description


def _scan_sections(lines: list[str], stop_line: int | None) -> dict[int, str | None]:
    current_section: str | None = None
    sections: dict[int, str | None] = {}
    last_line = stop_line if stop_line is not None else len(lines)
    for line_number in range(1, last_line + 1):
        line = lines[line_number - 1]
        match = _SECTION_COMMENT_RE.match(line)
        if match is not None:
            current_section = match.group(1).strip() or None
        sections[line_number] = current_section
    return sections


def _extract_inline_hint(source: str, statement_start: int) -> str | None:
    index = statement_start
    in_string: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in {'"', "'"}:
            in_string = char
            index += 1
            continue

        if char == ";":
            line_end = source.find("\n", index)
            if line_end == -1:
                line_end = len(source)
            trailing = source[index + 1 : line_end]
            comment_index = trailing.find("//")
            if comment_index == -1:
                return None
            hint = trailing[comment_index + 2 :].strip()
            return hint or None
        index += 1
    return None


def _find_first_brace_location(source: str):
    from .errors import SourceLocation

    line = 1
    column = 1
    index = 0
    in_string: str | None = None
    escaped = False
    while index < len(source):
        current = source[index]
        nxt = source[index : index + 2]

        if in_string is not None:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == in_string:
                in_string = None
            if current == "\n":
                line += 1
                column = 1
            else:
                column += 1
            index += 1
            continue

        if nxt == "//":
            while index < len(source) and source[index] != "\n":
                index += 1
                column += 1
            continue

        if nxt == "/*":
            index += 2
            column += 2
            while index < len(source) and source[index : index + 2] != "*/":
                if source[index] == "\n":
                    line += 1
                    column = 1
                    index += 1
                else:
                    index += 1
                    column += 1
            if index < len(source):
                index += 2
                column += 2
            continue

        if current in {'"', "'"}:
            in_string = current
            index += 1
            column += 1
            continue

        if current == "{":
            return SourceLocation(line, column)

        if current == "\n":
            line += 1
            column = 1
        else:
            column += 1
        index += 1
    return None


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(source):
        if character == "\n":
            offsets.append(index + 1)
    return offsets


def _offset_for_location(line: int, column: int, line_offsets: list[int]) -> int:
    return line_offsets[line - 1] + column - 1


def _location_before(left, right) -> bool:
    return (left.line, left.column) < (right.line, right.column)


def _display_name_for_parameter(name: str) -> str:
    if name == "$fn":
        return "Resolution"
    return name
