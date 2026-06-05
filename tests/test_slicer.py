"""Tests for the hy3dgen.slicer module."""

import sys
from pathlib import Path

# Ensure hy3dgen is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

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
