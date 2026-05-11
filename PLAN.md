# PLAN.md

## Project Overview

This project is a Blender add-on that converts OpenSCAD (`.scad`) files into Blender Geometry Nodes networks.

The goal is not only to parse OpenSCAD syntax, but also to reproduce the resulting geometry as accurately as possible using Blender-native procedural geometry. The add-on should allow users to import a `.scad` file, convert it into a Geometry Nodes setup, adjust supported parameters, generate the final object in Blender, and export the result.

Correctness is the highest priority. Every implemented feature must be validated against OpenSCAD output.


## Non-Negotiable Target Constraints

These constraints define the intended architecture and should not be relaxed without an explicit project decision:

* The target Blender version is Blender 5.1.
* Importing a `.scad` file into Blender must not create baked mesh geometry as the source representation.
* The imported object must be represented procedurally through Geometry Nodes.
* Any required Blender host object must remain an implementation detail and must not store the imported OpenSCAD shape as editable mesh vertices/faces.
* Mesh boolean operations inside Geometry Nodes must use the Manifold solver only.
* If a requested OpenSCAD feature cannot be represented procedurally yet, the importer must fail clearly or mark the feature unsupported. It must not silently fall back to baked mesh import.
* Test fixtures and sample models are validation inputs only. The implementation must not add conversion paths keyed to specific test cases, fixture names, or known sample files.
* The implementation must not rely on library- or sample-specific dedicated geometry generators as its primary strategy. Examples of prohibited direction include bespoke nodes or lowering paths such as `SpurGearNode`, `RingGearNode`, `ThreadedRodNode`, `ThreadedNutNode`, or BOSL2-specific shortcuts added only to satisfy current tests.
* A supported feature means any future user-provided `.scad` file using the same supported OpenSCAD constructs should convert through the same generic pipeline without new file-specific code.


## AST-First Conversion Requirement

The conversion pipeline must be driven from the parsed OpenSCAD AST at a low level.

Required direction:

* Parse the source file and preserve its structure through generic evaluation/lowering of expressions, variables, modules, functions, control flow, transforms, booleans, and other OpenSCAD language constructs.
* Build reusable Geometry Nodes generation from those generic constructs rather than introducing fixture-shaped shortcuts.
* Library code such as BOSL2 should work only because its OpenSCAD source is handled by the same generic AST/evaluation pipeline. It must not be supported through dedicated BOSL2-only conversion code added for the test suite.
* Validation failures should lead to missing generic feature support being implemented or marked unsupported, not to test-targeted code paths.


## Validation Process

For any supported `.scad` file:

1. OpenSCAD should generate a reference mesh.
2. This add-on should generate an equivalent Blender Geometry Nodes object.
3. The Blender-generated object should be exported as a mesh.
4. The two exported meshes should be compared.
5. Implementation is not considered complete until the generated Blender result matches the OpenSCAD result within an accepted tolerance.


## Assumptions

The development and validation environment assumes:

- OpenSCAD is installed and available from the command line.
- Blender 5.1 is installed and can be run in background mode.
- Test `.scad` files are provided under the `test/scad/` directory.
- Blender scripts can be executed in headless/background mode.
- STL files are used as the primary comparison format.
- The project may include Python scripts for parsing, conversion, testing, exporting, and comparison.


## Expected Test Directory Structure

Use the following structure unless there is a strong reason to change it:

```text
project-root/
  AGENTS.md
  addon/
    ...
  scripts/
    ...
  test/
    scad/
      .../
        model.scad
        params.json
    openscad_stl/
      ...
    blender_stl/
      ...
    reports/
      ...
```

Each test case should ideally live in its own folder.

Example:

```text
test/scad/basic_cube/
  model.scad
  params.json
```

`params.json` should describe parameter combinations to test.

Example:

```json
{
  "parameters": {
    "width": [10, 20],
    "height": [5, 15],
    "center": [true, false]
  }
}
```

The validation system should generate all meaningful parameter combinations unless the test case explicitly defines a fixed list of combinations.


## Validation Strategy

Validation must compare OpenSCAD-generated geometry with Blender-generated geometry.

For each test `.scad` file:

