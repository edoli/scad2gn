bl_info = {
    "name": "SCAD2GN",
    "author": "GitHub Copilot",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > SCAD2GN",
    "description": "Import a supported OpenSCAD subset and generate Blender geometry",
    "category": "Import-Export",
}

def register():
    import bpy

    from .operators import SCAD2GN_OT_export_stl, SCAD2GN_OT_import_scad, SCAD2GN_OT_rebuild_scad
    from .ui import SCAD2GN_PT_sidebar_panel, register_properties

    classes = (
        SCAD2GN_OT_import_scad,
        SCAD2GN_OT_rebuild_scad,
        SCAD2GN_OT_export_stl,
        SCAD2GN_PT_sidebar_panel,
    )

    register_properties()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    import bpy

    from .operators import SCAD2GN_OT_export_stl, SCAD2GN_OT_import_scad, SCAD2GN_OT_rebuild_scad
    from .ui import SCAD2GN_PT_sidebar_panel, unregister_properties

    classes = (
        SCAD2GN_OT_import_scad,
        SCAD2GN_OT_rebuild_scad,
        SCAD2GN_OT_export_stl,
        SCAD2GN_PT_sidebar_panel,
    )

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_properties()
