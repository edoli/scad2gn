from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from addon.scad2gn.customizer import collect_customizer_parameters_from_source
from addon.scad2gn.errors import UnsupportedFeatureError
from addon.scad2gn.ir import ConditionalNode, PrimitiveNode
from addon.scad2gn.params import discover_case_directories, generate_parameter_combinations, load_case_manifest
from addon.scad2gn.runtime import collect_top_level_defaults, load_ir_from_file, parse_source
from addon.scad2gn.evaluator import Evaluator
from addon.scad2gn.stl import compare_stl_meshes

REPO_ROOT = Path(__file__).resolve().parents[1]


class Scad2GnCoreTests(unittest.TestCase):
    def test_collect_customizer_parameters_respects_visibility_rules(self):
        source = textwrap.dedent(
            """
            /* [Dimensions] */
            // Width of the part
            width = 10; // [0:2:20]
            $fn = 32;
            height = width / 2;
            centered = true;
            name = "foo"; // [foo, bar]
            size = [1, 2.5, -3]; // [0:10]
            /* [Hidden] */
            debug = false;
            module stop_customizer() {}
            after_module = 3;
            """
        ).strip()

        parameters = collect_customizer_parameters_from_source(source, path="inline.scad")
        self.assertEqual([parameter.name for parameter in parameters], ["width", "$fn", "centered", "name", "size"])

        width = parameters[0]
        self.assertEqual(width.kind, "int")
        self.assertEqual(width.default, 10)
        self.assertEqual(width.description, "Width of the part")
        self.assertEqual(width.section, "Dimensions")
        self.assertEqual(width.minimum, 0)
        self.assertEqual(width.maximum, 20)
        self.assertEqual(width.step, 2)

        resolution = parameters[1]
        self.assertEqual(resolution.display_name, "Resolution")

        name = parameters[3]
        self.assertEqual(name.kind, "string")
        self.assertEqual([choice.value for choice in name.choices], ["foo", "bar"])

        size = parameters[4]
        self.assertEqual(size.kind, "vector")
        self.assertEqual(size.default, [1, 2.5, -3])
        self.assertEqual(size.component_kinds, ["int", "float", "int"])

    def test_parameterized_evaluator_keeps_only_used_customizer_inputs(self):
        source = textwrap.dedent(
            """
            base = 6;
            centered = true;
            label = "box";
            dims = [base + 2, (base / 2) * 2, base - 1];

            cube(size = dims, center = centered);
            """
        ).strip()

        program = parse_source(source, path="inline.scad")
        customizer = collect_customizer_parameters_from_source(source, path="inline.scad", program=program)
        ir, active = Evaluator(path="inline.scad").evaluate_parameterized(program, customizer)

        self.assertIsInstance(ir, PrimitiveNode)
        self.assertEqual([parameter.name for parameter in active], ["base", "centered"])

    def test_parameterized_evaluator_excludes_dynamic_loop_counts(self):
        source = textwrap.dedent(
            """
            count = 3;
            enabled = true;
            mode = "rack";
            step = 3.0;

            module peg(offset) {
                translate([offset, 0, 0])
                    cube([1, 1, 1], center = true);
            }

            module rack(step_size, item_count) {
                for (i = [0:item_count - 1]) {
                    peg(i * step_size);
                }
            }

            if (enabled && mode == "rack") {
                rack(step, count);
            } else {
                cube([1, 1, 1], center = true);
            }
            """
        ).strip()

        program = parse_source(source, path="inline.scad")
        customizer = collect_customizer_parameters_from_source(source, path="inline.scad", program=program)
        ir, active = Evaluator(path="inline.scad").evaluate_parameterized(program, customizer)

        self.assertIsInstance(ir, ConditionalNode)
        self.assertEqual([parameter.name for parameter in active], ["enabled", "mode", "step"])

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
