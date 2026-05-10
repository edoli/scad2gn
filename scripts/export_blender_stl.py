from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addon.scad2gn.blender_bridge import clear_scene, create_scad_object, export_wrapper_to_stl  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a .scad file to a Blender STL export")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--name", default="")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    clear_scene()
    wrapper = create_scad_object(args.input, json.loads(args.params), object_name=args.name or None)
    export_wrapper_to_stl(wrapper, args.output)
    return 0


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    raise SystemExit(main(arguments))
