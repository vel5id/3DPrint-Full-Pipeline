"""Tests for the hy3dgen.slicer module."""

import sys
from pathlib import Path

# Ensure hy3dgen is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pytest
import trimesh

from hy3dgen.slicer.config import (
    ConnectorConfig,
    PrinterProfile,
    QIDI_Q2_PROFILE,
    ENDER3_PROFILE,
    PRUSA_MK4_PROFILE,
    BUILTIN_PROFILES,
    load_profile,
)


class TestConnectorConfig:
    def test_defaults(self):
        cfg = ConnectorConfig()
        assert cfg.pin_diameter == 4.5
        assert cfg.pin_depth == 9.0
        assert cfg.pin_tolerance == 0.2
        assert cfg.min_edge_distance == 5.0
        assert cfg.min_pins_per_face == 2

    def test_custom_values(self):
        cfg = ConnectorConfig(
            pin_diameter=3.0,
            pin_depth=6.0,
            pin_tolerance=0.15,
        )
        assert cfg.pin_diameter == 3.0
        assert cfg.pin_depth == 6.0
        assert cfg.pin_tolerance == 0.15

    def test_is_frozen(self):
        cfg = ConnectorConfig()
        with pytest.raises(Exception):
            cfg.pin_diameter = 10.0

    def test_computed_properties(self):
        cfg = ConnectorConfig(
            pin_diameter=4.5,
            pin_depth=9.0,
            pin_tolerance=0.2,
        )
        # min_spacing = 3.0 * pin_diameter
        assert cfg.min_spacing == 13.5
        # hole_radius = pin_diameter / 2 + tolerance
        assert cfg.hole_radius == 2.45
        # hole_depth = pin_depth + 1.0
        assert cfg.hole_depth == 10.0

    def test_computed_properties_custom(self):
        cfg = ConnectorConfig(
            pin_diameter=3.0,
            pin_depth=5.0,
            pin_tolerance=0.1,
        )
        assert cfg.min_spacing == 9.0
        assert cfg.hole_radius == 1.6
        assert cfg.hole_depth == 6.0


class TestPrinterProfile:
    def test_qidi_q2_profile(self):
        p = QIDI_Q2_PROFILE
        assert p.name == "Qidi Q2"
        assert p.bed_size == (270, 270, 256)
        assert p.margin == 5.0
        assert p.usable_bed == (260, 260, 246)
        assert p.connector.pin_diameter == 4.5

    def test_ender3_profile(self):
        p = ENDER3_PROFILE
        assert p.bed_size == (220, 220, 250)
        assert p.usable_bed == (210, 210, 240)

    def test_prusa_mk4_profile(self):
        p = PRUSA_MK4_PROFILE
        assert p.usable_bed == (244, 204, 214)

    def test_part_fits(self):
        p = QIDI_Q2_PROFILE
        # Part that fits: 100x100x100 < 260x260x246
        assert p.part_fits((100, 100, 100)) is True
        # Part that exceeds Z
        assert p.part_fits((100, 100, 300)) is False
        # Part that exceeds X
        assert p.part_fits((300, 100, 100)) is False
        # Part exactly at limit
        assert p.part_fits((260, 260, 246)) is True

    def test_is_frozen(self):
        p = QIDI_Q2_PROFILE
        with pytest.raises(Exception):
            p.bed_size = (300, 300, 300)


class TestLoadProfile:
    def test_load_qidi_q2_by_name(self):
        p = load_profile("qidi_q2")
        assert p.name == "Qidi Q2"
        assert p.bed_size == (270, 270, 256)

    def test_load_ender3_by_name(self):
        p = load_profile("ender3")
        assert p.bed_size == (220, 220, 250)

    def test_load_case_insensitive(self):
        p = load_profile("QIDI_Q2")
        assert p.bed_size == (270, 270, 256)

    def test_load_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            load_profile("nonexistent_printer_v999")

    def test_load_hyphen_normalized(self):
        p = load_profile("qidi-q2")
        assert p.name == "Qidi Q2"
        assert p.bed_size == (270, 270, 256)

    def test_builtin_profiles_dict(self):
        assert "qidi_q2" in BUILTIN_PROFILES
        assert "ender3" in BUILTIN_PROFILES
        assert "prusa_mk4" in BUILTIN_PROFILES
        assert len(BUILTIN_PROFILES) == 3


# -----------------------------------------------------------------------
# MeshCutter tests
# -----------------------------------------------------------------------

from hy3dgen.slicer.cutter import MeshCutter, PartInfo


class TestPartInfo:
    def test_creation(self):
        mesh = trimesh.creation.box(extents=[10, 20, 30])
        info = PartInfo(
            mesh=mesh,
            name="test_box",
            bbox_min=mesh.bounds[0],
            bbox_max=mesh.bounds[1],
            bbox_size=mesh.bounds[1] - mesh.bounds[0],
        )
        assert info.name == "test_box"
        assert info.bbox_size[0] == pytest.approx(10, abs=0.1)
        assert info.bbox_size[1] == pytest.approx(20, abs=0.1)
        assert info.bbox_size[2] == pytest.approx(30, abs=0.1)


