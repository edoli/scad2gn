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
from addon.scad2gn.stl import compare_stl_meshes  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenSCAD -> Blender STL validation pipeline")
    parser.add_argument("--test-root", default=str(REPO_ROOT / "test" / "scad"))
    parser.add_argument("--openscad-output-root", default=str(REPO_ROOT / "test" / "openscad_stl"))
    parser.add_argument("--blender-output-root", default=str(REPO_ROOT / "test" / "blender_stl"))
    parser.add_argument("--report-root", default=str(REPO_ROOT / "test" / "reports"))
    parser.add_argument("--openscad", default="openscad")
    parser.add_argument("--blender", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_root = Path(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    results = []

    for case_directory in discover_case_directories(args.test_root):
        manifest = load_case_manifest(case_directory)
        model_path = case_directory / "model.scad"
        combinations = generate_parameter_combinations(manifest)
        for combination in combinations:
            slug = parameter_slug(combination)
            openscad_output = Path(args.openscad_output_root) / case_directory.name / f"{slug}.stl"
            blender_output = Path(args.blender_output_root) / case_directory.name / f"{slug}.stl"
            openscad_output.parent.mkdir(parents=True, exist_ok=True)
            blender_output.parent.mkdir(parents=True, exist_ok=True)

            openscad_command = [args.openscad, "-o", str(openscad_output)]
            for key, value in combination.items():
                openscad_command.extend(["-D", f"{key}={serialize_scad_value(value)}"])
            openscad_command.append(str(model_path))
            openscad_run = subprocess.run(openscad_command, capture_output=True, text=True)
            if openscad_run.returncode != 0:
                raise SystemExit(
                    f"OpenSCAD export failed for {model_path} ({slug})\n{openscad_run.stdout}{openscad_run.stderr}"
                )

            blender_command = [
                args.blender,
                "--background",
                "--factory-startup",
                "--python",
                str(REPO_ROOT / "scripts" / "export_blender_stl.py"),
                "--",
                "--input",
                str(model_path),
                "--output",
                str(blender_output),
                "--params",
                json.dumps(combination, sort_keys=True),
            ]
            blender_run = subprocess.run(blender_command, capture_output=True, text=True)
            if blender_run.returncode != 0 or not blender_output.exists():
                raise SystemExit(
                    f"Blender export failed for {model_path} ({slug})\n{blender_run.stdout}{blender_run.stderr}"
                )

            comparison = compare_stl_meshes(openscad_output, blender_output)
            result = {
                "case": case_directory.name,
                "model_path": str(model_path),
                "parameters": combination,
                "openscad_stl": str(openscad_output),
                "blender_stl": str(blender_output),
                **comparison,
            }
            results.append(result)

    latest_json = report_root / "latest.json"
    latest_md = report_root / "latest.md"
    latest_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    latest_md.write_text(
        "\n".join(
            ["# Validation Report", ""]
            + [
                f"- {'PASS' if result['passed'] else 'FAIL'} `{result['case']}` `{parameter_slug(result['parameters'])}`"
                for result in results
            ]
        ),
        encoding="utf-8",
    )
    failures = [result for result in results if not result["passed"]]
    print(f"Validated {len(results)} case(s), failures: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
