"""
Model Manager for Hunyuan3D-2 Gradio App.

Manages shape and texture model loading, switching, and VRAM lifecycle.
Provides a centralized registry of all available model families and speed variants.
"""

import gc
import torch

from hy3dgen.shapegen.utils import logger

# ---------------------------------------------------------------------------
# Shape Model Registry
# ---------------------------------------------------------------------------
# family_key -> { repo, display, is_mv, flashvdm, variants: { variant_key: { subfolder, default_steps } } }
SHAPE_MODEL_CONFIGS = {
    "hunyuan3d-2mini": {
        "repo": "tencent/Hunyuan3D-2mini",
        "display": "Hunyuan3D-2 mini (0.6B)",
        "is_mv": False,
        "flashvdm": True,
        "variants": {
            "turbo":    {"subfolder": "hunyuan3d-dit-v2-mini-turbo", "default_steps": 5,  "use_safetensors": True},
            "fast":     {"subfolder": "hunyuan3d-dit-v2-mini-fast",  "default_steps": 10, "use_safetensors": True},
            "standard": {"subfolder": "hunyuan3d-dit-v2-mini",       "default_steps": 30, "use_safetensors": True},
        },
    },
    "hunyuan3d-2": {
        "repo": "tencent/Hunyuan3D-2",
        "display": "Hunyuan3D-2 (1.1B)",
        "is_mv": False,
        "flashvdm": True,
        "variants": {
            "turbo":    {"subfolder": "hunyuan3d-dit-v2-0-turbo", "default_steps": 5,  "use_safetensors": True},
            "fast":     {"subfolder": "hunyuan3d-dit-v2-0-fast",  "default_steps": 10, "use_safetensors": True},
            "standard": {"subfolder": "hunyuan3d-dit-v2-0",       "default_steps": 30, "use_safetensors": True},
        },
    },
    "hunyuan3d-2.1": {
        "repo": "tencent/Hunyuan3D-2.1",
        "display": "Hunyuan3D-2.1 (3.0B)",
        "is_mv": False,
        "flashvdm": False,  # v2.1 is not in the enable_flashvdm VAE mapping
        "variants": {
            "standard": {
                "subfolder": "hunyuan3d-dit-v2-1",
                "default_steps": 30,
                "use_safetensors": False,  # v2.1 only has .ckpt files
            },
        },
    },
    "hunyuan3d-2mv": {
        "repo": "tencent/Hunyuan3D-2mv",
        "display": "Hunyuan3D-2 mv (1.1B)",
        "is_mv": True,
        "flashvdm": True,
        "variants": {
            "turbo":    {"subfolder": "hunyuan3d-dit-v2-mv-turbo", "default_steps": 5,  "use_safetensors": True},
            "fast":     {"subfolder": "hunyuan3d-dit-v2-mv-fast",  "default_steps": 10, "use_safetensors": True},
            "standard": {"subfolder": "hunyuan3d-dit-v2-mv",       "default_steps": 30, "use_safetensors": True},
        },
    },
    "hunyuan3d-omni": {
        "repo": "tencent/Hunyuan3D-Omni",
        "display": "Hunyuan3D-Omni (3.3B) Ctrl",
        "is_mv": False,
        "flashvdm": False,  # uses fast_decode internally instead
        "pipeline": "omni",  # special: uses Hunyuan3DOmniSiTFlowMatchingPipeline
        "variants": {
            "standard": {
                "subfolder": "",  # not used — Omni loads entire repo
                "default_steps": 50,
                "use_safetensors": False,
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Texture Model Registry
# ---------------------------------------------------------------------------
# tex_key -> { repo, subfolder, display }
TEX_MODEL_CONFIGS = {
    "paint-turbo": {
        "repo": "tencent/Hunyuan3D-2",
        "subfolder": "hunyuan3d-paint-v2-0-turbo",
        "display": "Paint v2-0 Turbo",
    },
    "paint": {
        "repo": "tencent/Hunyuan3D-2",
        "subfolder": "hunyuan3d-paint-v2-0",
        "display": "Paint v2-0 Standard",
    },
    "paintpbr-v2-1": {
        "repo": "tencent/Hunyuan3D-2.1",
        "subfolder": "hunyuan3d-paintpbr-v2-1",
        "display": "Paint PBR v2-1",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_repo_name(model_path: str) -> str:
    """Extract the last path component from a model path."""
    return model_path.rstrip("/").split("/")[-1]

# Mapping from HuggingFace repo names to family keys
_REPO_TO_FAMILY = {
    "Hunyuan3D-2":    "hunyuan3d-2",
    "Hunyuan3D-2mini": "hunyuan3d-2mini",
    "Hunyuan3D-2.1":  "hunyuan3d-2.1",
    "Hunyuan3D-2mv":  "hunyuan3d-2mv",
}

_FAMILY_TO_REPO = {v: k for k, v in _REPO_TO_FAMILY.items()}


def resolve_cli_args(model_path: str, subfolder: str):
    """
    Map CLI --model_path / --subfolder to (family_key, variant_key).

    Returns (family_key, variant_key). Falls back to ('hunyuan3d-2mini', 'turbo')
    if the combination cannot be resolved.
    """
    repo_name = _extract_repo_name(model_path)
    family = _REPO_TO_FAMILY.get(repo_name, "hunyuan3d-2mini")

    # Try direct subfolder match
    if family in SHAPE_MODEL_CONFIGS:
        for vk, vc in SHAPE_MODEL_CONFIGS[family]["variants"].items():
            if vc["subfolder"] == subfolder:
                return family, vk

    # Fallback: derive variant from subfolder name
    if "turbo" in subfolder:
        return family, "turbo"
    elif "fast" in subfolder:
        return family, "fast"
    return family, "standard"


def resolve_tex_cli_args(texgen_model_path: str) -> str:
    """
    Map CLI --texgen_model_path to a tex_key from TEX_MODEL_CONFIGS.

    Returns the best-match tex_key. Defaults to 'paint-turbo'.
    """
    repo_name = _extract_repo_name(texgen_model_path)
    # Simple logic: if it's the 2.1 repo, use PBR; otherwise paint-turbo
    if "2.1" in repo_name:
        return "paintpbr-v2-1"
    return "paint-turbo"


def get_available_variants(family_key: str) -> list:
    """Return the variant keys available for a given shape model family."""
    if family_key not in SHAPE_MODEL_CONFIGS:
        return ["standard"]
    return list(SHAPE_MODEL_CONFIGS[family_key]["variants"].keys())


# ---------------------------------------------------------------------------
# ModelManager
# ---------------------------------------------------------------------------

class ModelManager:
    """
    Manages loading, unloading, and switching of shape and texture pipelines.

    Holds the authoritative state for which model family + variant is currently
    loaded, and provides properties so the rest of the app can stay declarative.
    """

    def __init__(
        self,
        device: str = "cuda",
        cli_model_path: str = "tencent/Hunyuan3D-2mini",
        cli_subfolder: str = "hunyuan3d-dit-v2-mini-turbo",
        cli_texgen_path: str = "tencent/Hunyuan3D-2",
        enable_flashvdm_flag: bool = False,
        mc_algo: str = "mc",
        low_vram_mode: bool = False,
    ):
        self._device = device
        self._mc_algo = mc_algo
        self._enable_flashvdm_flag = enable_flashvdm_flag
        self._low_vram_mode = low_vram_mode

        # Resolve CLI args to initial keys
        init_family, init_variant = resolve_cli_args(cli_model_path, cli_subfolder)
        init_tex = resolve_tex_cli_args(cli_texgen_path)

        self._shape_family = init_family
        self._shape_variant = init_variant
        self._tex_key = init_tex

        # Pipeline slots
        self._shape_pipeline = None
        self._tex_pipeline = None
        self._has_texgen = False

        # Post-process workers (needed in gradio_app)
        self.floater_remover = None
        self.degenerate_face_remover = None
        self.face_reducer = None
        self.rmbg_worker = None
        self.t2i_worker = None

    # ------------------------------------------------------------------
    # Shape pipeline
    # ------------------------------------------------------------------

    def load_shape_model(self, family_key: str, variant_key: str):
        """
        Load (or switch to) a shape-generation model.

        On failure the previous pipeline is left intact.
        Returns a metadata dict for UI updates.
        """
        config = SHAPE_MODEL_CONFIGS[family_key]
        variant_cfg = config["variants"][variant_key]
        use_safetensors = variant_cfg.get("use_safetensors", True)
        is_omni = config.get("pipeline") == "omni"

        # Skip if already loaded
        if (self._shape_family == family_key and
                self._shape_variant == variant_key and
                self._shape_pipeline is not None):
            logger.info(f"Shape model {family_key}/{variant_key} already loaded – skipping.")
            return self._make_info_dict()

        # Keep old pipeline alive so we can restore it on failure
        old_pipeline = self._shape_pipeline
        old_family = self._shape_family
        old_variant = self._shape_variant
        self._shape_pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        repo = config["repo"]
        subfolder = variant_cfg.get("subfolder", "")
        logger.info(f"Loading shape model: {repo}/{subfolder}  ...")
        try:
            if is_omni:
                from hy3dshape.pipelines import Hunyuan3DOmniSiTFlowMatchingPipeline
                pipeline = Hunyuan3DOmniSiTFlowMatchingPipeline.from_pretrained(
                    repo,
                    device=self._device,
                )
            else:
                from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
                pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                    repo,
                    subfolder=subfolder,
                    use_safetensors=use_safetensors,
                    device=self._device,
                )
                # Auto-enable flashvdm for turbo variants when supported
                if variant_key == "turbo" and config["flashvdm"]:
                    mc = "mc" if self._device in ("cpu", "mps") else self._mc_algo
                    pipeline.enable_flashvdm(mc_algo=mc)
                # Respect explicit CLI --enable_flashvdm even for non-turbo
                if self._enable_flashvdm_flag and variant_key != "turbo" and config["flashvdm"]:
                    mc = "mc" if self._device in ("cpu", "mps") else self._mc_algo
                    pipeline.enable_flashvdm(mc_algo=mc)

            # Success — free the old pipeline
            if old_pipeline is not None:
                del old_pipeline
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            self._shape_pipeline = pipeline
            self._shape_family = family_key
            self._shape_variant = variant_key

            logger.info(f"Shape model loaded: {self.current_model_display}")
            return self._make_info_dict()

        except Exception as exc:
            logger.error(f"Failed to load {family_key}/{variant_key}: {exc}")
            # Restore previous pipeline
            self._shape_pipeline = old_pipeline
            self._shape_family = old_family
            self._shape_variant = old_variant
            logger.info(f"Restored previous model: {self.current_model_display}")
            raise RuntimeError(
                f"Failed to load {family_key}/{variant_key}. "
                f"Previous model ({old_family}/{old_variant}) has been restored. Error: {exc}"
            ) from exc

    def unload_shape_model(self):
        """Delete the shape pipeline and free GPU memory."""
        if self._shape_pipeline is not None:
            logger.info("Unloading shape model ...")
            del self._shape_pipeline
            self._shape_pipeline = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ------------------------------------------------------------------
    # Texture pipeline
    # ------------------------------------------------------------------

    def load_tex_model(self, tex_key: str):
        """
        Load (or switch to) a texture-generation pipeline.

        Requires C++ extensions (custom_rasterizer, differentiable_renderer)
        to be compiled.  If loading fails, `has_texgen` stays False.
        """
        from hy3dgen.texgen import Hunyuan3DPaintPipeline

        if tex_key not in TEX_MODEL_CONFIGS:
            logger.warning(f"Unknown texture model key: {tex_key}")
            return

        if self._tex_key == tex_key and self._tex_pipeline is not None:
            logger.info(f"Texture model {tex_key} already loaded – skipping.")
            return

        self.unload_tex_model()

        cfg = TEX_MODEL_CONFIGS[tex_key]
        logger.info(f"Loading texture model: {cfg['repo']}/{cfg['subfolder']}  ...")

        try:
            pipeline = Hunyuan3DPaintPipeline.from_pretrained(
                cfg["repo"], subfolder=cfg["subfolder"]
            )
            if self._low_vram_mode:
                pipeline.enable_model_cpu_offload()
            self._tex_pipeline = pipeline
            self._tex_key = tex_key
            self._has_texgen = True
            logger.info(f"Texture model loaded: {cfg['display']}")
        except Exception as exc:
            logger.error(f"Failed to load texture model {tex_key}: {exc}")
            self._has_texgen = False

    def unload_tex_model(self):
        """Delete the texture pipeline and free GPU memory."""
        if self._tex_pipeline is not None:
            logger.info("Unloading texture model ...")
            del self._tex_pipeline
            self._tex_pipeline = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def empty_cache(self):
        """Manually free cached CUDA memory (call after inference)."""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def shape_pipeline(self):
        return self._shape_pipeline

    @property
    def tex_pipeline(self):
        return self._tex_pipeline

    @property
    def has_texgen(self) -> bool:
        return self._has_texgen

    @property
    def shape_family(self) -> str:
        return self._shape_family

    @property
    def shape_variant(self) -> str:
        return self._shape_variant

    @property
    def tex_key(self) -> str:
        return self._tex_key

    @property
    def is_mv_mode(self) -> bool:
        return SHAPE_MODEL_CONFIGS[self._shape_family]["is_mv"]

    @property
    def is_turbo(self) -> bool:
        return self._shape_variant == "turbo"

    @property
    def is_omni(self) -> bool:
        """Returns True if the current model uses the Omni pipeline."""
        cfg = SHAPE_MODEL_CONFIGS.get(self._shape_family, {})
        return cfg.get("pipeline") == "omni"

    @property
    def default_steps(self) -> int:
        return SHAPE_MODEL_CONFIGS[self._shape_family]["variants"][self._shape_variant]["default_steps"]

    @property
    def current_model_display(self) -> str:
        """Human-readable description of the currently loaded shape model."""
        cfg = SHAPE_MODEL_CONFIGS[self._shape_family]
        return f"{cfg['display']} — {self._shape_variant.capitalize()}"

    @property
    def current_tex_display(self) -> str:
        """Human-readable description of the currently loaded texture model."""
        if not self._has_texgen:
            return "Unavailable"
        return TEX_MODEL_CONFIGS.get(self._tex_key, {}).get("display", self._tex_key)

    @property
    def device(self) -> str:
        return self._device

    @property
    def low_vram_mode(self) -> bool:
        return self._low_vram_mode

    @property
    def current_repo(self) -> str:
        return SHAPE_MODEL_CONFIGS[self._shape_family]["repo"]

    @property
    def current_subfolder(self) -> str:
        return SHAPE_MODEL_CONFIGS[self._shape_family]["variants"][self._shape_variant]["subfolder"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_info_dict(self) -> dict:
        """Build a metadata dict for UI updates after model switching."""
        cfg = SHAPE_MODEL_CONFIGS[self._shape_family]
        vc = cfg["variants"][self._shape_variant]
        return {
            "family": self._shape_family,
            "variant": self._shape_variant,
            "is_mv": cfg["is_mv"],
            "is_turbo": self._shape_variant == "turbo",
            "default_steps": vc["default_steps"],
            "model_display": self.current_model_display,
            "flashvdm": cfg["flashvdm"],
        }

    @staticmethod
    def get_available_variants(family_key: str) -> list:
        """Public static accessor."""
        return get_available_variants(family_key)

    @staticmethod
    def get_family_choices():
        """Return list of (display, key) tuples for a gradio Dropdown."""
        return [(v["display"], k) for k, v in SHAPE_MODEL_CONFIGS.items()]

    @staticmethod
    def get_tex_choices():
        """Return list of (display, key) tuples for a gradio Dropdown."""
        return [(v["display"], k) for k, v in TEX_MODEL_CONFIGS.items()]
