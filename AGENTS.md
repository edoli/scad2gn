# AGENTS.md

## Project

SCAD2GN is a Blender add-on that imports OpenSCAD `.scad` files and builds equivalent Blender Geometry Nodes networks.

Core constraints:

* Target Blender version is 5.1.
* Imported `.scad` geometry must be represented with Geometry Nodes, not baked source mesh data.
* Mesh Boolean nodes must use the Manifold solver.
* If a feature cannot be represented procedurally, fail clearly instead of silently approximating it.

## Structure

```text
addon/
  __init__.py              Blender add-on registration
  operators.py            Import, rebuild, and export operators
  ui.py                   Sidebar UI
  scad2gn/
    parser.py             OpenSCAD parser
    evaluator.py          AST to IR evaluation
    ir.py                 Intermediate representation
    blender_bridge.py     IR to Blender Geometry Nodes

scripts/
  generate_openscad_stl.py
  export_blender_stl.py
  compare_stl.py
  validate_all.py
  validation_cases.py     Validation fixture discovery and parameter combinations
  validation_stl.py       STL loading and validation mesh comparison

test/
  scad/                   Validation fixture inputs
  openscad_stl/           Generated OpenSCAD reference STL files
  blender_stl/            Generated Blender STL files
  reports/                Validation reports
```

## Workflow

When changing behavior:

1. Read the relevant parser/evaluator/Geometry Nodes code before editing.
2. Add or update a focused `.scad` fixture under `test/scad/` when needed.
3. Keep OpenSCAD parsing, IR evaluation, Geometry Nodes generation, and validation concerns separate.
4. Run validation before considering the change done.
5. Do not rely on existing generated STL files; validation should regenerate Blender output.

## Useful Commands

Run Python/unit tests:

```bash
python test/test_scad2gn.py
```

Resolve Blender path from `.local/blender_path.txt`. If it is missing or invalid, discover Blender 5.1 and save it there.

Run full validation:

```bash
python scripts/validate_all.py --blender $blenderPath
```

Run one fixture:

```bash
python scripts/validate_all.py `
  --test-root test/scad/basic_cube `
  --blender $blenderPath
```

Export one Blender STL directly:

```bash
& $blenderPath `
  --background --factory-startup `
  --python scripts/export_blender_stl.py -- `
  --input test/scad/basic_cube/model.scad `
  --output .temp/basic_cube.stl `
  --params "{}"
```

## Validation Expectations

Always check validation after code changes that can affect geometry, transforms, parameters, export, STL comparison, or Blender node construction.

Validation compares:

* Bounding box
* Surface area
* Volume
* Sampled surface distance
* Normal/orientation consistency

Reports are written to:

```text
test/reports/latest.md
test/reports/latest.json
```

`FAIL` means the add-on output is not acceptable. `WARN` means the result is within failure tolerance but should be watched, usually because Blender and OpenSCAD tessellation differ.
