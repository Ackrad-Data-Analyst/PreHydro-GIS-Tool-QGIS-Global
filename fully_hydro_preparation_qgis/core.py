"""QGIS-independent project, QA, and threshold helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


FOLDERS = (
    "01_Source/Boundary",
    "01_Source/Terrain",
    "01_Source/Reference",
    "02_Processed/Boundary",
    "02_Processed/Terrain",
    "02_Processed/Drainage",
    "02_Processed/Infrastructure",
    "02_Processed/Categorical",
    "02_Processed/Flood_Hazard",
    "HEC_RAS_GIS_Export",
    "qa_qc",
)


def safe_project_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    value = re.sub(r"_+", "_", value).strip("._-")
    if not value:
        raise ValueError("Project Name must contain at least one letter or number.")
    return value[:100]


def create_workspace(parent: str | Path, project_name: str) -> dict[str, Path]:
    parent_path = Path(parent).expanduser().resolve()
    if not parent_path.is_dir():
        raise ValueError(f"Parent output folder does not exist: {parent_path}")
    name = safe_project_name(project_name)
    root = parent_path / name
    if root.exists() and any(root.iterdir()):
        raise ValueError(
            f"Project folder already exists and is not empty: {root}. "
            "Use a new project name for a clean, auditable run."
        )
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "gpkg": root / "02_Processed" / "Fully_Hydro_Preparation.gpkg",
        "hec_gpkg": root / "HEC_RAS_GIS_Export" / "HEC_RAS_GIS_Inputs.gpkg",
        "manifest": root / "FINAL_OUTPUT_MANIFEST.json",
        "manifest_text": root / "FINAL_OUTPUT_MANIFEST.txt",
        "qa": root / "qa_qc" / "RUN_QA.json",
    }


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def threshold_cells(acres: float, pixel_x: float, pixel_y: float, map_unit: str) -> int:
    if acres <= 0 or pixel_x == 0 or pixel_y == 0:
        raise ValueError("Drainage area and raster pixel dimensions must be positive.")
    unit = map_unit.lower()
    if "foot" in unit or "feet" in unit:
        square_units = acres * 43560.0
    elif "meter" in unit or "metre" in unit:
        square_units = acres * 4046.8564224
    else:
        raise ValueError(
            "Target CRS must use metres or feet. Geographic-degree CRSs are not valid "
            "for drainage-area thresholds."
        )
    return max(1, int(round(square_units / abs(pixel_x * pixel_y))))


def elevation_conversion_factor(source_z_unit: str, target_map_unit: str) -> float:
    source = source_z_unit.lower()
    target = target_map_unit.lower()
    source_is_metre = "meter" in source or "metre" in source
    target_is_metre = "meter" in target or "metre" in target
    source_is_foot = "foot" in source or "feet" in source
    target_is_foot = "foot" in target or "feet" in target
    if source_is_metre and target_is_foot:
        return 3.280839895013123
    if source_is_foot and target_is_metre:
        return 0.3048
    if (source_is_metre and target_is_metre) or (source_is_foot and target_is_foot):
        return 1.0
    raise ValueError("Elevation and target map units must each be metres or feet.")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def write_manifest(paths: dict[str, Path], payload: dict) -> None:
    write_json(paths["manifest"], payload)
    lines = [
        "FULLY HYDRO PREPARATION 4.2 - GLOBAL QGIS EDITION",
        f"Status: {payload.get('status', 'UNKNOWN')}",
        f"Completed UTC: {payload.get('completed_utc', '')}",
        f"Project root: {payload.get('project_root', '')}",
        "",
        "OUTPUTS",
    ]
    for key, value in sorted(payload.get("outputs", {}).items()):
        lines.append(f"{key}: {value}")
    lines.extend(["", "REVIEW NOTES"])
    notes = payload.get("review_notes", [])
    lines.extend(f"- {note}" for note in notes)
    paths["manifest_text"].write_text("\n".join(lines) + "\n", encoding="utf-8")
