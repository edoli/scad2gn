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


@dataclass(slots=True)
class Bounds3D:
    min_corner: Vector
    max_corner: Vector

    @property
    def center(self) -> Vector:
        return (self.min_corner + self.max_corner) / 2.0

    @property
    def size(self) -> Vector:
        return self.max_corner - self.min_corner


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

    wrapper = _create_wrapper_object(ir, object_name or source_path.stem)
    defaults = collect_top_level_defaults(source_path)
    wrapper["scad_source_path"] = str(source_path)
    wrapper["scad_params_json"] = json.dumps(params, sort_keys=True)
    wrapper["scad_defaults_json"] = json.dumps(defaults, sort_keys=True)
    wrapper["scad_generated_kind"] = "native_geometry_nodes"
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

    ir = load_ir_from_file(source_path, params)
    if ir is None:
        raise BlenderConversionError(f"No geometry generated for {source_path}")

    defaults = collect_top_level_defaults(source_path)
    _cleanup_helper_objects(wrapper_object.name)
    new_group = _build_wrapper_node_group(wrapper_object.name, ir)
    modifier = _ensure_nodes_modifier(wrapper_object)
    old_group = modifier.node_group
    modifier.node_group = new_group

    wrapper_object["scad_params_json"] = json.dumps(params, sort_keys=True)
    wrapper_object["scad_defaults_json"] = json.dumps(defaults, sort_keys=True)
    wrapper_object["scad_generated_kind"] = "native_geometry_nodes"
    wrapper_object["scad_last_error"] = ""
    _cleanup_legacy_generated_source(wrapper_object)
    if old_group is not None and old_group != new_group and old_group.users == 0:
        bpy.data.node_groups.remove(old_group)
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


def _create_wrapper_object(ir: IRNode, display_name: str):
    collection = _ensure_generated_collection()
    mesh = bpy.data.meshes.new(f"{display_name}_HostMesh")
    wrapper = bpy.data.objects.new(display_name, mesh)
    collection.objects.link(wrapper)
    node_group = _build_wrapper_node_group(display_name, ir)
    modifier = _ensure_nodes_modifier(wrapper)
    modifier.node_group = node_group
    return wrapper


