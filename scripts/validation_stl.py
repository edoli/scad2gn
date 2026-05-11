from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


Vector3 = tuple[float, float, float]
Triangle = tuple[Vector3, Vector3, Vector3]
DEFAULT_FAILURE_ABSOLUTE_DISTANCE_TOLERANCE = 0.1
DEFAULT_FAILURE_RELATIVE_TOLERANCE = 0.01
DEFAULT_WARNING_ABSOLUTE_DISTANCE_TOLERANCE = 0.01
DEFAULT_WARNING_RELATIVE_TOLERANCE = 0.001
DEFAULT_FAILURE_ORIENTATION_MISMATCH_RATIO_TOLERANCE = 0.0
DEFAULT_WARNING_ORIENTATION_MISMATCH_RATIO_TOLERANCE = 0.0


@dataclass(slots=True)
class MeshStats:
    triangle_count: int
    vertex_count: int
    bounding_box_min: Vector3
    bounding_box_max: Vector3
    surface_area: float
    signed_volume: float


def load_stl(path: str | Path) -> list[Triangle]:
    raw = Path(path).read_bytes()
    if _looks_like_ascii(raw):
        return _parse_ascii_stl(raw.decode("utf-8", errors="ignore"))
    return _parse_binary_stl(raw)


def compute_mesh_stats(triangles: Iterable[Triangle]) -> MeshStats:
    triangle_list = list(triangles)
    vertices = [vertex for triangle in triangle_list for vertex in triangle]
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    surface_area = sum(_triangle_area(triangle) for triangle in triangle_list)
    signed_volume = sum(_triangle_signed_volume(triangle) for triangle in triangle_list)
    unique_vertices = {
        (
            round(vertex[0], 6),
            round(vertex[1], 6),
            round(vertex[2], 6),
        )
        for vertex in vertices
    }
    return MeshStats(
        triangle_count=len(triangle_list),
        vertex_count=len(unique_vertices),
        bounding_box_min=(min(xs), min(ys), min(zs)),
        bounding_box_max=(max(xs), max(ys), max(zs)),
        surface_area=surface_area,
        signed_volume=signed_volume,
    )


