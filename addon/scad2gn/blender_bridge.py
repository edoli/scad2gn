from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from .errors import BlenderConversionError, EvaluationError
from .ir import BooleanNode, ExtrudeNode, IRNode, PrimitiveNode, TransformNode
from .runtime import collect_top_level_defaults, load_ir_from_file

GENERATED_COLLECTION_NAME = "SCAD2GN Generated"


@dataclass(slots=True)
class Profile2D:
    points: list[tuple[float, float]]

    def transformed(self, matrix: Matrix) -> "Profile2D":
        transformed = []
        for x, y in self.points:
            result = matrix @ Vector((x, y, 1.0))
            transformed.append((float(result.x), float(result.y)))
        return Profile2D(points=transformed)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        if curve.users == 0:
            bpy.data.curves.remove(curve)


def create_scad_object(scad_path: str, parameters: dict | None = None, object_name: str | None = None):
    source_path = Path(scad_path)
    params = parameters or {}
    ir = load_ir_from_file(source_path, params)
    if ir is None:
        raise BlenderConversionError(f"No geometry generated for {source_path}")

    source_object = _compile_3d(ir, source_path.stem)
    _bake_object_transform(source_object)
    source_object.hide_set(True)
    source_object.hide_render = True
    source_object.name = f"{source_path.stem}_Source"

    wrapper = _create_wrapper_object(source_object, object_name or source_path.stem)
    defaults = collect_top_level_defaults(source_path)
    wrapper["scad_source_path"] = str(source_path)
    wrapper["scad_params_json"] = json.dumps(params, sort_keys=True)
    wrapper["scad_defaults_json"] = json.dumps(defaults, sort_keys=True)
    wrapper["scad_generated_source"] = source_object.name
    wrapper["scad_last_error"] = ""
    return wrapper


def rebuild_scad_object(wrapper_object, parameters: dict | None = None):
    source_path = wrapper_object.get("scad_source_path")
    if not source_path:
        raise BlenderConversionError("Selected object is not managed by SCAD2GN")

    params = parameters
    if params is None:
        raw_params = wrapper_object.get("scad_params_json", "{}")
        params = json.loads(raw_params)

    old_source_name = wrapper_object.get("scad_generated_source")
    old_source = bpy.data.objects.get(old_source_name) if old_source_name else None

    new_wrapper = create_scad_object(source_path, params, object_name=wrapper_object.name)
    wrapper_object["scad_params_json"] = new_wrapper["scad_params_json"]
    wrapper_object["scad_defaults_json"] = new_wrapper["scad_defaults_json"]
    wrapper_object["scad_generated_source"] = new_wrapper["scad_generated_source"]
    wrapper_object["scad_last_error"] = ""
    _update_wrapper_node_group(wrapper_object, bpy.data.objects[new_wrapper["scad_generated_source"]])

    bpy.data.objects.remove(new_wrapper, do_unlink=True)
    if old_source is not None and old_source.name != wrapper_object["scad_generated_source"]:
        bpy.data.objects.remove(old_source, do_unlink=True)
    return wrapper_object


