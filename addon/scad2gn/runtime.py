from __future__ import annotations

from pathlib import Path

from .ast_nodes import Program
from .evaluator import Evaluator
from .parser import Parser


def parse_source(source: str, *, path: str | None = None) -> Program:
    return Parser(source, path=path).parse()


def load_program_from_file(path: str | Path) -> Program:
    source_path = Path(path)
    return parse_source(source_path.read_text(encoding="utf-8"), path=str(source_path))


def load_ir_from_file(path: str | Path, parameters: dict | None = None):
    source_path = Path(path)
    program = load_program_from_file(source_path)
    evaluator = Evaluator(parameters=parameters, path=str(source_path))
    return evaluator.evaluate(program)


def collect_top_level_defaults(path: str | Path) -> dict[str, object]:
    source_path = Path(path)
    program = load_program_from_file(source_path)
    evaluator = Evaluator(path=str(source_path))
    return evaluator.collect_top_level_defaults(program)