1. Read the `.scad` file.
2. Detect or load parameter definitions.
3. Generate one or more parameter combinations.
4. Use OpenSCAD to export reference STL files.
5. Use the Blender add-on to convert the `.scad` file into Geometry Nodes.
6. Apply the same parameter combinations inside Blender.
7. Generate the Blender object.
8. Export the Blender result as STL.
9. Compare the OpenSCAD STL and Blender STL.
10. Produce a validation report.

The implementation should continue to be improved until the comparison passes.


## OpenSCAD Reference Export

For every test case, generate reference STL files using OpenSCAD.

Example command pattern:

```bash
openscad \
  -o test/openscad_stl/basic_cube/width_10_height_5_center_true.stl \
  -D width=10 \
  -D height=5 \
  -D center=true \
  test/scad/basic_cube/model.scad
```

The validation system should:

* Create deterministic output file names.
* Include parameter values in the file name or metadata.
* Capture OpenSCAD stdout and stderr.
* Fail clearly if OpenSCAD cannot compile the file.
* Store logs for debugging.
* Avoid silently accepting OpenSCAD errors or warnings that affect geometry.


## Blender Geometry Nodes Export

For the same `.scad` file and parameter combination:

1. Run Blender in background mode.
2. Load the add-on or conversion script.
3. Convert the `.scad` file into a Geometry Nodes network.
4. Set the same parameters used for the OpenSCAD export.
5. Evaluate the final object without applying or baking the Geometry Nodes modifier.
6. Export the evaluated mesh as STL.

Example command pattern:

```bash
blender --background --python scripts/export_blender_stl.py -- \
  --input test/scad/basic_cube/model.scad \
  --output test/blender_stl/basic_cube/width_10_height_5_center_true.stl \
  --params '{"width":10,"height":5,"center":true}'
```

The Blender export script should:

* Run without requiring the UI.
* Clear the scene before each test.
* Use deterministic units and scale.
* Apply object transforms before export if needed.
* Export only the generated object.
* Ensure modifiers and Geometry Nodes are evaluated before STL export.
* Fail loudly if the conversion creates no object or invalid geometry.
* Fail if the imported source representation contains baked mesh vertices/faces.
* Verify that any evaluated mesh used for STL export is derived from Geometry Nodes, not from imported mesh data.


## Mesh Comparison

STL files generated by OpenSCAD and Blender should be compared automatically using python script.

Do not rely only on file size or vertex count. Meshes may be topologically different but geometrically equivalent.

Comparison should include multiple checks where possible:

* Bounding box comparison.
* Surface area comparison.
* Volume comparison.
* Triangle count comparison.
* Vertex/face count comparison.
* Hausdorff distance or nearest-surface distance.
* Normal consistency.
* Watertightness/manifold checks.
* Optional voxelized comparison for robust shape matching.

Suggested comparison stages:

### 1. Fast Metadata Comparison

Compare:

* Bounding box dimensions.
* Mesh volume.
* Surface area.
* Triangle count.

This catches obvious failures quickly.

### 2. Geometry Distance Comparison

Sample points on both meshes and measure bidirectional distances.

The comparison should pass only if the maximum or percentile distance is below a defined tolerance.

These values may need adjustment depending on OpenSCAD tessellation settings and Blender mesh generation behavior.

### 3. Visual Debug Output

When a comparison fails, generate debug artifacts:

* OpenSCAD STL.
* Blender STL.
* Difference report.
* Optional overlay scene.
* Optional screenshot from Blender.
* Optional sampled error heatmap.

The report should explain why the test failed.


## Tessellation and Resolution

OpenSCAD uses `$fn`, `$fa`, and `$fs` to control tessellation. Blender Geometry Nodes may generate curves, primitives, or meshes with different resolution behavior.

The converter must handle these carefully.

Rules:

* Respect `$fn`, `$fa`, and `$fs` where supported.
* Use equivalent segment counts in Blender primitives when possible.
* Avoid relying on Blender defaults for geometry resolution.
* Make tessellation deterministic.
* Document any known mismatch between OpenSCAD and Blender behavior.

If exact tessellation matching is not possible, the comparison should focus on geometric equivalence rather than exact triangle identity.


## Parameter Handling

The test runner should support parameterized `.scad` files.

Parameters may be provided by:

