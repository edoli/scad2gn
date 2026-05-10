from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from addon.scad2gn.errors import UnsupportedFeatureError
from addon.scad2gn.params import discover_case_directories, generate_parameter_combinations, load_case_manifest
from addon.scad2gn.runtime import collect_top_level_defaults, load_ir_from_file, parse_source
from addon.scad2gn.evaluator import Evaluator
from addon.scad2gn.stl import compare_stl_meshes

REPO_ROOT = Path(__file__).resolve().parents[1]


class Scad2GnCoreTests(unittest.TestCase):
    def test_all_fixture_cases_parse_and_evaluate(self):
        cases = discover_case_directories(REPO_ROOT / "test" / "scad")
        self.assertGreater(len(cases), 0)
        for case_directory in cases:
            manifest = load_case_manifest(case_directory)
            defaults = collect_top_level_defaults(case_directory / "model.scad")
            self.assertIsInstance(defaults, dict)
            for combination in generate_parameter_combinations(manifest):
                with self.subTest(case=str(case_directory.name), parameters=combination):
                    ir = load_ir_from_file(case_directory / "model.scad", combination)
                    self.assertIsNotNone(ir)

    def test_unsupported_feature_raises_explicit_error(self):
        source = "minkowski() { cube(1); sphere(1); }"
        program = parse_source(source, path="inline.scad")
        with self.assertRaises(UnsupportedFeatureError):
            Evaluator(path="inline.scad").evaluate(program)

    def test_stl_compare_identical_meshes_passes(self):
        stl_text = textwrap.dedent(
            """
            solid sample
              facet normal 0 0 1
                outer loop
                  vertex 0 0 0
                  vertex 1 0 0
                  vertex 0 1 0
                endloop
              endfacet
            endsolid sample
            """
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.stl"
            second = Path(directory) / "second.stl"
            first.write_text(stl_text, encoding="utf-8")
            second.write_text(stl_text, encoding="utf-8")
            result = compare_stl_meshes(first, second)
            self.assertTrue(result["passed"])

    def test_stl_compare_reports_warning_below_failure_tolerance(self):
        reference_stl = textwrap.dedent(
            """
            solid sample
              facet normal 0 0 1
                outer loop
                  vertex 0 0 0
                  vertex 1 0 0
                  vertex 0 1 0
                endloop
              endfacet
            endsolid sample
            """
        ).strip()
        shifted_stl = textwrap.dedent(
            """
            solid sample
              facet normal 0 0 1
                outer loop
                  vertex 0.02 0 0
                  vertex 1.02 0 0
                  vertex 0.02 1 0
                endloop
              endfacet
            endsolid sample
            """
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.stl"
            second = Path(directory) / "second.stl"
            first.write_text(reference_stl, encoding="utf-8")
            second.write_text(shifted_stl, encoding="utf-8")
            result = compare_stl_meshes(first, second)
            self.assertTrue(result["passed"])
            self.assertTrue(result["warning"])
            self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
