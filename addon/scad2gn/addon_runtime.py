from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper


SUPPORTED_BLENDER_VERSION = (5, 1)


def ensure_supported_blender_version() -> None:
    if bpy.app.version[:2] != SUPPORTED_BLENDER_VERSION:
        expected = ".".join(str(part) for part in SUPPORTED_BLENDER_VERSION)
        actual = bpy.app.version_string
        raise RuntimeError(f"SCAD2GN requires Blender {expected}. Found {actual}.")


def parse_parameters_json(value: str) -> dict[str, object]:
    text = value.strip()
    if not text:
        return {}
    parameters = json.loads(text)
    if not isinstance(parameters, dict):
        raise ValueError("Parameters JSON must decode to an object.")
    return parameters


def activate_imported_object(context: bpy.types.Context, imported_object: bpy.types.Object) -> None:
    for scene_object in context.scene.objects:
        scene_object.select_set(False)
    imported_object.select_set(True)
    context.view_layer.objects.active = imported_object


class SCAD2GN_OT_import_scad(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.scad2gn"
    bl_label = "Import OpenSCAD as Geometry Nodes"
    bl_description = "Import a .scad file and convert it into a Geometry Nodes object"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".scad"
    filter_glob: StringProperty(default="*.scad", options={"HIDDEN"})

    object_name: StringProperty(
        name="Object Name",
        description="Optional override for the imported object name",
        default="",
    )

    parameters_json: StringProperty(
        name="Parameters JSON",
        description="Optional JSON object with SCAD parameter overrides",
        default="{}",
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        from .blender_bridge import create_scad_object

        ensure_supported_blender_version()

        source_path = Path(self.filepath).resolve()
        if not source_path.exists():
            self.report({"ERROR"}, f"OpenSCAD file not found: {source_path}")
            return {"CANCELLED"}

        try:
            imported_object = create_scad_object(
                source_path,
                parse_parameters_json(self.parameters_json),
                object_name=self.object_name.strip() or None,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        activate_imported_object(context, imported_object)
        self.report({"INFO"}, f"Imported {source_path.name} as {imported_object.name}")
        return {"FINISHED"}


class SCAD2GN_FH_import_scad(bpy.types.FileHandler):
    bl_idname = "SCAD2GN_FH_import_scad"
    bl_label = "Import OpenSCAD as Geometry Nodes"
    bl_import_operator = SCAD2GN_OT_import_scad.bl_idname
    bl_file_extensions = ".scad"

    @classmethod
    def poll_drop(cls, context: bpy.types.Context) -> bool:
        return (
            context.area is not None
            and context.area.type in {"VIEW_3D", "OUTLINER"}
        )


class SCAD2GN_PT_sidebar(bpy.types.Panel):
    bl_label = "SCAD2GN"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SCAD2GN"

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator(SCAD2GN_OT_import_scad.bl_idname, icon="IMPORT")
        layout.label(text="Import .scad as Geometry Nodes")


CLASSES = (
    SCAD2GN_OT_import_scad,
    SCAD2GN_FH_import_scad,
    SCAD2GN_PT_sidebar,
)


def menu_func_import(self: bpy.types.TOPBAR_MT_file_import, _context: bpy.types.Context) -> None:
    self.layout.operator(SCAD2GN_OT_import_scad.bl_idname, text="OpenSCAD (.scad)")


def register() -> None:
    ensure_supported_blender_version()

    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