1. A `params.json` file beside the test `.scad` file.
2. Explicit command-line arguments.
3. Default values inside the `.scad` file.
4. Future automatic parameter extraction.

`params.json` is acceptable as validation metadata for choosing regression combinations, but runtime import behavior must not depend on test metadata. The importer must derive editable parameters from the `.scad` source itself.

Parameter combinations should be generated consistently.

Example:

```json
{
  "combinations": [
    {
      "width": 10,
      "height": 5,
      "center": true
    },
    {
      "width": 20,
      "height": 15,
      "center": false
    }
  ]
}
```

Support both explicit combinations and Cartesian-product style definitions.

For large parameter spaces, avoid generating excessive combinations by default. Allow each test case to define a maximum or curated set of representative cases.


## Blender Parameter and Customizer UI

Imported `.scad` files should eventually expose editable parameters in Blender in a way that is close to OpenSCAD's Customizer panel.

Goals:

* Detect top-level OpenSCAD variables that are safe to expose as user-editable parameters.
* Preserve default values from the `.scad` file.
* Parse OpenSCAD Customizer-style comments where practical, including labels, descriptions, ranges, steps, option lists, and grouping.
* Show exposed parameters on the imported object's Blender-side modifier controls so they are directly editable after import.
* Create Blender UI controls for exposed parameters using appropriate control types:
  * numeric inputs and sliders for numbers and ranges
  * checkboxes for booleans
  * dropdowns for enumerated options
  * vector controls for vector values
  * text inputs for strings where supported
* Keep the Blender UI synchronized with the generated Geometry Nodes group inputs.
* Support updating the object by changing Blender-side parameter values.
* Do not hard-code parameter lists for known sample files; extract them from the source file and Customizer metadata.

Geometry Nodes parameter rules:

* Exposable top-level SCAD variables should become Geometry Nodes group input sockets when their values influence supported procedural geometry.
* Primitive and transform node inputs should use socket links instead of hard-coded constants where the value depends on an exposed parameter.
* Expression-derived values should remain linked to parameter sockets where practical, using Geometry Nodes math/vector nodes instead of baking the evaluated result.
* If an expression cannot yet be represented procedurally in Geometry Nodes, document the limitation and either rebuild the node tree on parameter change through the same generic AST-driven pipeline or mark that parameter as non-live.

The long-term user experience should be:

1. Import a `.scad` file.
2. See the same meaningful parameters that would appear in OpenSCAD's Customizer.
3. Adjust those parameters in Blender.
4. Have Geometry Nodes update the generated geometry procedurally.
5. Export or validate the updated result.


## Supported OpenSCAD Features

Implement features incrementally.

Recommended implementation order:

1. Basic primitives:

   * `cube`
   * `sphere`
   * `cylinder`
   * `circle`
   * `square`
   * `polygon`

2. Transformations:

   * `translate`
   * `rotate`
   * `scale`
   * `resize`
   * `mirror`
   * `multmatrix`

3. Boolean operations:

   * `union`
   * `difference`
   * `intersection`

4. Extrusions:

   * `linear_extrude`
   * `rotate_extrude`

5. Variables and parameters:

   * numeric values
   * booleans
   * strings where relevant
   * vectors
   * simple expressions

6. Modules:

   * module definitions
   * module calls
   * nested modules
   * parameterized modules

7. Control flow:

   * `for`
   * `if`
   * `else`
   * list comprehensions where practical

8. Advanced features:

   * `hull`
   * `minkowski`
   * `offset`
   * `projection`
   * `surface`
   * `import`

Unsupported features must fail explicitly with clear error messages.

Do not silently ignore unsupported OpenSCAD constructs.


## Conversion Design Principles

The converter should preserve procedural structure whenever possible.

Must use Geometry Nodes representations instead of baking source geometry to mesh.

Tests are only evidence of correctness. They must never define the architecture or justify adding conversion code that only works for the current `test/scad/` samples.

For example:

* `translate()` should map to a transform node or equivalent transform operation.
* `union()` should map to join/boolean geometry behavior.
* `difference()` should use Blender boolean geometry when possible.
* Parameters should become editable Blender inputs where possible.
* Repeated structures should remain procedural if practical.