class TestMeshCutter:
    @pytest.fixture
    def cutter(self):
        return MeshCutter(QIDI_Q2_PROFILE)

    @pytest.fixture
    def small_box(self):
        return trimesh.creation.box(extents=[100, 100, 100])

    @pytest.fixture
    def large_box(self):
        return trimesh.creation.box(extents=[300, 100, 50])

    @pytest.fixture
    def huge_box(self):
        return trimesh.creation.box(extents=[500, 500, 500])

    def test_small_part_fits(self, cutter, small_box):
        info = cutter.check_part(small_box, "small")
        assert info.fits_bed is True
        assert info.name == "small"

    def test_large_part_exceeds(self, cutter, large_box):
        info = cutter.check_part(large_box, "large")
        # 300 mm X exceeds 260 mm usable
        assert info.fits_bed is False

    def test_huge_part_exceeds(self, cutter, huge_box):
        info = cutter.check_part(huge_box, "huge")
        assert info.fits_bed is False

    def test_empty_mesh_raises(self, cutter):
        empty = trimesh.Trimesh()
        with pytest.raises(ValueError, match="empty"):
            cutter.check_part(empty, "empty")

    def test_process_scene(self, cutter, small_box):
        scene = trimesh.Scene()
        scene.add_geometry(small_box, geom_name="box_a")
        scene.add_geometry(
            trimesh.creation.box(extents=[50, 50, 50]),
            geom_name="box_b",
        )
        results = cutter.process(scene)
        assert len(results) == 2
        assert all(r.fits_bed for r in results)
        assert results[0].name == "box_a"
        assert results[1].name == "box_b"

    def test_process_none(self, cutter):
        assert cutter.process(None) == []

    def test_process_skips_non_trimesh(self, cutter, small_box):
        scene = trimesh.Scene()
        scene.add_geometry(small_box, geom_name="valid")
        # Add a Path3D which is not a Trimesh — cutter should skip it
        path = trimesh.path.creation.box_outline()
        scene.add_geometry(path, geom_name="skip_me")
        results = cutter.process(scene)
        assert len(results) == 1
        assert results[0].name == "valid"


# -----------------------------------------------------------------------
# PinHoleGenerator tests
# -----------------------------------------------------------------------

from hy3dgen.slicer.connectors import PinHoleGenerator


