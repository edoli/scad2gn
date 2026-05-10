from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addon.scad2gn.stl import compare_stl_meshes, write_comparison_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two STL meshes")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--json-report")
    parser.add_argument("--markdown-report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare_stl_meshes(args.reference, args.candidate)
    if args.json_report and args.markdown_report:
        write_comparison_report(result, args.json_report, args.markdown_report)
    print("PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