Correctness is more important than perfect procedural elegance, but mesh fallback is not allowed for imported source geometry. If a feature cannot yet be represented cleanly in Geometry Nodes, it should be implemented as an explicit unsupported feature with a clear error message and validation status.


## Blender 5.1 Compatibility

The project targets Blender 5.1 specifically.

Rules:

* Use Blender 5.1 Geometry Nodes APIs and socket names as the implementation target.
* Avoid compatibility shims for older Blender versions unless they are isolated and documented.
* Pin validation scripts and CI jobs to Blender 5.1.
* Record the exact Blender executable path and version in validation reports.
* Add a startup check that fails clearly when the add-on is run on an unsupported Blender version.


## Add-on Requirements

The Blender add-on should eventually provide:

* Import `.scad` file operation.
* Conversion to Geometry Nodes.
* Parameter UI for detected or provided parameters.
* Error reporting inside Blender.
* Rebuild/update button.
* Export generated result.
* Optional validation/debug mode.

The add-on should be usable both from:

* Blender UI.
* Blender background scripts.
* Automated tests.


## Automation Scripts

Recommended scripts:

```text
scripts/
  generate_openscad_stl.py
  export_blender_stl.py
  compare_stl.py
  validate_all.py
  validation_cases.py
  validation_stl.py
```

### `generate_openscad_stl.py`

Responsible for:

* Reading test cases.
* Reading parameter combinations.
* Running OpenSCAD.
* Writing reference STL files.
* Capturing logs.

### `export_blender_stl.py`

Responsible for:

* Running inside Blender.
* Loading the add-on/converter.
* Converting `.scad` to Geometry Nodes.
* Applying parameters.
* Exporting evaluated STL.

### `compare_stl.py`

Responsible for:

* Loading two STL files.
* Running comparison checks.
* Producing pass/fail output.
* Writing detailed difference reports.

### `validate_all.py`

Responsible for:

* Running the full validation pipeline.
* Coordinating OpenSCAD export.
* Coordinating Blender export.
* Running mesh comparisons.
* Producing a summary report.


## Validation Report

Every validation run should generate a report.

The report should include:

* Test case name.
* `.scad` input path.
* Parameter combination.
* OpenSCAD STL path.
* Blender STL path.
* Pass/fail result.
* Bounding box difference.
* Volume difference.
* Surface area difference.
* Distance metrics.
* Error messages, if any.
* Links or paths to debug artifacts.

Recommended output formats:

* Human-readable Markdown report.
* Machine-readable JSON report.

Example:

```text
test/reports/latest.md
test/reports/latest.json
```


## CI Expectations

The project should eventually support CI validation.

CI should be able to:

* Install or locate OpenSCAD.
* Install or locate Blender.
* Run the test suite in background mode.
* Export reference and generated STLs.
* Compare results.
* Fail if any required test case does not pass.

Because Blender and OpenSCAD can be heavy dependencies, CI may support multiple levels:

### Fast CI

Runs parser and unit tests only.

### Geometry CI

Runs selected representative `.scad` files.

### Full Validation CI

Runs all `.scad` validation cases and mesh comparisons.


## Determinism Requirements

Validation depends on deterministic output.

All scripts should:

* Use fixed tessellation settings where possible.
* Avoid random sampling unless a fixed seed is used.
* Use consistent units.
* Use consistent coordinate systems.
* Apply transforms before export where needed.
* Normalize STL output if required before comparison.
* Avoid relying on object names generated by Blender defaults.


## Error Handling

Errors should be clear and actionable.

Bad behavior:

```text
Conversion failed.
```

Better behavior:

```text
Unsupported OpenSCAD feature: minkowski()
File: test/scad/example/model.scad
Line: 24
Suggestion: implement minkowski support or mark this test as expected unsupported.
```

The converter should distinguish between:

* Parse errors.
* Unsupported syntax.
* Unsupported geometry operations.
* Blender node construction errors.
* Export errors.
* Mesh comparison failures.
* OpenSCAD compilation errors.


## Development Workflow for Agents

When working on this project, follow this workflow:

