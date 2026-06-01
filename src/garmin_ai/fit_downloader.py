"""FIT download and cache handling."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from .errors import FitDownloadError
from .garmin_client import download_original_activity


def download_or_get_cached_fit(client: Any, activity_id: str, fit_dir: Path, use_cache: bool = True) -> Path:
    """Return a cached FIT file or download and extract the original activity."""

    fit_dir.mkdir(parents=True, exist_ok=True)
    fit_path = fit_dir / f"{activity_id}.fit"
    if use_cache and fit_path.exists() and fit_path.stat().st_size > 0:
        return fit_path

    try:
        payload = download_original_activity(client, str(activity_id), fit_dir)
        fit_bytes = _extract_fit_bytes(payload)
        fit_path.write_bytes(fit_bytes)
        return fit_path
    except Exception as exc:  # noqa: BLE001
        raise FitDownloadError(f"Failed to download FIT for activity {activity_id}: {exc}") from exc


def _extract_fit_bytes(payload: bytes) -> bytes:
    """Extract FIT bytes from Garmin's original download payload."""

    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".fit"):
                    return archive.read(name)
            raise FitDownloadError("Garmin original download zip did not contain a .fit file")
    return payload
