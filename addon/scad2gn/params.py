from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any


def load_case_manifest(case_directory: str | Path) -> dict[str, Any]:
    manifest_path = Path(case_directory) / "params.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def generate_parameter_combinations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if not manifest:
        return [{}]

    if "combinations" in manifest:
        combinations = manifest["combinations"]
        return [dict(item) for item in combinations] or [{}]

    parameters = manifest.get("parameters", {})
    if not parameters:
        return [{}]

    keys = list(parameters)
    values = []
    for key in keys:
        raw_value = parameters[key]
        if isinstance(raw_value, list):
            values.append(raw_value)
        else:
            values.append([raw_value])
    return [dict(zip(keys, combination)) for combination in itertools.product(*values)]


def serialize_scad_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "undef"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(serialize_scad_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ",".join(f"{serialize_scad_value(key)}:{serialize_scad_value(item)}" for key, item in value.items())
        return "{" + items + "}"
    raise TypeError(f"Unsupported SCAD value: {value!r}")


def parameter_slug(parameters: dict[str, Any]) -> str:
    if not parameters:
        return "default"
    parts = []
    for key in sorted(parameters):
        value = parameters[key]
        value_text = json.dumps(value, sort_keys=True)
        safe_value = "".join(character if character.isalnum() else "_" for character in value_text).strip("_")
        parts.append(f"{key}_{safe_value}")
    return "__".join(parts)


def discover_case_directories(test_root: str | Path) -> list[Path]:
    root = Path(test_root)
    cases = []
    for scad_file in root.rglob("model.scad"):
        cases.append(scad_file.parent)
    return sorted(cases)