def compare_stl_meshes(
    reference_path: str | Path,
    candidate_path: str | Path,
    *,
    absolute_distance_tolerance: float = DEFAULT_FAILURE_ABSOLUTE_DISTANCE_TOLERANCE,
    relative_dimension_tolerance: float = DEFAULT_FAILURE_RELATIVE_TOLERANCE,
    volume_relative_tolerance: float = DEFAULT_FAILURE_RELATIVE_TOLERANCE,
    surface_area_relative_tolerance: float = DEFAULT_FAILURE_RELATIVE_TOLERANCE,
    orientation_mismatch_ratio_tolerance: float = DEFAULT_FAILURE_ORIENTATION_MISMATCH_RATIO_TOLERANCE,
    warning_absolute_distance_tolerance: float = DEFAULT_WARNING_ABSOLUTE_DISTANCE_TOLERANCE,
    warning_relative_dimension_tolerance: float = DEFAULT_WARNING_RELATIVE_TOLERANCE,
    warning_volume_relative_tolerance: float = DEFAULT_WARNING_RELATIVE_TOLERANCE,
    warning_surface_area_relative_tolerance: float = DEFAULT_WARNING_RELATIVE_TOLERANCE,
    warning_orientation_mismatch_ratio_tolerance: float = DEFAULT_WARNING_ORIENTATION_MISMATCH_RATIO_TOLERANCE,
) -> dict:
    reference_triangles = load_stl(reference_path)
    candidate_triangles = load_stl(candidate_path)
    reference_stats = compute_mesh_stats(reference_triangles)
    candidate_stats = compute_mesh_stats(candidate_triangles)

    bbox_delta = tuple(
        abs((candidate_stats.bounding_box_max[index] - candidate_stats.bounding_box_min[index]) -
            (reference_stats.bounding_box_max[index] - reference_stats.bounding_box_min[index]))
        for index in range(3)
    )
    bbox_relative = tuple(
        delta / max(
            1e-9,
            abs(reference_stats.bounding_box_max[index] - reference_stats.bounding_box_min[index]),
        )
        for index, delta in enumerate(bbox_delta)
    )

    reference_volume = abs(reference_stats.signed_volume)
    candidate_volume = abs(candidate_stats.signed_volume)
    volume_relative_delta = abs(candidate_volume - reference_volume) / max(reference_volume, 1e-9)
    surface_area_relative_delta = abs(candidate_stats.surface_area - reference_stats.surface_area) / max(
        reference_stats.surface_area,
        1e-9,
    )

    sampled_points = _sample_points(reference_triangles) + _sample_points(candidate_triangles)
    distances = [
        max(
            _point_set_distance(point, candidate_triangles),
            _point_set_distance(point, reference_triangles),
        )
        for point in sampled_points
    ]
    max_distance = max(distances, default=0.0)
    percentile_95 = _percentile(distances, 95.0)
    normal_metrics = _normal_consistency_metrics(reference_triangles, candidate_triangles)
    orientation_metrics = _orientation_consistency_metrics(reference_triangles, candidate_triangles)

    passed = (
        max(bbox_relative) <= relative_dimension_tolerance
        and volume_relative_delta <= volume_relative_tolerance
        and surface_area_relative_delta <= surface_area_relative_tolerance
        and max_distance <= absolute_distance_tolerance
        and orientation_metrics["orientation_mismatch_ratio"] <= orientation_mismatch_ratio_tolerance
    )
    warnings = _comparison_warnings(
        max_bbox_relative=max(bbox_relative),
        volume_relative_delta=volume_relative_delta,
        surface_area_relative_delta=surface_area_relative_delta,
        max_distance=max_distance,
        distance_p95=percentile_95,
        orientation_mismatch_ratio=orientation_metrics["orientation_mismatch_ratio"],
        warning_absolute_distance_tolerance=warning_absolute_distance_tolerance,
        warning_relative_dimension_tolerance=warning_relative_dimension_tolerance,
        warning_volume_relative_tolerance=warning_volume_relative_tolerance,
        warning_surface_area_relative_tolerance=warning_surface_area_relative_tolerance,
        warning_orientation_mismatch_ratio_tolerance=warning_orientation_mismatch_ratio_tolerance,
    )

    return {
        "reference_path": str(reference_path),
        "candidate_path": str(candidate_path),
        "passed": passed,
        "warning": bool(passed and warnings),
        "warnings": warnings,
        "metrics": {
            "reference": _stats_to_dict(reference_stats),
            "candidate": _stats_to_dict(candidate_stats),
            "bbox_relative_delta": list(bbox_relative),
            "volume_relative_delta": volume_relative_delta,
            "surface_area_relative_delta": surface_area_relative_delta,
            "max_bidirectional_distance": max_distance,
            "distance_p95": percentile_95,
            **normal_metrics,
            **orientation_metrics,
        },
        "tolerances": {
            "absolute_distance_tolerance": absolute_distance_tolerance,
            "relative_dimension_tolerance": relative_dimension_tolerance,
            "volume_relative_tolerance": volume_relative_tolerance,
            "surface_area_relative_tolerance": surface_area_relative_tolerance,
            "orientation_mismatch_ratio_tolerance": orientation_mismatch_ratio_tolerance,
            "warning_absolute_distance_tolerance": warning_absolute_distance_tolerance,
            "warning_relative_dimension_tolerance": warning_relative_dimension_tolerance,
            "warning_volume_relative_tolerance": warning_volume_relative_tolerance,
            "warning_surface_area_relative_tolerance": warning_surface_area_relative_tolerance,
            "warning_orientation_mismatch_ratio_tolerance": warning_orientation_mismatch_ratio_tolerance,
        },
    }


