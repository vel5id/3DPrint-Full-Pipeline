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

"""Printer profiles and connector configuration for the slicer module."""

from dataclasses import dataclass
from pathlib import Path
import json


# ---------------------------------------------------------------------------
# ConnectorConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectorConfig:
    """Configuration for pin/hole connectors between parts."""

    pin_diameter: float = 4.5        # mm — pin cylinder diameter
    pin_depth: float = 9.0           # mm — how far the pin extends into the hole
    pin_tolerance: float = 0.2       # mm — radial clearance between pin and hole
    min_edge_distance: float = 5.0   # mm — minimum distance from part edge
    min_pins_per_face: int = 2       # — minimum number of pins on each contact face

    @property
    def min_spacing(self) -> float:
        """Minimum distance between adjacent pins (3 × pin_diameter)."""
        return 3.0 * self.pin_diameter

    @property
    def hole_radius(self) -> float:
        """Hole radius = pin radius + tolerance."""
        return (self.pin_diameter / 2.0) + self.pin_tolerance

    @property
    def hole_depth(self) -> float:
        """Hole depth = pin depth + 1 mm bottom clearance."""
        return self.pin_depth + 1.0


# ---------------------------------------------------------------------------
# PrinterProfile
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrinterProfile:
    """Immutable printer profile with bed dimensions and connector settings."""

    name: str
    bed_size: tuple   # (X, Y, Z) mm — full mechanical travel
    margin: float      # mm — edge clearance on all sides
    connector: ConnectorConfig

    @property
    def usable_bed(self) -> tuple:
        """Bed size after subtracting 2× margin from each axis."""
        return tuple(
            max(1.0, s - 2.0 * self.margin)
            for s in self.bed_size
        )

    def part_fits(self, bbox_size: tuple) -> bool:
        """Return True if a part with *bbox_size* fits within usable_bed."""
        return all(
            float(bbox_size[i]) <= float(self.usable_bed[i])
            for i in range(3)
        )


# ---------------------------------------------------------------------------
# Built-in printer profiles
# ---------------------------------------------------------------------------

QIDI_Q2_PROFILE = PrinterProfile(
    name="Qidi Q2",
    bed_size=(270, 270, 256),
    margin=5.0,
    connector=ConnectorConfig(
        pin_diameter=4.5,
        pin_depth=9.0,
        pin_tolerance=0.2,
        min_edge_distance=5.0,
        min_pins_per_face=2,
    ),
)

ENDER3_PROFILE = PrinterProfile(
    name="Ender-3 / Ender-3 Pro",
    bed_size=(220, 220, 250),
    margin=5.0,
    connector=ConnectorConfig(
        pin_diameter=4.0,
        pin_depth=8.0,
        pin_tolerance=0.2,
        min_edge_distance=5.0,
        min_pins_per_face=2,
    ),
)

PRUSA_MK4_PROFILE = PrinterProfile(
    name="Prusa MK4",
    bed_size=(250, 210, 220),
    margin=3.0,
    connector=ConnectorConfig(
        pin_diameter=4.0,
        pin_depth=8.0,
        pin_tolerance=0.15,
        min_edge_distance=4.0,
        min_pins_per_face=2,
    ),
)

BUILTIN_PROFILES = {
    "qidi_q2": QIDI_Q2_PROFILE,
    "ender3": ENDER3_PROFILE,
    "prusa_mk4": PRUSA_MK4_PROFILE,
}


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

def load_profile(name_or_path: str) -> PrinterProfile:
    """Load a printer profile by name or file path.

    Resolution order:
    1. Built-in name (case-insensitive, underscores/hyphens → identical).
    2. Exact file path.
    3. ``~/.config/hy3dgen/profiles/<name>.json``.

    Parameters
    ----------
    name_or_path : str
        Built-in profile name (e.g. ``'qidi_q2'``) or path to a JSON file.

    Returns
    -------
    PrinterProfile

    Raises
    ------
    ValueError
        If the name is not recognised and no file is found.
    """
    # --- 1. Built-in (normalised key) ---
    key = name_or_path.lower().replace(" ", "_").replace("-", "_")
    if key in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[key]

    # --- 2. Direct file path ---
    path = Path(name_or_path)
    if path.is_file():
        return _load_profile_from_file(path)

    # --- 3. User config directory ---
    user_path = (
        Path.home() / ".config" / "hy3dgen" / "profiles" / f"{key}.json"
    )
    if user_path.is_file():
        return _load_profile_from_file(user_path)

    available = ", ".join(BUILTIN_PROFILES.keys())
    raise ValueError(
        f"Unknown profile '{name_or_path}'. "
        f"Available built-in profiles: {available}. "
        f"Or provide a path to a JSON profile file."
    )


def _load_profile_from_file(path: Path) -> PrinterProfile:
    """Load a PrinterProfile from a JSON file."""
    with open(path, "r") as fh:
        data = json.load(fh)

    conn_data = data.get("connector", {})
    defaults = ConnectorConfig()
    connector = ConnectorConfig(
        pin_diameter=conn_data.get("pin_diameter", defaults.pin_diameter),
        pin_depth=conn_data.get("pin_depth", defaults.pin_depth),
        pin_tolerance=conn_data.get("pin_tolerance", defaults.pin_tolerance),
        min_edge_distance=conn_data.get("min_edge_distance", defaults.min_edge_distance),
        min_pins_per_face=conn_data.get("min_pins_per_face", defaults.min_pins_per_face),
    )

    return PrinterProfile(
        name=data.get("name", path.stem),
        bed_size=tuple(data["bed_size"]),
        margin=data.get("margin", 5.0),
        connector=connector,
    )
