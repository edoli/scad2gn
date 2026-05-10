from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Panel


class SCAD2GN_PT_sidebar_panel(Panel):
    bl_label = "SCAD2GN"
    bl_idname = "SCAD2GN_PT_sidebar_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SCAD2GN"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active_object = context.active_object

        layout.prop(scene, "scad2gn_object_name")
        layout.prop(scene, "scad2gn_params_json")
        layout.operator("scad2gn.import_scad", text="Import .scad")

        if active_object is not None:
            layout.separator()
            layout.label(text=f"Active: {active_object.name}")
            if "scad_source_path" in active_object:
                layout.label(text=f"Source: {active_object['scad_source_path']}")
            if "scad_defaults_json" in active_object:
                layout.label(text="Detected defaults:")
                layout.label(text=active_object["scad_defaults_json"])
            layout.operator("scad2gn.rebuild_scad", text="Rebuild Selected")
            layout.operator("scad2gn.export_stl", text="Export Selected STL")

        if scene.scad2gn_last_error:
            layout.separator()
            layout.label(text="Last error:")
            for line in scene.scad2gn_last_error.splitlines():
                layout.label(text=line)


def register_properties():
    bpy.types.Scene.scad2gn_params_json = StringProperty(
        name="Params JSON",
        description="JSON object used to override top-level OpenSCAD variables",
        default="{}",
    )
    bpy.types.Scene.scad2gn_object_name = StringProperty(
        name="Object Name",
        description="Optional name for the generated wrapper object",
        default="",
    )
    bpy.types.Scene.scad2gn_import_path = StringProperty(
        name="Last Import Path",
        subtype="FILE_PATH",
        default="",
    )
    bpy.types.Scene.scad2gn_last_error = StringProperty(
        name="Last Error",
        default="",
    )


def unregister_properties():
    del bpy.types.Scene.scad2gn_last_error
    del bpy.types.Scene.scad2gn_import_path
    del bpy.types.Scene.scad2gn_object_name
    del bpy.types.Scene.scad2gn_params_json
