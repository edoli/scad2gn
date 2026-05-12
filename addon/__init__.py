bl_info = {
    "name": "SCAD2GN",
    "author": "Daniel Jeon",
    "version": (0, 1, 0),
    "blender": (5, 1, 0),
    "location": "File > Import, View3D > Sidebar",
    "description": "Import OpenSCAD files as Blender Geometry Nodes setups",
    "category": "Import-Export",
}


def register() -> None:
    from .scad2gn.addon_runtime import register as runtime_register

    runtime_register()


def unregister() -> None:
    from .scad2gn.addon_runtime import unregister as runtime_unregister

    runtime_unregister()