1. Pick one OpenSCAD feature or failing test case.
2. Understand the expected OpenSCAD behavior.
3. Add or update a minimal `.scad` test case.
4. Generate the OpenSCAD reference STL.
5. Implement or improve the converter.
6. Generate the Blender STL.
7. Compare the two STL files.
8. Inspect failures using reports and debug artifacts.
9. Iterate until the test passes.
10. Add regression coverage so the behavior does not break later.

Do not implement large unsupported areas without tests.

Do not mark a feature complete until it passes validation against OpenSCAD output.


## Coding Guidelines

General rules:

* Prefer clear, maintainable code over clever abstractions.
* Keep parser, intermediate representation, Blender node generation, and validation logic separate.
* Add tests for every supported OpenSCAD feature.
* Keep feature support explicit.
* Avoid silently approximating behavior unless documented.
* Use type hints in Python where practical.
* Use structured logging for scripts.
* Make command-line scripts usable independently.
* Keep generated files out of source control unless they are intentional fixtures.

The converter should ideally use an intermediate representation between OpenSCAD parsing and Blender node generation.

Example flow:

```text
SCAD source
  -> parser
  -> OpenSCAD-like AST
  -> normalized intermediate representation
  -> Blender Geometry Nodes builder
  -> evaluated Blender object
```


## Intermediate Representation

Use an intermediate representation if possible.

The IR should describe geometry and operations independently of Blender implementation details.

Example concepts:

* Primitive nodes.
* Transform nodes.
* Boolean operation nodes.
* Extrusion nodes.
* Parameter references.
* Module instances.
* Expression values.

This makes the project easier to test without launching Blender for every parser-level change.


## Test Case Requirements

Each new supported feature should include:

* A minimal `.scad` test.
* At least one parameterized test if the feature accepts parameters.
* A validation entry.
* Expected pass/fail status.
* Notes for any known approximation.

Good test cases are small and focused.

Avoid starting with complex real-world models before the basic feature suite is stable.


## Handling Unsupported Features

Unsupported features should be tracked explicitly.

A test case may be marked as expected unsupported, but only with a reason.

Example:

```json
{
  "expected_status": "unsupported",
  "reason": "minkowski() is not implemented yet"
}
```

Unsupported tests should not be confused with failed supported tests.


## Mesh Comparison Limitations

Mesh comparison is not always straightforward.

The same shape may have:

* Different triangulation.
* Different vertex order.
* Different face orientation.
* Slightly different floating-point coordinates.
* Different tessellation strategy.
* Different internal topology.

Therefore, exact STL text or binary equality is not required.

The goal is geometric equivalence, not byte-for-byte identity.

However, for simple primitives where exact matching is possible, stricter checks may be useful.


## Priority Order

When deciding what to work on, prioritize:

1. Correctness against OpenSCAD.
2. Pure procedural Geometry Nodes representation with no baked imported mesh data.
3. Deterministic validation.
4. Blender 5.1 compatibility.
5. Manifold-only Geometry Nodes boolean behavior.
6. Clear unsupported-feature reporting.
7. Small, well-tested feature increments.
8. Blender UI polish.
9. Performance optimization.

Do not prioritize UI polish before the conversion and validation pipeline is reliable.


## Definition of Done

A feature is considered done only when:

* The converter supports the intended OpenSCAD behavior.
* There is at least one `.scad` test case.
* Import creates a Geometry Nodes representation without baked source mesh data.
* Boolean Geometry Nodes, if used, are configured to use the Manifold solver.
* OpenSCAD reference STL generation succeeds.
* Blender Geometry Nodes generation succeeds.
* Blender STL export succeeds.
* Mesh comparison passes within tolerance.
* The validation report records the passing result.
* Unsupported edge cases are documented.


## Long-Term Goals

Long-term goals may include:

* Broader OpenSCAD language support.
* Editable Blender parameter UI.
* Live update when parameters change.
* Better mapping from OpenSCAD modules to reusable node groups.
* Visual diff tooling inside Blender.
* Automatic detection of OpenSCAD parameters.
* Support for importing existing OpenSCAD libraries.
* Support for common OpenSCAD community models.
* High-quality documentation and examples.


## Important Principle

The OpenSCAD output is the source of truth.

If Blender output differs from OpenSCAD output, assume the converter is wrong unless there is a documented and intentional limitation.

Always validate by generating geometry, exporting STL, and comparing results.
