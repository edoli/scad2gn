from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addon.scad2gn.params import (  # noqa: E402
    discover_case_directories,
    generate_parameter_combinations,
    load_case_manifest,
    parameter_slug,
    serialize_scad_value,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OpenSCAD STL fixtures from test/scad cases")
    parser.add_argument("--test-root", default=str(REPO_ROOT / "test" / "scad"))
    parser.add_argument("--output-root", default=str(REPO_ROOT / "test" / "openscad_stl"))
    parser.add_argument("--openscad", default="openscad")
    parser.add_argument("--case", help="Optional single case directory or model.scad path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    test_root = Path(args.test_root)
    output_root = Path(args.output_root)
    case_paths = [Path(args.case)] if args.case else discover_case_directories(test_root)

    for case_path in case_paths:
        directory = case_path.parent if case_path.name == "model.scad" else case_path
        model_path = directory / "model.scad"
        manifest = load_case_manifest(directory)
        for combination in generate_parameter_combinations(manifest):
            slug = parameter_slug(combination)
            output_path = output_root / directory.name / f"{slug}.stl"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            command = [args.openscad, "-o", str(output_path)]
            for key, value in combination.items():
                command.extend(["-D", f"{key}={serialize_scad_value(value)}"])
            command.append(str(model_path))
            completed = subprocess.run(command, capture_output=True, text=True)
            log_path = output_root / directory.name / f"{slug}.log"
            log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                raise SystemExit(
                    f"OpenSCAD export failed for {model_path} ({slug})\n{completed.stdout}{completed.stderr}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