def write_comparison_report(result: dict, json_path: str | Path, markdown_path: str | Path) -> None:
    json_output = Path(json_path)
    markdown_output = Path(markdown_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    metrics = result["metrics"]
    markdown_output.write_text(
        "\n".join(
            [
                f"# STL Comparison Report",
                "",
                f"- Result: {'PASS' if result['passed'] else 'FAIL'}",
                f"- Warning: {'YES' if result.get('warning') else 'NO'}",
                f"- Reference: `{result['reference_path']}`",
                f"- Candidate: `{result['candidate_path']}`",
                f"- Max bidirectional distance: `{metrics['max_bidirectional_distance']:.8f}`",
                f"- 95th percentile distance: `{metrics['distance_p95']:.8f}`",
                f"- Bounding-box relative delta: `{metrics['bbox_relative_delta']}`",
                f"- Volume relative delta: `{metrics['volume_relative_delta']:.8f}`",
                f"- Surface area relative delta: `{metrics['surface_area_relative_delta']:.8f}`",
                f"- Flipped normal ratio: `{metrics['flipped_normal_ratio']:.8f}`",
                f"- Orientation mismatch ratio: `{metrics['orientation_mismatch_ratio']:.8f}`",
                f"- Warnings: `{json.dumps(result.get('warnings', []), sort_keys=True)}`",
            ]
        ),
        encoding="utf-8",
    )


def _comparison_warnings(
    *,
    max_bbox_relative: float,
    volume_relative_delta: float,
    surface_area_relative_delta: float,
    max_distance: float,
    distance_p95: float,
    orientation_mismatch_ratio: float,
    warning_absolute_distance_tolerance: float,
    warning_relative_dimension_tolerance: float,
    warning_volume_relative_tolerance: float,
    warning_surface_area_relative_tolerance: float,
    warning_orientation_mismatch_ratio_tolerance: float,
) -> list[dict]:
    checks = [
        ("bbox_relative_delta", max_bbox_relative, warning_relative_dimension_tolerance),
        ("volume_relative_delta", volume_relative_delta, warning_volume_relative_tolerance),
        ("surface_area_relative_delta", surface_area_relative_delta, warning_surface_area_relative_tolerance),
        ("max_bidirectional_distance", max_distance, warning_absolute_distance_tolerance),
        ("distance_p95", distance_p95, warning_absolute_distance_tolerance),
        ("orientation_mismatch_ratio", orientation_mismatch_ratio, warning_orientation_mismatch_ratio_tolerance),
    ]
    return [
        {
            "metric": metric,
            "value": value,
            "warning_tolerance": tolerance,
        }
        for metric, value, tolerance in checks
        if value > tolerance
    ]


def _normal_consistency_metrics(reference_triangles: list[Triangle], candidate_triangles: list[Triangle]) -> dict:
    sample_points = _sample_points(candidate_triangles)
    if not sample_points:
        return {
            "normal_sample_count": 0,
            "flipped_normal_count": 0,
            "flipped_normal_ratio": 0.0,
            "normal_dot_min": 1.0,
        }

    flipped = 0
    normal_dots = []
    for point in sample_points:
        reference_triangle = _nearest_triangle(point, reference_triangles)
        candidate_triangle = _nearest_triangle(point, candidate_triangles)
        if reference_triangle is None or candidate_triangle is None:
            continue
        reference_normal = _triangle_normal(reference_triangle)
        candidate_normal = _triangle_normal(candidate_triangle)
        if _length(reference_normal) <= 1e-12 or _length(candidate_normal) <= 1e-12:
            continue
        dot = _dot(reference_normal, candidate_normal)
        normal_dots.append(dot)
        if dot < 0.0:
            flipped += 1

    sample_count = len(normal_dots)
    return {
        "normal_sample_count": sample_count,
        "flipped_normal_count": flipped,
        "flipped_normal_ratio": flipped / max(sample_count, 1),
        "normal_dot_min": min(normal_dots, default=1.0),
    }


def _orientation_consistency_metrics(reference_triangles: list[Triangle], candidate_triangles: list[Triangle]) -> dict:
    reference_components = _mesh_components(reference_triangles)
    candidate_components = _mesh_components(candidate_triangles)
    unmatched_candidates = set(range(len(candidate_components)))
    mismatches = 0
    compared = 0

    for reference in reference_components:
        if not unmatched_candidates:
            break
        candidate_index = min(
            unmatched_candidates,
            key=lambda index: _component_match_cost(reference, candidate_components[index]),
        )
        unmatched_candidates.remove(candidate_index)
        candidate = candidate_components[candidate_index]
        if abs(reference["signed_volume"]) <= 1e-9 or abs(candidate["signed_volume"]) <= 1e-9:
            continue
        compared += 1
        if reference["signed_volume"] * candidate["signed_volume"] < 0.0:
            mismatches += 1

    return {
        "orientation_component_count": compared,
        "orientation_mismatch_count": mismatches,
        "orientation_mismatch_ratio": mismatches / max(compared, 1),
    }


def _mesh_components(triangles: list[Triangle]) -> list[dict]:
    remaining = set(range(len(triangles)))
    vertex_to_triangles: dict[Vector3, list[int]] = {}
    for index, triangle in enumerate(triangles):
        for vertex in triangle:
            vertex_to_triangles.setdefault(_vertex_key(vertex), []).append(index)

    components = []
    while remaining:
        start = remaining.pop()
        stack = [start]
        indices = [start]
        while stack:
            current = stack.pop()
            for vertex in triangles[current]:
                for neighbor in vertex_to_triangles[_vertex_key(vertex)]:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
                        indices.append(neighbor)
        component_triangles = [triangles[index] for index in indices]
        components.append(_component_stats(component_triangles))
    return components


def _component_stats(triangles: list[Triangle]) -> dict:
    vertices = [vertex for triangle in triangles for vertex in triangle]
    return {
        "signed_volume": sum(_triangle_signed_volume(triangle) for triangle in triangles),
        "bbox": (
            min(vertex[0] for vertex in vertices),
            min(vertex[1] for vertex in vertices),
            min(vertex[2] for vertex in vertices),
            max(vertex[0] for vertex in vertices),
            max(vertex[1] for vertex in vertices),
            max(vertex[2] for vertex in vertices),
        ),
    }


def _component_match_cost(first: dict, second: dict) -> float:
    bbox_cost = sum(abs(first["bbox"][index] - second["bbox"][index]) for index in range(6))
    volume_cost = abs(abs(first["signed_volume"]) - abs(second["signed_volume"]))
    return bbox_cost + volume_cost


def _vertex_key(vertex: Vector3) -> Vector3:
    return (round(vertex[0], 5), round(vertex[1], 5), round(vertex[2], 5))


def _looks_like_ascii(raw: bytes) -> bool:
    prefix = raw[:80].lstrip()
    return prefix.startswith(b"solid") and b"\x00" not in raw[:512]


def _parse_ascii_stl(text: str) -> list[Triangle]:
    triangles: list[Triangle] = []
    vertices: list[Vector3] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("vertex"):
            _, x, y, z = stripped.split()
            vertices.append((float(x), float(y), float(z)))
            if len(vertices) == 3:
                triangles.append((vertices[0], vertices[1], vertices[2]))
                vertices = []
    return triangles


def _parse_binary_stl(raw: bytes) -> list[Triangle]:
    triangle_count = struct.unpack_from("<I", raw, offset=80)[0]
    triangles: list[Triangle] = []
    offset = 84
    for _ in range(triangle_count):
        offset += 12
        vertices = []
        for _ in range(3):
            x, y, z = struct.unpack_from("<fff", raw, offset)
            vertices.append((float(x), float(y), float(z)))
            offset += 12
        triangles.append((vertices[0], vertices[1], vertices[2]))
        offset += 2
    return triangles


def _triangle_area(triangle: Triangle) -> float:
    a, b, c = triangle
    ab = _sub(b, a)
    ac = _sub(c, a)
    cross = _cross(ab, ac)
    return 0.5 * _length(cross)


def _triangle_signed_volume(triangle: Triangle) -> float:
    a, b, c = triangle
    return _dot(a, _cross(b, c)) / 6.0


def _triangle_normal(triangle: Triangle) -> Vector3:
    a, b, c = triangle
    normal = _cross(_sub(b, a), _sub(c, a))
    length = _length(normal)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (normal[0] / length, normal[1] / length, normal[2] / length)


def _sample_points(triangles: list[Triangle], *, max_triangles: int = 96) -> list[Vector3]:
    points: list[Vector3] = []
    step = max(1, math.ceil(len(triangles) / max_triangles))
    for triangle in triangles[::step]:
        a, b, c = triangle
        points.extend([a, b, c, ((_sum(a, b, c)[0] / 3), (_sum(a, b, c)[1] / 3), (_sum(a, b, c)[2] / 3))])
    return points


def _point_set_distance(point: Vector3, triangles: list[Triangle]) -> float:
    return min((_point_triangle_distance(point, triangle) for triangle in triangles), default=0.0)


def _nearest_triangle(point: Vector3, triangles: list[Triangle]) -> Triangle | None:
    nearest = None
    nearest_distance = math.inf
    for triangle in triangles:
        distance = _point_triangle_distance(point, triangle)
        if distance < nearest_distance:
            nearest = triangle
            nearest_distance = distance
    return nearest


def _point_triangle_distance(point: Vector3, triangle: Triangle) -> float:
    a, b, c = triangle
    ab = _sub(b, a)
    ac = _sub(c, a)
    ap = _sub(point, a)

    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return _distance(point, a)

    bp = _sub(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return _distance(point, b)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        projection = _add(a, _scale(ab, v))
        return _distance(point, projection)

    cp = _sub(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return _distance(point, c)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        projection = _add(a, _scale(ac, w))
        return _distance(point, projection)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        projection = _add(b, _scale(_sub(c, b), w))
        return _distance(point, projection)

    denominator = 1.0 / (va + vb + vc)
    v = vb * denominator
    w = vc * denominator
    projection = _add(a, _add(_scale(ab, v), _scale(ac, w)))
    return _distance(point, projection)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return ordered[index]


def _stats_to_dict(stats: MeshStats) -> dict:
    return {
        "triangle_count": stats.triangle_count,
        "vertex_count": stats.vertex_count,
        "bounding_box_min": list(stats.bounding_box_min),
        "bounding_box_max": list(stats.bounding_box_max),
        "surface_area": stats.surface_area,
        "signed_volume": stats.signed_volume,
    }


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vector3, factor: float) -> Vector3:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a: Vector3) -> float:
    return math.sqrt(_dot(a, a))


def _distance(a: Vector3, b: Vector3) -> float:
    return _length(_sub(a, b))


def _sum(a: Vector3, b: Vector3, c: Vector3) -> Vector3:
    return (a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2])