def export_wrapper_to_stl(wrapper_object, output_path: str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    wrapper_object.select_set(True)
    bpy.context.view_layer.objects.active = wrapper_object

    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(
            filepath=str(output),
            export_selected_objects=True,
            apply_modifiers=True,
            ascii_format=False,
        )
        return

    if hasattr(bpy.ops.export_mesh, "stl"):
        bpy.ops.export_mesh.stl(
            filepath=str(output),
            use_selection=True,
            ascii=False,
            use_mesh_modifiers=True,
        )
        return

    raise BlenderConversionError("No STL export operator is available in this Blender build")


def _compile_3d(node: IRNode, name: str):
    if isinstance(node, PrimitiveNode):
        if node.kind == "cube":
            return _create_cube(node.params, name)
        if node.kind == "sphere":
            return _create_sphere(node.params, name)
        if node.kind == "cylinder":
            return _create_cylinder(node.params, name)
        raise BlenderConversionError(f"Unsupported 3D primitive: {node.kind}")

    if isinstance(node, TransformNode):
        if _node_dimension(node.child) == 2:
            raise BlenderConversionError(f"Transform {node.kind}() produced 2D geometry where 3D was required")
        obj = _compile_3d(node.child, name)
        _apply_transform_to_object(obj, node)
        return obj

    if isinstance(node, BooleanNode):
        objects = [_compile_3d(child, f"{name}_{index}") for index, child in enumerate(node.children)]
        return _apply_boolean(node.kind, objects, name)

    if isinstance(node, ExtrudeNode):
        profile = _compile_2d(node.child)
        if node.kind == "linear_extrude":
            return _create_mesh_object(name, *_linear_extrude(profile, node.params))
        if node.kind == "rotate_extrude":
            return _create_mesh_object(name, *_rotate_extrude(profile, node.params))
        raise BlenderConversionError(f"Unsupported extrusion: {node.kind}")

    raise BlenderConversionError(f"Unsupported IR node: {type(node).__name__}")


def _compile_2d(node: IRNode) -> Profile2D:
    if isinstance(node, PrimitiveNode):
        if node.kind == "circle":
            return _profile_circle(node.params)
        if node.kind == "square":
            return _profile_square(node.params)
        if node.kind == "polygon":
            return _profile_polygon(node.params)
        raise BlenderConversionError(f"Unsupported 2D primitive: {node.kind}")

    if isinstance(node, TransformNode):
        if _node_dimension(node.child) != 2:
            raise BlenderConversionError(f"Transform {node.kind}() cannot be applied to 3D geometry in a 2D context")
        profile = _compile_2d(node.child)
        return profile.transformed(_profile_transform_matrix(node))

    raise BlenderConversionError(f"Unsupported 2D IR node: {type(node).__name__}")


def _node_dimension(node: IRNode) -> int:
    if isinstance(node, PrimitiveNode):
        return 2 if node.kind in {"circle", "square", "polygon"} else 3
    if isinstance(node, TransformNode):
        return _node_dimension(node.child)
    if isinstance(node, BooleanNode):
        return 3
    if isinstance(node, ExtrudeNode):
        return 3
    raise BlenderConversionError(f"Unknown node dimension: {type(node).__name__}")


def _create_cube(params: dict, name: str):
    positional = params.get("_positional", [])
    size = params.get("size", positional[0] if positional else 1.0)
    center = bool(params.get("center", positional[1] if len(positional) > 1 else False))
    dimensions = _vector3(size)
    half = [value / 2.0 for value in dimensions]
    if center:
        min_corner = (-half[0], -half[1], -half[2])
        max_corner = (half[0], half[1], half[2])
    else:
        min_corner = (0.0, 0.0, 0.0)
        max_corner = tuple(dimensions)
    verts = [
        (min_corner[0], min_corner[1], min_corner[2]),
        (max_corner[0], min_corner[1], min_corner[2]),
        (max_corner[0], max_corner[1], min_corner[2]),
        (min_corner[0], max_corner[1], min_corner[2]),
        (min_corner[0], min_corner[1], max_corner[2]),
        (max_corner[0], min_corner[1], max_corner[2]),
        (max_corner[0], max_corner[1], max_corner[2]),
        (min_corner[0], max_corner[1], max_corner[2]),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return _create_mesh_object(name, verts, faces)


def _create_sphere(params: dict, name: str):
    positional = params.get("_positional", [])
    radius = params.get("r")
    if radius is None and "d" in params:
        radius = float(params["d"]) / 2.0
    if radius is None and positional:
        radius = positional[0]
    if radius is None:
        radius = 1.0
    tessellation = params.get("_tessellation", {})
    segments = _sphere_segment_count(float(radius), tessellation)
    ring_count = max(4, segments // 2)
    verts = []
    for ring_index in range(ring_count):
        theta = math.pi * (ring_index + 0.5) / ring_count
        z = float(radius) * math.cos(theta)
        ring_radius = float(radius) * math.sin(theta)
        for segment_index in range(segments):
            phi = (2.0 * math.pi * segment_index) / segments
            verts.append((ring_radius * math.cos(phi), ring_radius * math.sin(phi), z))

    faces = []
    top_ring = list(range(segments))
    bottom_ring = list(range((ring_count - 1) * segments, ring_count * segments))
    faces.append(tuple(reversed(top_ring)))
    for ring_index in range(ring_count - 1):
        for segment_index in range(segments):
            next_segment = (segment_index + 1) % segments
            a = ring_index * segments + segment_index
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment_index
            faces.append((a, b, c, d))
    faces.append(tuple(bottom_ring))
    return _create_mesh_object(name, verts, faces)


def _create_cylinder(params: dict, name: str):
    positional = params.get("_positional", [])
    height = float(params.get("h", positional[0] if positional else 1.0))
    radius_bottom = _resolve_radius(params, "r", "d", "r1", "d1", fallback=1.0)
    radius_top = _resolve_radius(params, "r", "d", "r2", "d2", fallback=radius_bottom)
    center = bool(params.get("center", False))
    tessellation = params.get("_tessellation", {})
    segments = _segment_count(max(radius_bottom, radius_top), tessellation)
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=max(8, segments),
        radius1=radius_bottom,
        radius2=radius_top,
        depth=height,
    )
    if not center:
        translation = Matrix.Translation(Vector((0.0, 0.0, height / 2.0)))
        bmesh.ops.transform(bm, matrix=translation, verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    return _link_mesh_object(name, mesh)


def _profile_circle(params: dict) -> Profile2D:
    positional = params.get("_positional", [])
    radius = params.get("r")
    if radius is None and "d" in params:
        radius = float(params["d"]) / 2.0
    if radius is None and positional:
        radius = positional[0]
    if radius is None:
        radius = 1.0
    tessellation = params.get("_tessellation", {})
    segments = _segment_count(float(radius), tessellation)
    points = []
    for index in range(max(8, segments)):
        angle = (2.0 * math.pi * index) / max(8, segments)
        points.append((float(radius) * math.cos(angle), float(radius) * math.sin(angle)))
    return Profile2D(points=points)


def _profile_square(params: dict) -> Profile2D:
    positional = params.get("_positional", [])
    size = params.get("size", positional[0] if positional else 1.0)
    center = bool(params.get("center", positional[1] if len(positional) > 1 else False))
    width, height = _vector2(size)
    min_x = -width / 2.0 if center else 0.0
    min_y = -height / 2.0 if center else 0.0
    points = [
        (min_x, min_y),
        (min_x + width, min_y),
        (min_x + width, min_y + height),
        (min_x, min_y + height),
    ]
    return Profile2D(points=points)


def _profile_polygon(params: dict) -> Profile2D:
    points = params.get("points")
    if points is None and params.get("_positional"):
        points = params["_positional"][0]
    if not isinstance(points, list) or len(points) < 3:
        raise BlenderConversionError("polygon() requires at least three points")
    paths = params.get("paths")
    if paths:
        if not isinstance(paths, list) or len(paths) != 1:
            raise BlenderConversionError("polygon() currently supports only a single path")
        indices = paths[0]
        return Profile2D(points=[tuple(_vector2(points[index])) for index in indices])
    return Profile2D(points=[tuple(_vector2(point)) for point in points])


def _linear_extrude(profile: Profile2D, params: dict):
    height = float(params.get("height", params.get("_positional", [1.0])[0] if params.get("_positional") else 1.0))
    center = bool(params.get("center", False))
    if not math.isclose(float(params.get("twist", 0.0)), 0.0):
        raise BlenderConversionError("linear_extrude(twist=...) is not supported yet")
    scale = params.get("scale", 1.0)
    if isinstance(scale, (int, float)):
        if not math.isclose(float(scale), 1.0):
            raise BlenderConversionError("linear_extrude(scale=...) is not supported yet")
    elif list(scale) != [1.0, 1.0]:
        raise BlenderConversionError("linear_extrude(scale=...) is not supported yet")

    bottom_z = -height / 2.0 if center else 0.0
    top_z = bottom_z + height
    points = profile.points
    bottom = [(x, y, bottom_z) for x, y in points]
    top = [(x, y, top_z) for x, y in points]
    verts = bottom + top
    faces = [tuple(reversed(range(len(points)))), tuple(range(len(points), len(points) * 2))]
    for index in range(len(points)):
        next_index = (index + 1) % len(points)
        faces.append((index, next_index, len(points) + next_index, len(points) + index))
    return verts, faces


def _rotate_extrude(profile: Profile2D, params: dict):
    angle = float(params.get("angle", 360.0))
    if angle <= 0.0 or angle > 360.0:
        raise BlenderConversionError("rotate_extrude(angle=...) must be between 0 and 360")
    tessellation = params.get("_tessellation", {})
    max_radius = max(point[0] for point in profile.points)
    if max_radius <= 0.0:
        raise BlenderConversionError("rotate_extrude() requires profile points with positive X radius")
    steps = max(8, _segment_count(max_radius, tessellation))
    if angle < 360.0:
        steps = max(2, round((angle / 360.0) * steps))
    total_steps = steps if math.isclose(angle, 360.0) else steps + 1

    verts = []
    for step in range(total_steps):
        theta = math.radians((angle / steps) * step)
        cosine = math.cos(theta)
        sine = math.sin(theta)
        for radius, z in profile.points:
            verts.append((radius * cosine, radius * sine, z))

    faces = []
    point_count = len(profile.points)
    ring_count = steps if math.isclose(angle, 360.0) else steps
    for ring in range(ring_count):
        next_ring = (ring + 1) % total_steps
        for point_index in range(point_count):
            next_point = (point_index + 1) % point_count
            a = ring * point_count + point_index
            b = ring * point_count + next_point
            c = next_ring * point_count + next_point
            d = next_ring * point_count + point_index
            faces.append((a, b, c, d))
    return verts, faces


def _apply_transform_to_object(obj, node: TransformNode) -> None:
    if node.kind == "translate":
        vector = _vector3(_first_argument(node.params, "v"))
        obj.data.transform(Matrix.Translation(Vector(vector)))
        obj.data.update()
        return

    if node.kind == "rotate":
        obj.data.transform(_rotation_matrix(node.params))
        obj.data.update()
        return

    if node.kind == "scale":
        vector = _vector3(_first_argument(node.params, "v", default=1.0))
        obj.data.transform(
            Matrix.Diagonal(Vector((vector[0], vector[1], vector[2], 1.0)))
        )
        obj.data.update()
        return

    if node.kind == "mirror":
        obj.data.transform(_mirror_matrix(_vector3(_first_argument(node.params, "v"))))
        obj.data.update()
        return

    if node.kind == "multmatrix":
        matrix = _matrix4(_first_argument(node.params, "m"))
        obj.data.transform(matrix)
        obj.data.update()
        return

    if node.kind == "resize":
        _apply_resize_to_object(obj, _vector3(_first_argument(node.params, "newsize")))
        return

    raise BlenderConversionError(f"Unsupported transform: {node.kind}")


def _profile_transform_matrix(node: TransformNode) -> Matrix:
    if node.kind == "translate":
        vector = _vector2(_first_argument(node.params, "v"))
        return Matrix(((1.0, 0.0, vector[0]), (0.0, 1.0, vector[1]), (0.0, 0.0, 1.0)))
    if node.kind == "rotate":
        angle = _resolve_profile_rotation(node.params)
        radians = math.radians(angle)
        return Matrix(
            (
                (math.cos(radians), -math.sin(radians), 0.0),
                (math.sin(radians), math.cos(radians), 0.0),
                (0.0, 0.0, 1.0),
            )
        )
    if node.kind == "scale":
        sx, sy = _vector2(_first_argument(node.params, "v", default=1.0))
        return Matrix(((sx, 0.0, 0.0), (0.0, sy, 0.0), (0.0, 0.0, 1.0)))
    if node.kind == "mirror":
        normal = _vector2(_first_argument(node.params, "v"))
        nx, ny = _normalize_vector(Vector((normal[0], normal[1], 0.0)))[:2]
        return Matrix(
            (
                (1.0 - 2.0 * nx * nx, -2.0 * nx * ny, 0.0),
                (-2.0 * ny * nx, 1.0 - 2.0 * ny * ny, 0.0),
                (0.0, 0.0, 1.0),
            )
        )
    if node.kind == "multmatrix":
        value = _first_argument(node.params, "m")
        rows = [list(map(float, row)) for row in value]
        if len(rows) == 3 and all(len(row) == 3 for row in rows):
            return Matrix(rows)
        if len(rows) == 4 and all(len(row) == 4 for row in rows):
            return Matrix(
                (
                    (rows[0][0], rows[0][1], rows[0][3]),
                    (rows[1][0], rows[1][1], rows[1][3]),
                    (0.0, 0.0, 1.0),
                )
            )
        raise BlenderConversionError("multmatrix() for 2D geometry requires a 3x3 or 4x4 matrix")
    if node.kind == "resize":
        raise BlenderConversionError("resize() on 2D geometry is not supported yet")
    raise BlenderConversionError(f"Unsupported 2D transform: {node.kind}")


def _apply_resize_to_object(obj, newsize: tuple[float, float, float]) -> None:
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    min_corner = Vector((min(vertex.x for vertex in coordinates), min(vertex.y for vertex in coordinates), min(vertex.z for vertex in coordinates)))
    max_corner = Vector((max(vertex.x for vertex in coordinates), max(vertex.y for vertex in coordinates), max(vertex.z for vertex in coordinates)))
    current_size = max_corner - min_corner
    center = (min_corner + max_corner) / 2.0
    scale = []
    for index, target in enumerate(newsize):
        source = current_size[index]
        if math.isclose(target, 0.0):
            scale.append(1.0)
        elif math.isclose(source, 0.0):
            raise BlenderConversionError("resize() cannot resize a zero-size dimension")
        else:
            scale.append(target / source)
    transform = (
        Matrix.Translation(center)
        @ Matrix.Diagonal(Vector((scale[0], scale[1], scale[2], 1.0)))
        @ Matrix.Translation(-center)
    )
    obj.data.transform(transform)
    obj.data.update()


def _apply_boolean(operation: str, objects: list, name: str):
    if len(objects) == 1:
        objects[0].name = name
        return objects[0]

    if operation not in {"union", "difference", "intersection"}:
        raise BlenderConversionError(f"Unsupported boolean operation: {operation}")

    base = objects[0]
    base.name = name
    operation_map = {
        "union": "UNION",
        "difference": "DIFFERENCE",
        "intersection": "INTERSECT",
    }
    for operand in objects[1:]:
        modifier = base.modifiers.new(name=f"SCAD2GN_{operation}", type="BOOLEAN")
        modifier.operation = operation_map[operation]
        modifier.solver = "EXACT"
        modifier.object = operand
        bpy.ops.object.select_all(action="DESELECT")
        base.select_set(True)
        bpy.context.view_layer.objects.active = base
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(operand, do_unlink=True)
    return base


def _create_mesh_object(name: str, verts: Iterable[tuple[float, float, float]], faces: Iterable[Iterable[int]]):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(list(verts), [], [tuple(face) for face in faces])
    mesh.update()
    return _link_mesh_object(name, mesh)


def _link_mesh_object(name: str, mesh):
    collection = _ensure_generated_collection()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def _create_wrapper_object(source_object, display_name: str):
    collection = _ensure_generated_collection()
    mesh = bpy.data.meshes.new(f"{display_name}_WrapperMesh")
    wrapper = bpy.data.objects.new(display_name, mesh)
    collection.objects.link(wrapper)
    node_group = _build_wrapper_node_group(display_name, source_object)
    modifier = wrapper.modifiers.new(name="SCAD2GN", type="NODES")
    modifier.node_group = node_group
    return wrapper


def _build_wrapper_node_group(display_name: str, source_object):
    group = bpy.data.node_groups.new(f"{display_name}_GN", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    output = group.nodes.new("NodeGroupOutput")
    object_info = group.nodes.new("GeometryNodeObjectInfo")
    object_info.transform_space = "RELATIVE"
    object_info.inputs["Object"].default_value = source_object
    output.location = (250, 0)
    group.links.new(object_info.outputs["Geometry"], output.inputs["Geometry"])
    return group


def _update_wrapper_node_group(wrapper_object, source_object) -> None:
    modifier = next((modifier for modifier in wrapper_object.modifiers if modifier.type == "NODES"), None)
    if modifier is None or modifier.node_group is None:
        raise BlenderConversionError("Wrapper object does not have a Geometry Nodes modifier")
    group = modifier.node_group
    object_info = next((node for node in group.nodes if node.bl_idname == "GeometryNodeObjectInfo"), None)
    if object_info is None:
        raise BlenderConversionError("Wrapper Geometry Nodes group is missing Object Info")
    object_info.inputs["Object"].default_value = source_object


def _ensure_generated_collection():
    collection = bpy.data.collections.get(GENERATED_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(GENERATED_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _segment_count(radius: float, tessellation: dict) -> int:
    fn = int(tessellation.get("fn", 0) or 0)
    if fn >= 3:
        return fn
    fa = float(tessellation.get("fa", 12.0) or 12.0)
    fs = float(tessellation.get("fs", 2.0) or 2.0)
    circumference = 2.0 * math.pi * max(radius, 1e-6)
    segments_by_angle = math.ceil(360.0 / max(fa, 1e-6))
    segments_by_size = math.ceil(circumference / max(fs, 1e-6))
    return max(8, segments_by_angle, segments_by_size)


def _sphere_segment_count(radius: float, tessellation: dict) -> int:
    fn = int(tessellation.get("fn", 0) or 0)
    if fn >= 8:
        return fn
    return _segment_count(radius, tessellation)


def _resolve_radius(params: dict, radius_key: str, diameter_key: str, alt_radius_key: str, alt_diameter_key: str, *, fallback: float) -> float:
    if radius_key in params:
        return float(params[radius_key])
    if diameter_key in params:
        return float(params[diameter_key]) / 2.0
    if alt_radius_key in params:
        return float(params[alt_radius_key])
    if alt_diameter_key in params:
        return float(params[alt_diameter_key]) / 2.0
    return float(fallback)


def _first_argument(params: dict, preferred_name: str, *, default=None):
    if preferred_name in params:
        return params[preferred_name]
    positional = params.get("_positional", [])
    if positional:
        return positional[0]
    if default is not None:
        return default
    raise BlenderConversionError(f"Missing required argument: {preferred_name}")


def _vector2(value) -> tuple[float, float]:
    if isinstance(value, (int, float)):
        return float(value), float(value)
    if len(value) == 3:
        return float(value[0]), float(value[1])
    if len(value) != 2:
        raise BlenderConversionError("Expected a 2D vector")
    return float(value[0]), float(value[1])


def _vector3(value) -> tuple[float, float, float]:
    if isinstance(value, (int, float)):
        scalar = float(value)
        return scalar, scalar, scalar
    if len(value) == 2:
        return float(value[0]), float(value[1]), 1.0
    if len(value) != 3:
        raise BlenderConversionError("Expected a 3D vector")
    return float(value[0]), float(value[1]), float(value[2])


def _matrix4(value) -> Matrix:
    rows = [list(map(float, row)) for row in value]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise BlenderConversionError("multmatrix() requires a 4x4 matrix for 3D geometry")
    return Matrix(rows)


def _rotation_matrix(params: dict) -> Matrix:
    if "a" in params and "v" in params:
        axis = Vector(_vector3(params["v"]))
        axis.normalize()
        return Matrix.Rotation(math.radians(float(params["a"])), 4, axis)
    value = _first_argument(params, "a", default=[0.0, 0.0, 0.0])
    if isinstance(value, (int, float)):
        return Matrix.Rotation(math.radians(float(value)), 4, "Z")
    vector = _vector3(value)
    return Euler(tuple(math.radians(component) for component in vector), "XYZ").to_matrix().to_4x4()


def _resolve_profile_rotation(params: dict) -> float:
    if "a" in params and "v" in params:
        axis = _vector3(params["v"])
        if not math.isclose(abs(axis[2]), 1.0, abs_tol=1e-6):
            raise BlenderConversionError("2D rotate(a=..., v=...) only supports the Z axis")
        return float(params["a"])
    value = _first_argument(params, "a", default=0.0)
    if isinstance(value, (int, float)):
        return float(value)
    vector = _vector3(value)
    return float(vector[2])


def _mirror_matrix(normal_value: tuple[float, float, float]) -> Matrix:
    normal = _normalize_vector(Vector(normal_value))
    nx, ny, nz = normal
    return Matrix(
        (
            (1.0 - 2.0 * nx * nx, -2.0 * nx * ny, -2.0 * nx * nz, 0.0),
            (-2.0 * ny * nx, 1.0 - 2.0 * ny * ny, -2.0 * ny * nz, 0.0),
            (-2.0 * nz * nx, -2.0 * nz * ny, 1.0 - 2.0 * nz * nz, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def _normalize_vector(vector: Vector) -> Vector:
    if math.isclose(vector.length, 0.0):
        raise BlenderConversionError("Cannot normalize a zero-length vector")
    return vector.normalized()


def _bake_object_transform(obj) -> None:
    if obj.matrix_world != Matrix.Identity(4):
        obj.data.transform(obj.matrix_world)
        obj.matrix_world = Matrix.Identity(4)
        obj.data.update()
