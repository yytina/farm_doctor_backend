import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from auth import get_supabase_client


MODEL_BUCKET = os.getenv("MODEL_BUCKET", "ml-models")
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", Path(tempfile.gettempdir()) / "farm-doctor-models"))


class ModelConfigurationError(RuntimeError):
    """Raised for safe-to-display model configuration failures."""


@dataclass(frozen=True)
class ModelSpec:
    crop_code: str
    crop_name: str
    model_name: str
    model_version: str
    storage_key: str


MODEL_SPECS = {
    "01": ModelSpec(
        crop_code="01",
        crop_name="pear",
        model_name="pear_v11_0",
        model_version="11.0",
        storage_key=os.getenv("PEAR_MODEL_KEY", "pear_v11_0.pt"),
    ),
    "02": ModelSpec(
        crop_code="02",
        crop_name="apple",
        model_name="apple_v11_0",
        model_version="11.0",
        storage_key=os.getenv("APPLE_MODEL_KEY", "apple_v11_0.pt"),
    ),
}


def get_model_spec(crop_code: str) -> ModelSpec:
    try:
        return MODEL_SPECS[crop_code]
    except KeyError as exc:
        raise ModelConfigurationError(f"No model is configured for crop code {crop_code}") from exc


class ModelCache:
    """Downloads private model artifacts once and retains loaded YOLO models."""

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._lock = Lock()

    def get(self, spec: ModelSpec) -> Any:
        with self._lock:
            if spec.model_name not in self._models:
                self._models[spec.model_name] = self._load(spec)
            return self._models[spec.model_name]

    def _load(self, spec: ModelSpec) -> Any:
        model_path = MODEL_CACHE_DIR / spec.model_name / Path(spec.storage_key).name
        if not model_path.exists():
            self._download(spec, model_path)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ModelConfigurationError("The ultralytics package is not installed") from exc
        return YOLO(str(model_path))

    @staticmethod
    def _download(spec: ModelSpec, model_path: Path) -> None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = model_path.with_suffix(model_path.suffix + ".download")
        try:
            model_bytes = get_supabase_client().storage.from_(MODEL_BUCKET).download(spec.storage_key)
            temporary_path.write_bytes(model_bytes)
            temporary_path.replace(model_path)
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise ModelConfigurationError(
                f"Could not download the {spec.crop_name} analysis model"
            ) from exc


model_cache = ModelCache()
