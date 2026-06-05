# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

# For avoidance of doubts, Hunyuan 3D means the large language models and
# their software and algorithms, including trained model weights, parameters (including
# optimizer states), machine-learning model code, inference-enabling code, training-enabling code,
# fine-tuning enabling code and other elements of the foregoing made publicly available
# by Tencent in accordance with TENCENT HUNYUAN COMMUNITY LICENSE AGREEMENT.

"""Pin/hole connector generator for 3D-printable part assembly.

Generates cylindrical pin (male) and hole (female) geometry at the contact
surfaces between adjacent parts using trimesh CSG boolean operations.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

import gc

from .config import ConnectorConfig
from .cutter import PartInfo
from .memory import log_memory_usage, free_gpu_memory, warn_if_large_mesh

logger = logging.getLogger(__name__)


class PinHoleGenerator:
    """Generate pin/hole connectors between adjacent parts.

    Parameters
    ----------
    config : ConnectorConfig
        Pin and hole dimensional parameters.
    """

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    # ==================================================================
    # Adjacency detection
    # ==================================================================

    def find_adjacent_pairs(
        self, parts: List[PartInfo]
    ) -> List[Tuple[int, int, float]]:
        """Find part pairs whose bounding boxes are close enough for
        connectors.

        Parts are considered adjacent when the minimum distance between
        their bounding boxes is <= ``pin_depth * 2``.

        Returns
        -------
        list[tuple[int, int, float]]
            ``(idx_a, idx_b, min_distance)`` for each adjacent pair.
        """
        pairs: List[Tuple[int, int, float]] = []
        n = len(parts)
        threshold = self.config.pin_depth * 2.0

        for i in range(n):
            for j in range(i + 1, n):
                dist = self._bbox_min_distance(
                    parts[i].bbox_min, parts[i].bbox_max,
                    parts[j].bbox_min, parts[j].bbox_max,
                )
                if dist <= threshold:
                    pairs.append((i, j, dist))

        logger.info("Found %d adjacent part pair(s)", len(pairs))
        return pairs

    @staticmethod
    def _bbox_min_distance(
        min_a: np.ndarray, max_a: np.ndarray,
        min_b: np.ndarray, max_b: np.ndarray,
    ) -> float:
        """Minimum distance between two axis-aligned bounding boxes.

        Returns 0 when the boxes overlap or touch.
        """
        dx = max(0.0, float(min_b[0] - max_a[0]),
                      float(min_a[0] - max_b[0]))
        dy = max(0.0, float(min_b[1] - max_a[1]),
                      float(min_a[1] - max_b[1]))
        dz = max(0.0, float(min_b[2] - max_a[2]),
                      float(min_a[2] - max_b[2]))
        return float(np.sqrt(dx * dx + dy * dy + dz * dz))

    # ==================================================================
    # Contact face detection
    # ==================================================================

    def find_contact_face(
        self, mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Find the contact region between two meshes.

        Uses `trimesh.proximity.closest_point` to locate the nearest
        vertex pair, then collects all vertices on *mesh_a* within
        ``pin_depth * 1.5`` of that closest point.

        Returns
        -------
        center : (3,) np.ndarray
            Midpoint between the two closest points.
        normal : (3,) np.ndarray
            Unit vector from mesh A toward mesh B.
        face_verts : (N, 3) np.ndarray
            Vertices of mesh A near the contact region.
        """
        # Closest-point query: find closest vertex pair between meshes
        pts_on_a, dists, _ = trimesh.proximity.closest_point(
            mesh_a, mesh_b.vertices
        )
        min_idx = np.argmin(dists)
        closest_a = np.asarray(pts_on_a[min_idx], dtype=np.float64)
        closest_b = np.asarray(mesh_b.vertices[min_idx], dtype=np.float64)

        # Direction from A -> B
        direction = closest_b - closest_a
        norm_dir = float(np.linalg.norm(direction))
        if norm_dir < 1e-6:
            # Meshes intersect -- use a small Z offset as fallback
            direction = np.array([0.0, 0.0, 0.001], dtype=np.float64)
            norm_dir = float(np.linalg.norm(direction))
        normal = direction / norm_dir

        # Center = midpoint
        center = (closest_a + closest_b) / 2.0

        # Collect vertices on A near the contact point
        verts_a = np.asarray(mesh_a.vertices, dtype=np.float64)
        dists = np.linalg.norm(verts_a - closest_a, axis=1)
        radius = self.config.pin_depth * 1.5
        mask = dists < radius
        face_verts = verts_a[mask]

        if len(face_verts) < 3:
            # Degenerate -- return just the closest point
            face_verts = closest_a.reshape(1, 3)

        return center, normal, face_verts

    # ==================================================================
    # Pin placement
    # ==================================================================

    def place_pins(
        self, face_vertices: np.ndarray, normal: np.ndarray
    ) -> List[np.ndarray]:
        """Compute pin positions on a contact face.

        Projects face vertices onto a plane perpendicular to *normal*,
        builds a bounding rectangle (shrunk by ``min_edge_distance``),
        then places pins on a grid with spacing >= ``min_spacing``.

        Parameters
        ----------
        face_vertices : (N, 3) np.ndarray
            Vertices defining the contact face.
        normal : (3,) np.ndarray
            Unit surface normal (pin extrusion direction).

        Returns
        -------
        list[np.ndarray]
            World-space (x, y, z) positions for each pin base.
        """
        face_vertices = np.asarray(face_vertices, dtype=np.float64)
        normal = np.asarray(normal, dtype=np.float64)
        normal = normal / (np.linalg.norm(normal) + 1e-10)

        # --- Build local 2D coordinate system ---
        if abs(normal[0]) < 0.9:
            u = np.cross(normal, np.array([1.0, 0.0, 0.0]))
        else:
            u = np.cross(normal, np.array([0.0, 1.0, 0.0]))
        u = u / (np.linalg.norm(u) + 1e-10)
        v = np.cross(normal, u)

        # --- Project vertices to 2D ---
        centroid_3d = face_vertices.mean(axis=0)
        proj_2d = np.array([
            [float(np.dot(p - centroid_3d, u)),
             float(np.dot(p - centroid_3d, v))]
            for p in face_vertices
        ])

        min_uv = proj_2d.min(axis=0)
        max_uv = proj_2d.max(axis=0)

        # Shrink by edge margin
        shrink = self.config.min_edge_distance
        min_uv += shrink
        max_uv -= shrink

        if (max_uv <= min_uv).any():
            # Region too small -- return centroid
            logger.info(
                "Contact region too small for edge margin; "
                "placing single pin at centroid"
            )
            return [centroid_3d]

        # --- Grid placement with min_spacing enforcement ---
        n_pins = self.config.min_pins_per_face
        width = float(max_uv[0] - min_uv[0])
        height = float(max_uv[1] - min_uv[1])

        if width <= 0 or height <= 0:
            return [centroid_3d]

        min_spacing = self.config.min_spacing

        # Find a grid (nx, ny) that respects min_spacing
        grid_ok = False
        for nx in range(1, n_pins + 1):
            ny = max(1, int(np.ceil(n_pins / nx)))
            if width / nx >= min_spacing and height / ny >= min_spacing:
                n_x, n_y = nx, ny
                grid_ok = True
                break

        if not grid_ok:
            logger.info(
                "Contact region too small for %d pins with min_spacing %.1f; "
                "placing single pin at centroid",
                n_pins, min_spacing,
            )
            return [centroid_3d]

        positions: List[np.ndarray] = []
        for ix in range(n_x):
            for iy in range(n_y):
                if len(positions) >= n_pins:
                    break
                uu = min_uv[0] + (ix + 0.5) * width / n_x
                vv = min_uv[1] + (iy + 0.5) * height / n_y
                pos_3d = centroid_3d + uu * u + vv * v
                positions.append(pos_3d)

        return positions

    # ==================================================================
    # Pin / hole mesh factories
    # ==================================================================

    def create_pin_mesh(
        self, position: np.ndarray, direction: np.ndarray
    ) -> trimesh.Trimesh:
        """Create a cylinder mesh representing a pin.

        The cylinder's bottom face is centered at *position* and extends
        along *direction* by ``pin_depth``.

        Parameters
        ----------
        position : (3,) np.ndarray
            Center of the pin base (on the part surface).
        direction : (3,) np.ndarray
            Unit vector pointing from base to tip.

        Returns
        -------
        trimesh.Trimesh
        """
        direction = np.asarray(direction, dtype=np.float64)
        direction = direction / (np.linalg.norm(direction) + 1e-10)

        pin = trimesh.creation.cylinder(
            radius=self.config.pin_diameter / 2.0,
            height=self.config.pin_depth,
            sections=16,
        )

        # trimesh cylinder is centred at origin, Z-up.
        # Step 1: translate so bottom is at origin
        pin.apply_translation([0, 0, self.config.pin_depth / 2.0])

        # Step 2: rotate Z -> direction
        rot = self._rotation_from_to(
            np.array([0.0, 0.0, 1.0]), direction
        )
        pin.apply_transform(rot)

        # Step 3: translate to target position
        pin.apply_translation(position)

        return pin

    def create_hole_mesh(
        self, position: np.ndarray, direction: np.ndarray
    ) -> trimesh.Trimesh:
        """Create a cylinder mesh for hole subtraction.

        The cylinder is slightly oversized (tolerance) and deeper than
        the pin for bottom clearance.  Its top face sits at *position*.

        Parameters
        ----------
        position : (3,) np.ndarray
            Center of the hole opening (on the part surface).
        direction : (3,) np.ndarray
            Unit vector pointing *into* the part (opposite to pin).

        Returns
        -------
        trimesh.Trimesh
        """
        direction = np.asarray(direction, dtype=np.float64)
        direction = direction / (np.linalg.norm(direction) + 1e-10)

        hole = trimesh.creation.cylinder(
            radius=self.config.hole_radius,
            height=self.config.hole_depth,
            sections=16,
        )

        # Translate so top is at origin (Z = -height/2 puts top at z=0)
        hole.apply_translation([0, 0, -self.config.hole_depth / 2.0])

        # Rotate Z -> direction
        rot = self._rotation_from_to(
            np.array([0.0, 0.0, 1.0]), direction
        )
        hole.apply_transform(rot)

        # Translate to target position
        hole.apply_translation(position)

        return hole

    @staticmethod
    def _rotation_from_to(
        src: np.ndarray, dst: np.ndarray
    ) -> np.ndarray:
        """Return a 4x4 homogeneous rotation matrix mapping *src* -> *dst*.

        Uses Rodrigues' rotation formula.  Handles identity and 180 deg
        cases explicitly.
        """
        src = np.asarray(src, dtype=np.float64)
        dst = np.asarray(dst, dtype=np.float64)
        src = src / (np.linalg.norm(src) + 1e-10)
        dst = dst / (np.linalg.norm(dst) + 1e-10)

        if np.allclose(src, dst, atol=1e-8):
            return np.eye(4)

        if np.allclose(src, -dst, atol=1e-8):
            # 180 deg rotation about an arbitrary perpendicular axis
            if abs(src[0]) < 0.9:
                axis = np.cross(src, np.array([1.0, 0.0, 0.0]))
            else:
                axis = np.cross(src, np.array([0.0, 1.0, 0.0]))
            axis = axis / (np.linalg.norm(axis) + 1e-10)
            r = Rotation.from_rotvec(np.pi * axis)
            mat = np.eye(4)
            mat[:3, :3] = r.as_matrix()
            return mat

        # Rodrigues' rotation formula
        v = np.cross(src, dst)
        c = float(np.dot(src, dst))
        vx = np.array([
            [0.0, -v[2], v[1]],
            [v[2], 0.0, -v[0]],
            [-v[1], v[0], 0.0],
        ], dtype=np.float64)
        R = np.eye(3) + vx + (vx @ vx) / (1.0 + c)

        mat = np.eye(4)
        mat[:3, :3] = R
        return mat

    # ==================================================================
    # Main entry point
    # ==================================================================

    def generate(
        self, parts: List[PartInfo]
    ) -> List[PartInfo]:
        """Generate pin/hole connectors for all adjacent part pairs.

        Workflow per adjacent pair (A, B):
        1. Find contact face on A.
        2. Place pin positions.
        3. For each position: CSG-union a pin cylinder onto A,
           CSG-difference a hole cylinder from B.
        4. On boolean failure: keep original mesh + log warning.

        Parameters
        ----------
        parts : list[PartInfo]
            Input parts (meshes are NOT mutated -- copies are made).

        Returns
        -------
        list[PartInfo]
            Parts with connectors applied (or originals on failure).
        """
        # ---- Enter memory snapshot ----
        log_memory_usage(logger, "connectors/enter")

        # Deep-copy parts so we don't mutate the caller's data
        result: List[PartInfo] = []
        for p in parts:
            result.append(PartInfo(
                mesh=p.mesh.copy(),
                name=p.name,
                bbox_min=p.bbox_min.copy(),
                bbox_max=p.bbox_max.copy(),
                bbox_size=p.bbox_size.copy(),
                fits_bed=p.fits_bed,
            ))

        pairs = self.find_adjacent_pairs(parts)
        if not pairs:
            logger.info(
                "No adjacent pairs -- skipping connector generation"
            )
            return result

        for i, j, _dist in pairs:
            part_a = result[i]
            part_b = result[j]

            try:
                center, normal, face_verts = self.find_contact_face(
                    part_a.mesh, part_b.mesh
                )

                # Log vertex/face counts
                logger.info(
                    "Processing pair '%s' (%d verts, %d faces) <-> "
                    "'%s' (%d verts, %d faces)",
                    part_a.name,
                    len(part_a.mesh.vertices), len(part_a.mesh.faces),
                    part_b.name,
                    len(part_b.mesh.vertices), len(part_b.mesh.faces),
                )

                pin_positions = self.place_pins(face_verts, normal)

                for pos in pin_positions:
                    # --- Pin on part A ---
                    pin = self.create_pin_mesh(pos, normal)
                    try:
                        # Warn and GC before boolean on large meshes
                        large_a = warn_if_large_mesh(
                            part_a.mesh, logger, part_a.name
                        )
                        if (
                            len(part_a.mesh.vertices) > 50000
                            or large_a
                        ):
                            gc.collect()

                        part_a.mesh = trimesh.boolean.union(
                            [part_a.mesh, pin]
                        )
                        part_a.bbox_min = np.asarray(
                            part_a.mesh.bounds[0], dtype=np.float64
                        )
                        part_a.bbox_max = np.asarray(
                            part_a.mesh.bounds[1], dtype=np.float64
                        )
                        part_a.bbox_size = part_a.bbox_max - part_a.bbox_min
                    except MemoryError as exc:
                        logger.warning(
                            "Out of memory during boolean union (pin) on "
                            "'%s': %s. Keeping original mesh.",
                            part_a.name, exc, exc_info=True,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Boolean union (pin) failed on '%s': %s. "
                            "Keeping original mesh.",
                            part_a.name, exc, exc_info=True,
                        )

                    # --- Hole on part B ---
                    # Hole starts at the pin tip position on B's surface
                    hole_pos = pos + normal * self.config.pin_depth
                    hole = self.create_hole_mesh(
                        hole_pos, -normal  # points INTO part B
                    )
                    try:
                        # Warn and GC before boolean on large meshes
                        large_b = warn_if_large_mesh(
                            part_b.mesh, logger, part_b.name
                        )
                        if (
                            len(part_b.mesh.vertices) > 50000
                            or large_b
                        ):
                            gc.collect()

                        part_b.mesh = trimesh.boolean.difference(
                            [part_b.mesh, hole]
                        )
                        part_b.bbox_min = np.asarray(
                            part_b.mesh.bounds[0], dtype=np.float64
                        )
                        part_b.bbox_max = np.asarray(
                            part_b.mesh.bounds[1], dtype=np.float64
                        )
                        part_b.bbox_size = part_b.bbox_max - part_b.bbox_min
                    except MemoryError as exc:
                        logger.warning(
                            "Out of memory during boolean difference "
                            "(hole) on '%s': %s. Keeping original mesh.",
                            part_b.name, exc, exc_info=True,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Boolean difference (hole) failed on "
                            "'%s': %s. Keeping original mesh.",
                            part_b.name, exc, exc_info=True,
                        )

                logger.info(
                    "Generated %d pin/hole(s) between '%s' and '%s'",
                    len(pin_positions), part_a.name, part_b.name,
                )

            except MemoryError as exc:
                logger.warning(
                    "Out of memory generating connectors between '%s' and "
                    "'%s': %s",
                    part_a.name, part_b.name, exc, exc_info=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to generate connectors between '%s' and "
                    "'%s': %s",
                    part_a.name, part_b.name, exc, exc_info=True,
                )

        # ---- Exit memory snapshot ----
        log_memory_usage(logger, "connectors/exit")
        return result
