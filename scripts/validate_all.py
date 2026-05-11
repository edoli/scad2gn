from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validation_cases import (  # noqa: E402
    discover_case_directories,
    generate_parameter_combinations,
    load_case_manifest,
    parameter_slug,
    serialize_scad_value,
)
from scripts.validation_stl import compare_stl_meshes  # noqa: E402


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
    test_root = Path(args.test_root).resolve()
    report_root = Path(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    results = []

    for case_directory in discover_case_directories(test_root):
        manifest = load_case_manifest(case_directory)
        model_path = case_directory / "model.scad"
        combinations = generate_parameter_combinations(manifest)
        for combination in combinations:
            slug = parameter_slug(combination)
            openscad_output = Path(args.openscad_output_root) / case_directory.name / f"{slug}.stl"
            blender_output = Path(args.blender_output_root) / case_directory.name / f"{slug}.stl"
            openscad_log_path = openscad_output.with_suffix(".log")
            blender_log_path = blender_output.with_suffix(".log")
            openscad_output.parent.mkdir(parents=True, exist_ok=True)
            blender_output.parent.mkdir(parents=True, exist_ok=True)
            if blender_output.exists():
                blender_output.unlink()
            if openscad_log_path.exists():
                openscad_log_path.unlink()
            if blender_log_path.exists():
                blender_log_path.unlink()

            openscad_command = [args.openscad, "-o", str(openscad_output)]
            for key, value in combination.items():
                openscad_command.extend(["-D", f"{key}={serialize_scad_value(value)}"])
            openscad_command.append(str(model_path))
            openscad_run = subprocess.run(openscad_command, capture_output=True, text=True)
            openscad_log = f"{openscad_run.stdout}{openscad_run.stderr}"
            openscad_log_path.write_text(openscad_log, encoding="utf-8")
            if openscad_run.returncode != 0 or not openscad_output.exists():
                results.append(
                    _failed_result(
                        case_directory=case_directory,
                        model_path=model_path,
                        parameters=combination,
                        openscad_output=openscad_output,
                        blender_output=blender_output,
                        openscad_log_path=openscad_log_path,
                        blender_log_path=blender_log_path,
                        stage="openscad",
                        error=f"OpenSCAD export failed for {model_path} ({slug})",
                    )
                )
                continue

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
            blender_log = f"{blender_run.stdout}{blender_run.stderr}"
            blender_log_path.write_text(blender_log, encoding="utf-8")
            blender_failed = blender_run.returncode != 0 or not blender_output.exists() or "Traceback (most recent call last)" in blender_log
            if blender_failed:
                results.append(
                    _failed_result(
                        case_directory=case_directory,
                        model_path=model_path,
                        parameters=combination,
                        openscad_output=openscad_output,
                        blender_output=blender_output,
                        openscad_log_path=openscad_log_path,
                        blender_log_path=blender_log_path,
                        stage="blender",
                        error=f"Blender export failed for {model_path} ({slug})",
                    )
                )
                continue

            comparison = compare_stl_meshes(openscad_output, blender_output)
            result = {
                "case": case_directory.name,
                "model_path": str(model_path),
                "parameters": combination,
                "openscad_stl": str(openscad_output),
                "openscad_log": str(openscad_log_path),
                "blender_stl": str(blender_output),
                "blender_log": str(blender_log_path),
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
                f"- {_result_status(result)} `{result['case']}` `{parameter_slug(result['parameters'])}`"
                for result in results
            ]
        ),
        encoding="utf-8",
    )
    failures = [result for result in results if not result["passed"]]
    warnings = [result for result in results if result.get("warning")]
    print(f"Validated {len(results)} case(s), failures: {len(failures)}, warnings: {len(warnings)}")
    return 1 if failures else 0


def _failed_result(
    *,
    case_directory: Path,
    model_path: Path,
    parameters: dict,
    openscad_output: Path,
    blender_output: Path,
    openscad_log_path: Path,
    blender_log_path: Path,
    stage: str,
    error: str,
) -> dict:
    return {
        "case": case_directory.name,
        "model_path": str(model_path),
        "parameters": parameters,
        "openscad_stl": str(openscad_output),
        "openscad_log": str(openscad_log_path),
        "blender_stl": str(blender_output),
        "blender_log": str(blender_log_path),
        "passed": False,
        "warning": False,
        "warnings": [],
        "stage": stage,
        "error": error,
    }


def _result_status(result: dict) -> str:
    if not result["passed"]:
        return "FAIL"
    if result.get("warning"):
        return "WARN"
    return "PASS"


if __name__ == "__main__":
    raise SystemExit(main())