def _build_wrapper_node_group(display_name: str, ir: IRNode):
    group = bpy.data.node_groups.new(f"{display_name}_GN", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    output = group.nodes.new("NodeGroupOutput")
    output.location = (1200, 0)
    builder = _GeometryNodesBuilder(group, display_name)
    geometry_socket = builder.build_geometry(ir, 0, 0)
    group.links.new(geometry_socket, output.inputs["Geometry"])
    return group


def _ensure_nodes_modifier(wrapper_object):
    modifier = next((modifier for modifier in wrapper_object.modifiers if modifier.type == "NODES"), None)
    if modifier is None:
        modifier = wrapper_object.modifiers.new(name="SCAD2GN", type="NODES")
    return modifier


def _cleanup_legacy_generated_source(wrapper_object) -> None:
    _cleanup_helper_objects(wrapper_object.name)
    old_source_name = wrapper_object.get("scad_generated_source")
    if old_source_name:
        old_source = bpy.data.objects.get(old_source_name)
        if old_source is not None:
            bpy.data.objects.remove(old_source, do_unlink=True)
        del wrapper_object["scad_generated_source"]


def _cleanup_helper_objects(owner_name: str) -> None:
    for obj in list(bpy.data.objects):
        if obj.get("scad_helper_owner") == owner_name:
            bpy.data.objects.remove(obj, do_unlink=True)


class _GeometryNodesBuilder:
    def __init__(self, group, owner_name: str) -> None:
        self.group = group
        self.owner_name = owner_name

    def build_geometry(self, node: IRNode, x: float, y: float):
        if isinstance(node, PrimitiveNode):
            return self._build_primitive(node, x, y)

        if isinstance(node, TransformNode):
            if _node_dimension(node.child) == 2:
                raise BlenderConversionError(f"2D transform {node.kind}() must be consumed by an extrusion node")
            child_socket = self.build_geometry(node.child, x - 220, y)
            child_bounds = _measure_ir_bounds(node.child)
            return self._build_transform(node, child_socket, child_bounds, x, y)

        if isinstance(node, BooleanNode):
            return self._build_boolean(node, x, y)

        if isinstance(node, ExtrudeNode):
            return self._build_extrude(node, x, y)

        raise BlenderConversionError(f"Unsupported IR node for Geometry Nodes: {type(node).__name__}")

    def _build_primitive(self, node: PrimitiveNode, x: float, y: float):
        if node.kind == "cube":
            primitive = self.group.nodes.new("GeometryNodeMeshCube")
            primitive.location = (x, y)
            size = _vector3(node.params.get("size", node.params.get("_positional", [1.0])[0] if node.params.get("_positional") else 1.0))
            primitive.inputs["Size"].default_value = size
            primitive.inputs["Vertices X"].default_value = 2
            primitive.inputs["Vertices Y"].default_value = 2
            primitive.inputs["Vertices Z"].default_value = 2
            geometry = primitive.outputs["Mesh"]
            if not bool(node.params.get("center", False)):
                geometry = self._add_transform(
                    geometry,
                    Vector((size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)),
                    Euler((0.0, 0.0, 0.0)),
                    Vector((1.0, 1.0, 1.0)),
                    x + 220,
                    y,
                )
            return geometry

        if node.kind == "sphere":
            primitive = self.group.nodes.new("GeometryNodeMeshUVSphere")
            primitive.location = (x, y)
            radius = _resolve_sphere_radius(node.params)
            tessellation = node.params.get("_tessellation", {})
            segments = _sphere_segment_count(radius, tessellation)
            primitive.inputs["Segments"].default_value = max(3, segments)
            primitive.inputs["Rings"].default_value = max(2, segments // 2)
            primitive.inputs["Radius"].default_value = radius
            return primitive.outputs["Mesh"]

        if node.kind == "cylinder":
            primitive = self.group.nodes.new("GeometryNodeMeshCone")
            primitive.location = (x, y)
            height = float(node.params.get("h", node.params.get("_positional", [1.0])[0] if node.params.get("_positional") else 1.0))
            radius_bottom = _resolve_radius(node.params, "r", "d", "r1", "d1", fallback=1.0)
            radius_top = _resolve_radius(node.params, "r", "d", "r2", "d2", fallback=radius_bottom)
            tessellation = node.params.get("_tessellation", {})
            segments = _segment_count(max(radius_bottom, radius_top), tessellation)
            primitive.inputs["Vertices"].default_value = max(8, segments)
            primitive.inputs["Side Segments"].default_value = 1
            primitive.inputs["Fill Segments"].default_value = 1
            primitive.inputs["Radius Top"].default_value = radius_top
            primitive.inputs["Radius Bottom"].default_value = radius_bottom
            primitive.inputs["Depth"].default_value = height
            primitive.fill_type = "NGON"
            geometry = primitive.outputs["Mesh"]
            if bool(node.params.get("center", False)):
                geometry = self._add_transform(
                    geometry,
                    Vector((0.0, 0.0, -height / 2.0)),
                    Euler((0.0, 0.0, 0.0)),
                    Vector((1.0, 1.0, 1.0)),
                    x + 220,
                    y,
                )
            return geometry

        raise BlenderConversionError(f"Unsupported 3D primitive for Geometry Nodes: {node.kind}")

    def _build_transform(
        self,
        node: TransformNode,
        child_socket,
        child_bounds: Bounds3D,
        x: float,
        y: float,
    ):
        translation, rotation, scale = _transform_components(node, child_bounds)
        flip_faces = _transform_flips_faces(node, child_bounds)
        return self._add_transform(child_socket, translation, rotation, scale, x, y, flip_faces=flip_faces)

    def _add_transform(
        self,
        geometry_socket,
        translation: Vector,
        rotation: Euler,
        scale: Vector,
        x: float,
        y: float,
        *,
        flip_faces: bool = False,
    ):
        transform = self.group.nodes.new("GeometryNodeTransform")
        transform.location = (x, y)
        self.group.links.new(geometry_socket, transform.inputs["Geometry"])
        transform.inputs["Translation"].default_value = translation
        transform.inputs["Rotation"].default_value = rotation
        transform.inputs["Scale"].default_value = scale
        geometry = transform.outputs["Geometry"]
        if flip_faces:
            flip = self.group.nodes.new("GeometryNodeFlipFaces")
            flip.location = (x + 220, y)
            self.group.links.new(geometry, flip.inputs["Mesh"])
            geometry = flip.outputs["Mesh"]
        return geometry

    def _build_boolean(self, node: BooleanNode, x: float, y: float):
        if not node.children:
            raise BlenderConversionError(f"Boolean node {node.kind}() has no children")
        operation_map = {
            "union": "UNION",
            "difference": "DIFFERENCE",
            "intersection": "INTERSECT",
        }

        if node.kind in {"union", "intersection"}:
            boolean_node = self.group.nodes.new("GeometryNodeMeshBoolean")
            boolean_node.location = (x, y)
            boolean_node.operation = operation_map[node.kind]
            boolean_node.solver = "MANIFOLD"
            for index, child in enumerate(node.children):
                child_socket = self.build_geometry(child, x - 420, y - (index * 240))
                self.group.links.new(child_socket, boolean_node.inputs[1])
            return boolean_node.outputs[0]

        current_socket = self.build_geometry(node.children[0], x - 420, y)
        for index, child in enumerate(node.children[1:], start=1):
            other_socket = self.build_geometry(child, x - 420, y - (index * 240))
            boolean_node = self.group.nodes.new("GeometryNodeMeshBoolean")
            boolean_node.location = (x + (index * 220), y - (index * 120))
            boolean_node.operation = operation_map[node.kind]
            boolean_node.solver = "MANIFOLD"
            self.group.links.new(current_socket, boolean_node.inputs[0])
            self.group.links.new(other_socket, boolean_node.inputs[1])
            current_socket = boolean_node.outputs[0]
        return current_socket

    def _build_extrude(self, node: ExtrudeNode, x: float, y: float):
        profile = _compile_2d(node.child)
        if node.kind == "linear_extrude":
            return self._build_linear_extrude(profile, node.params, x, y)
        if node.kind == "rotate_extrude":
            return self._build_rotate_extrude(profile, node.params, x, y)
        raise BlenderConversionError(f"Unsupported extrusion for Geometry Nodes: {node.kind}")

    def _build_linear_extrude(self, profile: Profile2D, params: dict, x: float, y: float):
        curve_socket = self._build_profile_curve(profile.points, x - 480, y)
        height = float(params.get("height", params.get("_positional", [1.0])[0] if params.get("_positional") else 1.0))
        path_line = self.group.nodes.new("GeometryNodeCurvePrimitiveLine")
        path_line.location = (x - 240, y + 160)
        path_line.inputs["Start"].default_value = (0.0, 0.0, 0.0)
        path_line.inputs["End"].default_value = (0.0, 0.0, height)

        curve_to_mesh = self.group.nodes.new("GeometryNodeCurveToMesh")
        curve_to_mesh.location = (x, y)
        self.group.links.new(path_line.outputs["Curve"], curve_to_mesh.inputs["Curve"])
        self.group.links.new(curve_socket, curve_to_mesh.inputs["Profile Curve"])
        curve_to_mesh.inputs["Fill Caps"].default_value = True
        geometry = curve_to_mesh.outputs["Mesh"]

        if bool(params.get("center", False)):
            geometry = self._add_transform(
                geometry,
                Vector((0.0, 0.0, -height / 2.0)),
                Euler((0.0, 0.0, 0.0)),
                Vector((1.0, 1.0, 1.0)),
                x + 220,
                y,
            )
        return geometry

    def _build_rotate_extrude(self, profile: Profile2D, params: dict, x: float, y: float):
        angle = float(params.get("angle", 360.0))
        if not math.isclose(angle, 360.0):
            raise BlenderConversionError("rotate_extrude(angle != 360) is not supported in the Blender 5.1 GN path yet")

        min_radius = min(point[0] for point in profile.points)
        if min_radius <= 0.0:
            raise BlenderConversionError("rotate_extrude() requires profile points with positive X radius in the GN path")

        tessellation = params.get("_tessellation", {})
        step_count = max(8, _segment_count(max(point[0] for point in profile.points), tessellation))

        shifted_points = [(point[0] - min_radius, point[1]) for point in profile.points]
        profile_socket = self._build_profile_curve(shifted_points, x - 680, y - 180)

        path_circle = self.group.nodes.new("GeometryNodeMeshCircle")
        path_circle.location = (x - 680, y + 140)
        path_circle.inputs["Vertices"].default_value = step_count
        path_circle.inputs["Radius"].default_value = min_radius

        path_curve = self.group.nodes.new("GeometryNodeMeshToCurve")
        path_curve.location = (x - 460, y + 140)
        self.group.links.new(path_circle.outputs["Mesh"], path_curve.inputs["Mesh"])

        curve_to_mesh = self.group.nodes.new("GeometryNodeCurveToMesh")
        curve_to_mesh.location = (x - 180, y)
        self.group.links.new(path_curve.outputs["Curve"], curve_to_mesh.inputs["Curve"])
        self.group.links.new(profile_socket, curve_to_mesh.inputs["Profile Curve"])
        curve_to_mesh.inputs["Fill Caps"].default_value = True
        return curve_to_mesh.outputs["Mesh"]

    def _build_profile_curve(self, points: list[tuple[float, float]], x: float, y: float):
        if len(points) < 3:
            raise BlenderConversionError("A profile curve requires at least three points")

        points_node = self.group.nodes.new("GeometryNodePoints")
        points_node.location = (x, y)
        points_node.inputs["Count"].default_value = len(points)
        points_node.inputs["Radius"].default_value = 0.001

        index_node = self.group.nodes.new("GeometryNodeInputIndex")
        index_node.location = (x, y - 220)

        index_switch = self.group.nodes.new("GeometryNodeIndexSwitch")
        index_switch.location = (x + 220, y - 220)
        index_switch.data_type = "VECTOR"
        while len(index_switch.index_switch_items) < len(points):
            index_switch.index_switch_items.new()
        self.group.links.new(index_node.outputs["Index"], index_switch.inputs["Index"])
        for point_index, point in enumerate(points):
            index_switch.inputs[str(point_index)].default_value = (float(point[0]), float(point[1]), 0.0)

        set_position = self.group.nodes.new("GeometryNodeSetPosition")
        set_position.location = (x + 440, y)
        self.group.links.new(points_node.outputs["Points"], set_position.inputs["Geometry"])
        self.group.links.new(index_switch.outputs["Output"], set_position.inputs["Position"])

        points_to_curves = self.group.nodes.new("GeometryNodePointsToCurves")
        points_to_curves.location = (x + 660, y)
        self.group.links.new(set_position.outputs["Geometry"], points_to_curves.inputs["Points"])
        self.group.links.new(index_node.outputs["Index"], points_to_curves.inputs["Weight"])

        spline_type = self.group.nodes.new("GeometryNodeCurveSplineType")
        spline_type.location = (x + 880, y)
        spline_type.spline_type = "POLY"
        self.group.links.new(points_to_curves.outputs["Curves"], spline_type.inputs["Curve"])

        cyclic = self.group.nodes.new("GeometryNodeSetSplineCyclic")
        cyclic.location = (x + 1100, y)
        cyclic.inputs["Cyclic"].default_value = True
        self.group.links.new(spline_type.outputs["Curve"], cyclic.inputs["Curve"])
        return cyclic.outputs["Curve"]


def _ensure_generated_collection():
    collection = bpy.data.collections.get(GENERATED_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(GENERATED_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _measure_ir_bounds(node: IRNode) -> Bounds3D:
    if isinstance(node, PrimitiveNode):
        if node.kind == "cube":
            size = _vector3(node.params.get("size", node.params.get("_positional", [1.0])[0] if node.params.get("_positional") else 1.0))
            center = bool(node.params.get("center", False))
            min_corner = Vector((-size[0] / 2.0, -size[1] / 2.0, -size[2] / 2.0)) if center else Vector((0.0, 0.0, 0.0))
            max_corner = Vector((size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)) if center else Vector(size)
            return Bounds3D(min_corner, max_corner)
        if node.kind == "sphere":
            radius = _resolve_sphere_radius(node.params)
            return Bounds3D(Vector((-radius, -radius, -radius)), Vector((radius, radius, radius)))
        if node.kind == "cylinder":
            height = float(node.params.get("h", node.params.get("_positional", [1.0])[0] if node.params.get("_positional") else 1.0))
            radius_bottom = _resolve_radius(node.params, "r", "d", "r1", "d1", fallback=1.0)
            radius_top = _resolve_radius(node.params, "r", "d", "r2", "d2", fallback=radius_bottom)
            radius = max(radius_bottom, radius_top)
            if bool(node.params.get("center", False)):
                return Bounds3D(Vector((-radius, -radius, -height / 2.0)), Vector((radius, radius, height / 2.0)))
            return Bounds3D(Vector((-radius, -radius, 0.0)), Vector((radius, radius, height)))

    if isinstance(node, TransformNode):
        child_bounds = _measure_ir_bounds(node.child)
        matrix = _transform_matrix_for_node(node, child_bounds)
        return _transform_bounds(child_bounds, matrix)

    if isinstance(node, BooleanNode):
        child_bounds = [_measure_ir_bounds(child) for child in node.children]
        if not child_bounds:
            raise BlenderConversionError(f"Boolean node {node.kind}() has no children")
        if node.kind == "difference":
            return child_bounds[0]
        if node.kind == "intersection":
            min_corner = Vector((
                max(bounds.min_corner[0] for bounds in child_bounds),
                max(bounds.min_corner[1] for bounds in child_bounds),
                max(bounds.min_corner[2] for bounds in child_bounds),
            ))
            max_corner = Vector((
                min(bounds.max_corner[0] for bounds in child_bounds),
                min(bounds.max_corner[1] for bounds in child_bounds),
                min(bounds.max_corner[2] for bounds in child_bounds),
            ))
            return Bounds3D(min_corner, max_corner)
        return _merge_bounds(child_bounds)

    if isinstance(node, ExtrudeNode):
        profile = _compile_2d(node.child)
        min_x = min(point[0] for point in profile.points)
        max_x = max(point[0] for point in profile.points)
        min_y = min(point[1] for point in profile.points)
        max_y = max(point[1] for point in profile.points)
        if node.kind == "linear_extrude":
            height = float(node.params.get("height", node.params.get("_positional", [1.0])[0] if node.params.get("_positional") else 1.0))
            if bool(node.params.get("center", False)):
                return Bounds3D(Vector((min_x, min_y, -height / 2.0)), Vector((max_x, max_y, height / 2.0)))
            return Bounds3D(Vector((min_x, min_y, 0.0)), Vector((max_x, max_y, height)))
        if node.kind == "rotate_extrude":
            radius = max(max(abs(point[0]) for point in profile.points), 0.0)
            return Bounds3D(Vector((-radius, -radius, min_y)), Vector((radius, radius, max_y)))

    raise BlenderConversionError(f"Cannot measure bounds for {type(node).__name__}")


def _merge_bounds(bounds_list: list[Bounds3D]) -> Bounds3D:
    return Bounds3D(
        Vector((
            min(bounds.min_corner[0] for bounds in bounds_list),
            min(bounds.min_corner[1] for bounds in bounds_list),
            min(bounds.min_corner[2] for bounds in bounds_list),
        )),
        Vector((
            max(bounds.max_corner[0] for bounds in bounds_list),
            max(bounds.max_corner[1] for bounds in bounds_list),
            max(bounds.max_corner[2] for bounds in bounds_list),
        )),
    )


def _transform_bounds(bounds: Bounds3D, matrix: Matrix) -> Bounds3D:
    corners = [
        Vector((x, y, z, 1.0))
        for x in (bounds.min_corner[0], bounds.max_corner[0])
        for y in (bounds.min_corner[1], bounds.max_corner[1])
        for z in (bounds.min_corner[2], bounds.max_corner[2])
    ]
    transformed = [matrix @ corner for corner in corners]
    return Bounds3D(
        Vector((
            min(corner[0] for corner in transformed),
            min(corner[1] for corner in transformed),
            min(corner[2] for corner in transformed),
        )),
        Vector((
            max(corner[0] for corner in transformed),
            max(corner[1] for corner in transformed),
            max(corner[2] for corner in transformed),
        )),
    )


def _transform_matrix_for_node(node: TransformNode, child_bounds: Bounds3D) -> Matrix:
    if node.kind == "translate":
        return Matrix.Translation(Vector(_vector3(_first_argument(node.params, "v"))))
    if node.kind == "rotate":
        return _rotation_matrix(node.params)
    if node.kind == "scale":
        vector = _vector3(_first_argument(node.params, "v", default=1.0))
        return Matrix.Diagonal(Vector((vector[0], vector[1], vector[2], 1.0)))
    if node.kind == "mirror":
        scale = _mirror_scale_vector(_vector3(_first_argument(node.params, "v")))
        return Matrix.Diagonal(Vector((scale[0], scale[1], scale[2], 1.0)))
    if node.kind == "multmatrix":
        return _matrix4(_first_argument(node.params, "m"))
    if node.kind == "resize":
        target = _vector3(_first_argument(node.params, "newsize"))
        current_size = child_bounds.size
        center = child_bounds.center
        scale = Vector((
            1.0 if math.isclose(target[0], 0.0) else target[0] / current_size[0],
            1.0 if math.isclose(target[1], 0.0) else target[1] / current_size[1],
            1.0 if math.isclose(target[2], 0.0) else target[2] / current_size[2],
        ))
        return Matrix.Translation(center) @ Matrix.Diagonal(Vector((scale[0], scale[1], scale[2], 1.0))) @ Matrix.Translation(-center)
    raise BlenderConversionError(f"Unsupported transform for bounds: {node.kind}")


def _transform_components(node: TransformNode, child_bounds: Bounds3D) -> tuple[Vector, Euler, Vector]:
    if node.kind == "translate":
        return Vector(_vector3(_first_argument(node.params, "v"))), Euler((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    if node.kind == "rotate":
        matrix = _rotation_matrix(node.params)
        return _matrix_to_components(matrix)
    if node.kind == "scale":
        scale = _vector3(_first_argument(node.params, "v", default=1.0))
        return Vector((0.0, 0.0, 0.0)), Euler((0.0, 0.0, 0.0)), Vector(scale)
    if node.kind == "mirror":
        scale = _mirror_scale_vector(_vector3(_first_argument(node.params, "v")))
        return Vector((0.0, 0.0, 0.0)), Euler((0.0, 0.0, 0.0)), Vector(scale)
    if node.kind == "multmatrix":
        return _matrix_to_components(_matrix4(_first_argument(node.params, "m")))
    if node.kind == "resize":
        target = _vector3(_first_argument(node.params, "newsize"))
        current_size = child_bounds.size
        center = child_bounds.center
        scale = Vector((
            _resize_scale_component(target[0], current_size[0]),
            _resize_scale_component(target[1], current_size[1]),
            _resize_scale_component(target[2], current_size[2]),
        ))
        translation = Vector((
            center[0] - scale[0] * center[0],
            center[1] - scale[1] * center[1],
            center[2] - scale[2] * center[2],
        ))
        return translation, Euler((0.0, 0.0, 0.0)), scale
    raise BlenderConversionError(f"Unsupported transform for Geometry Nodes: {node.kind}")


def _transform_flips_faces(node: TransformNode, child_bounds: Bounds3D) -> bool:
    matrix = _transform_matrix_for_node(node, child_bounds)
    determinant = matrix.to_3x3().determinant()
    return determinant < 0.0


def _matrix_to_components(matrix: Matrix) -> tuple[Vector, Euler, Vector]:
    location, rotation, scale = matrix.decompose()
    return Vector(location), rotation.to_euler("XYZ"), Vector(scale)


def _resize_scale_component(target: float, source: float) -> float:
    if math.isclose(target, 0.0):
        return 1.0
    if math.isclose(source, 0.0):
        raise BlenderConversionError("resize() cannot resize a zero-size dimension")
    return target / source


def _mirror_scale_vector(normal_value: tuple[float, float, float]) -> tuple[float, float, float]:
    vector = Vector(normal_value)
    if math.isclose(vector.length, 0.0):
        raise BlenderConversionError("mirror() requires a non-zero normal")
    normalized = Vector((round(component / vector.length, 6) for component in normal_value))
    axis_candidates = {
        (1.0, 0.0, 0.0): (-1.0, 1.0, 1.0),
        (-1.0, 0.0, 0.0): (-1.0, 1.0, 1.0),
        (0.0, 1.0, 0.0): (1.0, -1.0, 1.0),
        (0.0, -1.0, 0.0): (1.0, -1.0, 1.0),
        (0.0, 0.0, 1.0): (1.0, 1.0, -1.0),
        (0.0, 0.0, -1.0): (1.0, 1.0, -1.0),
    }
    for axis, scale in axis_candidates.items():
        if all(math.isclose(normalized[index], axis[index], abs_tol=1e-6) for index in range(3)):
            return scale
    raise BlenderConversionError("mirror() in the Blender 5.1 GN path currently supports only axis-aligned normals")


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


def _resolve_sphere_radius(params: dict) -> float:
    positional = params.get("_positional", [])
    radius = params.get("r")
    if radius is None and "d" in params:
        radius = float(params["d"]) / 2.0
    if radius is None and positional:
        radius = positional[0]
    if radius is None:
        radius = 1.0
    return float(radius)


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
