from __future__ import annotations

import json

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .scad2gn.blender_bridge import create_scad_object, export_wrapper_to_stl, rebuild_scad_object
from .scad2gn.errors import Scad2GnError


def _load_scene_params(context) -> dict:
    raw = context.scene.scad2gn_params_json.strip()
    if not raw:
        return {}
    return json.loads(raw)


class SCAD2GN_OT_import_scad(Operator, ImportHelper):
    bl_idname = "scad2gn.import_scad"
    bl_label = "Import OpenSCAD"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".scad"
    filter_glob: StringProperty(default="*.scad", options={"HIDDEN"})

    def execute(self, context):
        try:
            params = _load_scene_params(context)
            wrapper = create_scad_object(self.filepath, params, object_name=context.scene.scad2gn_object_name or None)
            context.scene.scad2gn_import_path = self.filepath
            context.scene.scad2gn_last_error = ""
            context.view_layer.objects.active = wrapper
            wrapper.select_set(True)
            return {"FINISHED"}
        except (Scad2GnError, json.JSONDecodeError) as error:
            context.scene.scad2gn_last_error = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class SCAD2GN_OT_rebuild_scad(Operator):
    bl_idname = "scad2gn.rebuild_scad"
    bl_label = "Rebuild Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active_object = context.active_object
        if active_object is None:
            self.report({"ERROR"}, "No active object selected")
            return {"CANCELLED"}
        try:
            params = _load_scene_params(context)
            rebuild_scad_object(active_object, params or None)
            active_object["scad_last_error"] = ""
            context.scene.scad2gn_last_error = ""
            return {"FINISHED"}
        except (Scad2GnError, json.JSONDecodeError) as error:
            active_object["scad_last_error"] = str(error)
            context.scene.scad2gn_last_error = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class SCAD2GN_OT_export_stl(Operator, ExportHelper):
    bl_idname = "scad2gn.export_stl"
    bl_label = "Export Selected STL"
    bl_options = {"REGISTER"}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def execute(self, context):
        active_object = context.active_object
        if active_object is None:
            self.report({"ERROR"}, "No active object selected")
            return {"CANCELLED"}
        try:
            export_wrapper_to_stl(active_object, self.filepath)
            context.scene.scad2gn_last_error = ""
            return {"FINISHED"}
        except Scad2GnError as error:
            context.scene.scad2gn_last_error = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
