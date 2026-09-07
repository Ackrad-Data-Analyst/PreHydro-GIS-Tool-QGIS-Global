"""Build deterministic install and source ZIPs, then validate their contents."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PACKAGE_ROOT / "fully_hydro_preparation_qgis"
OUTPUT_ROOT = PACKAGE_ROOT / "dist"
INSTALL_ZIP = OUTPUT_ROOT / "PreHydro-GIS-Tool-QGIS-Global-4.2.zip"
SOURCE_ZIP = OUTPUT_ROOT / "PreHydro-GIS-Tool-QGIS-Global-4.2-Source.zip"
EXCLUDED_PARTS = {"__pycache__", ".test-temp"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def included(path: Path) -> bool:
    return not (EXCLUDED_PARTS.intersection(path.parts) or path.suffix in EXCLUDED_SUFFIXES)


def write_zip(target: Path, base: Path, files: list[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(base).as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_install_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {
            "fully_hydro_preparation_qgis/__init__.py",
            "fully_hydro_preparation_qgis/metadata.txt",
            "fully_hydro_preparation_qgis/plugin.py",
            "fully_hydro_preparation_qgis/provider.py",
            "fully_hydro_preparation_qgis/algorithms/preflight.py",
            "fully_hydro_preparation_qgis/algorithms/fully_hydro.py",
            "fully_hydro_preparation_qgis/docs/README.md",
            "fully_hydro_preparation_qgis/docs/QUICK_START.md",
        }
        missing = sorted(required - names)
        unwanted = sorted(name for name in names if "__pycache__" in name or name.endswith(".pyc"))
        roots = {name.split("/", 1)[0] for name in names}
        if missing or unwanted or roots != {"fully_hydro_preparation_qgis"}:
            raise RuntimeError(
                f"Invalid install ZIP: missing={missing}, unwanted={unwanted}, roots={sorted(roots)}"
            )
        metadata = archive.read("fully_hydro_preparation_qgis/metadata.txt").decode("utf-8")
        for item in ("qgisMinimumVersion=3.44", "hasProcessingProvider=yes", "version=4.2.0-qgis.1"):
            if item not in metadata:
                raise RuntimeError(f"Install ZIP metadata is missing: {item}")


def main() -> None:
    plugin_files = [path for path in PLUGIN_ROOT.rglob("*") if path.is_file() and included(path)]
    source_files = [path for path in PACKAGE_ROOT.rglob("*") if path.is_file() and included(path)]
    write_zip(INSTALL_ZIP, PACKAGE_ROOT, plugin_files)
    write_zip(SOURCE_ZIP, PACKAGE_ROOT.parent, source_files)
    validate_install_zip(INSTALL_ZIP)
    release = {
        "install_zip": INSTALL_ZIP.relative_to(PACKAGE_ROOT.parents[1]).as_posix(),
        "install_zip_bytes": INSTALL_ZIP.stat().st_size,
        "install_zip_sha256": sha256(INSTALL_ZIP),
        "source_zip": SOURCE_ZIP.relative_to(PACKAGE_ROOT.parents[1]).as_posix(),
        "source_zip_bytes": SOURCE_ZIP.stat().st_size,
        "source_zip_sha256": sha256(SOURCE_ZIP),
    }
    (OUTPUT_ROOT / "RELEASE_CHECKSUMS.json").write_text(
        json.dumps(release, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(release, indent=2))


if __name__ == "__main__":
    main()