class TestPinHoleGenerator:
    @pytest.fixture
    def gen(self):
        return PinHoleGenerator(QIDI_Q2_PROFILE.connector)

    @pytest.fixture
    def box_a(self):
        """10x10x10 box at origin."""
        return trimesh.creation.box(extents=[10, 10, 10])

    @pytest.fixture
    def box_b(self):
        """10x10x10 box offset by 5 mm in X (close but not touching)."""
        m = trimesh.creation.box(extents=[10, 10, 10])
        m.apply_translation([15, 0, 0])  # 5 mm gap
        return m

    @pytest.fixture
    def far_box(self):
        """Box far away -- should NOT be detected as adjacent."""
        m = trimesh.creation.box(extents=[10, 10, 10])
        m.apply_translation([100, 0, 0])
        return m

    # -- adjacency detection --

    def test_bbox_min_distance_touching(self):
        """Two boxes touching should have 0 distance."""
        min_a = np.array([0, 0, 0])
        max_a = np.array([10, 10, 10])
        min_b = np.array([10, 0, 0])
        max_b = np.array([20, 10, 10])
        d = PinHoleGenerator._bbox_min_distance(min_a, max_a, min_b, max_b)
        assert d == 0.0

    def test_bbox_min_distance_separated(self):
        min_a = np.array([0, 0, 0])
        max_a = np.array([10, 10, 10])
        min_b = np.array([15, 0, 0])
        max_b = np.array([25, 10, 10])
        d = PinHoleGenerator._bbox_min_distance(min_a, max_a, min_b, max_b)
        assert d == 5.0

    def test_bbox_min_distance_overlapping(self):
        min_a = np.array([0, 0, 0])
        max_a = np.array([10, 10, 10])
        min_b = np.array([5, 0, 0])
        max_b = np.array([15, 10, 10])
        d = PinHoleGenerator._bbox_min_distance(min_a, max_a, min_b, max_b)
        assert d == 0.0

    def test_find_adjacent_pairs_nearby(self, gen, box_a, box_b):
        infos = [
            PartInfo(box_a, "A", box_a.bounds[0], box_a.bounds[1],
                     box_a.bounds[1] - box_a.bounds[0]),
            PartInfo(box_b, "B", box_b.bounds[0], box_b.bounds[1],
                     box_b.bounds[1] - box_b.bounds[0]),
        ]
        pairs = gen.find_adjacent_pairs(infos)
        assert len(pairs) == 1
        assert pairs[0][0] == 0
        assert pairs[0][1] == 1

    def test_find_adjacent_pairs_far(self, gen, box_a, far_box):
        infos = [
            PartInfo(box_a, "A", box_a.bounds[0], box_a.bounds[1],
                     box_a.bounds[1] - box_a.bounds[0]),
            PartInfo(far_box, "F", far_box.bounds[0], far_box.bounds[1],
                     far_box.bounds[1] - far_box.bounds[0]),
        ]
        pairs = gen.find_adjacent_pairs(infos)
        assert len(pairs) == 0

    def test_find_adjacent_pairs_empty(self, gen):
        assert gen.find_adjacent_pairs([]) == []

    # -- pin placement --

    def test_place_pins_on_plane(self, gen):
        """Place pins on a flat 40x40 mm face on XY plane (large enough
        for min_spacing=13.5 with 5mm edge margins)."""
        normal = np.array([0.0, 0.0, 1.0])
        face_verts = np.array([
            [-20, -20, 0],
            [20, -20, 0],
            [20, 20, 0],
            [-20, 20, 0],
        ], dtype=np.float64)

        positions = gen.place_pins(face_verts, normal)
        assert len(positions) >= 2  # at least min_pins_per_face
        # All positions should be on the z=0 plane
        for pos in positions:
            assert abs(pos[2]) < 0.01

    def test_place_pins_small_face(self, gen):
        """Very small face should still produce at least 1 pin at centroid."""
        normal = np.array([0.0, 0.0, 1.0])
        # Two points only
        face_verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        positions = gen.place_pins(face_verts, normal)
        assert len(positions) == 1

    # -- pin/hole mesh creation --

    def test_create_pin_mesh(self, gen):
        pos = np.array([0.0, 0.0, 0.0])
        direction = np.array([0.0, 0.0, 1.0])
        pin = gen.create_pin_mesh(pos, direction)
        assert isinstance(pin, trimesh.Trimesh)
        assert len(pin.vertices) > 0
        assert len(pin.faces) > 0

    def test_create_hole_mesh(self, gen):
        pos = np.array([0.0, 0.0, 0.0])
        direction = np.array([0.0, 0.0, 1.0])
        hole = gen.create_hole_mesh(pos, direction)
        assert isinstance(hole, trimesh.Trimesh)
        assert len(hole.vertices) > 0
        assert len(hole.faces) > 0

    # -- rotation helper --

    def test_rotation_from_to_identity(self):
        src = np.array([0.0, 0.0, 1.0])
        dst = np.array([0.0, 0.0, 1.0])
        mat = PinHoleGenerator._rotation_from_to(src, dst)
        assert np.allclose(mat, np.eye(4), atol=1e-6)

    def test_rotation_from_to_90_degrees(self):
        src = np.array([0.0, 0.0, 1.0])
        dst = np.array([1.0, 0.0, 0.0])
        mat = PinHoleGenerator._rotation_from_to(src, dst)
        # Applying rotation to src should give dst
        result = mat[:3, :3] @ src
        assert np.allclose(result, dst, atol=1e-6)

    def test_rotation_from_to_180_degrees(self):
        src = np.array([0.0, 0.0, 1.0])
        dst = np.array([0.0, 0.0, -1.0])
        mat = PinHoleGenerator._rotation_from_to(src, dst)
        # Applying rotation to src should give dst
        result = mat[:3, :3] @ src
        assert np.allclose(result, dst, atol=1e-6)
        # Verify src was rotated to opposite direction
        assert np.dot(src, result) == pytest.approx(-1.0, abs=1e-6)

    # -- contact face detection --

    def test_find_contact_face(self, gen):
        """Two boxes with known closest points produce expected contact face."""
        box_a = trimesh.creation.box(extents=[10, 10, 10])
        box_b = trimesh.creation.box(extents=[10, 10, 10])
        box_b.apply_translation([15, 0, 0])  # 5 mm gap
        center, normal, face_verts = gen.find_contact_face(box_a, box_b)
        # Returns tuple of 3 numpy arrays
        assert isinstance(center, np.ndarray)
        assert isinstance(normal, np.ndarray)
        assert isinstance(face_verts, np.ndarray)
        assert center.shape == (3,)
        assert normal.shape == (3,)
        assert face_verts.ndim == 2
        assert face_verts.shape[1] == 3

    # -- full generate flow --

    def test_generate_no_adjacent_parts(self, gen, box_a, far_box):
        infos = [
            PartInfo(box_a, "A", box_a.bounds[0], box_a.bounds[1],
                     box_a.bounds[1] - box_a.bounds[0]),
            PartInfo(far_box, "F", far_box.bounds[0], far_box.bounds[1],
                     far_box.bounds[1] - far_box.bounds[0]),
        ]
        result = gen.generate(infos)
        # Should return same number of parts unchanged
        assert len(result) == 2
        # Vertices should be unchanged (no connectors applied)
        assert np.allclose(result[0].mesh.vertices, box_a.vertices)
