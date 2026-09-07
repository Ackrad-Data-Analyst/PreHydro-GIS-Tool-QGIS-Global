"""Credential-free global public-data acquisition helpers.

All downloads are deterministic from a WGS 84 bounding box and are accompanied by
provenance records. These helpers intentionally avoid private portals and API keys.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


USER_AGENT = "FullyHydroPreparationQGIS/4.2 (desktop QGIS processing plugin)"
COP30_ROOT = "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com"
COP90_ROOT = "https://copernicus-dem-90m.s3.eu-central-1.amazonaws.com"
WORLDCOVER_ROOT = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SOILGRIDS_ROOT = "https://maps.isric.org/mapserv"


class AcquisitionError(RuntimeError):
    pass


@dataclass
class SourceRecord:
    role: str
    dataset: str
    provider: str
    url: str
    local_path: str
    status: str
    note: str = ""

    def to_dict(self):
        return asdict(self)


def _notify(feedback, message: str) -> None:
    if feedback is not None:
        feedback.pushInfo(message)


def download(url: str, destination: str | Path, feedback=None, timeout=180, retries=2) -> Path:
    """Download atomically with bounded retries and a descriptive user agent."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(retries + 1):
        try:
            _notify(feedback, f"Downloading {target.name} (attempt {attempt + 1}/{retries + 1})")
            with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as stream:
                while True:
                    if feedback is not None and feedback.isCanceled():
                        raise AcquisitionError("Data acquisition canceled by user.")
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    stream.write(block)
            if partial.stat().st_size == 0:
                raise AcquisitionError(f"The provider returned an empty file: {url}")
            partial.replace(target)
            return target
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                break
        except (OSError, urllib.error.URLError, TimeoutError, AcquisitionError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(2 ** attempt)
    if partial.exists():
        partial.unlink()
    raise AcquisitionError(f"Download failed for {url}: {last_error}")


def _degree_cells(minimum: float, maximum: float):
    start = math.floor(minimum)
    stop = math.ceil(maximum - 1e-10)
    return range(start, stop)


def _copernicus_name(lat: int, lon: int, resolution: int) -> str:
    northing = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
    easting = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
    return f"Copernicus_DSM_COG_{resolution}_{northing}_00_{easting}_00_DEM"


def fetch_copernicus_dem(bbox, folder: str | Path, feedback=None, max_tiles=36):
    """Fetch GLO-30 tiles with a GLO-90 fallback for unavailable 30 m tiles."""
    west, south, east, north = bbox
    cells = [(lat, lon) for lat in _degree_cells(south, north) for lon in _degree_cells(west, east)]
    if not cells or len(cells) > max_tiles:
        raise AcquisitionError(
            f"DEM request needs {len(cells)} one-degree tiles; the automatic safety limit is {max_tiles}. "
            "Use a smaller watershed/site boundary or supply a prepared DEM manually."
        )
    paths, records = [], []
    for lat, lon in cells:
        selected = None
        errors = []
        for resolution, root, dataset in (
            (10, COP30_ROOT, "Copernicus DEM GLO-30 Public (2021)"),
            (30, COP90_ROOT, "Copernicus DEM GLO-90 (2021)"),
        ):
            name = _copernicus_name(lat, lon, resolution)
            url = f"{root}/{name}/{name}.tif"
            target = Path(folder) / f"{name}.tif"
            try:
                selected = download(url, target, feedback)
                paths.append(str(selected))
                records.append(SourceRecord(
                    "dem", dataset, "Copernicus Programme / AWS Open Data",
                    url, str(selected), "downloaded",
                    "GLO-90 fallback used." if resolution == 30 else "",
                ))
                break
            except AcquisitionError as exc:
                errors.append(str(exc))
        if selected is None:
            raise AcquisitionError("No Copernicus DEM tile was available for a required cell. " + " | ".join(errors))
    return paths, records


def _worldcover_cell(value: float) -> int:
    return int(math.floor(value / 3.0) * 3)


def _worldcover_name(lat: int, lon: int) -> str:
    ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
    ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
    return f"{ns}{ew}"


def fetch_worldcover(bbox, folder: str | Path, feedback=None, max_tiles=16):
    west, south, east, north = bbox
    lat_values = range(_worldcover_cell(south), _worldcover_cell(north - 1e-10) + 1, 3)
    lon_values = range(_worldcover_cell(west), _worldcover_cell(east - 1e-10) + 1, 3)
    cells = [(lat, lon) for lat in lat_values for lon in lon_values]
    if not cells or len(cells) > max_tiles:
        raise AcquisitionError(
            f"Land-cover request needs {len(cells)} WorldCover tiles; the automatic safety limit is {max_tiles}."
        )
    paths, records = [], []
    for lat, lon in cells:
        tile = _worldcover_name(lat, lon)
        filename = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
        url = f"{WORLDCOVER_ROOT}/{filename}"
        target = download(url, Path(folder) / filename, feedback)
        paths.append(str(target))
        records.append(SourceRecord(
            "land_cover", "ESA WorldCover 2021 v200 (10 m)", "European Space Agency",
            url, str(target), "downloaded",
        ))
    return paths, records


def _overpass_geojson(elements, tag: str):
    features = []
    for element in elements:
        tags = element.get("tags", {})
        geometry = element.get("geometry") or []
        if tag not in tags or len(geometry) < 2:
            continue
        coordinates = [[point["lon"], point["lat"]] for point in geometry]
        properties = {"osm_id": element.get("id"), "source": "OpenStreetMap"}
        properties.update(tags)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": properties,
        })
    return {"type": "FeatureCollection", "features": features}


def fetch_osm_lines(bbox, folder: str | Path, feedback=None, max_square_degrees=4.0):
    west, south, east, north = bbox
    area = max(0.0, east - west) * max(0.0, north - south)
    if area > max_square_degrees:
        raise AcquisitionError(
            f"The boundary bounding box is {area:.2f} square degrees; the public Overpass safety limit "
            f"is {max_square_degrees:.2f}. Supply regional OSM/authoritative layers manually."
        )
    box = f"{south:.8f},{west:.8f},{north:.8f},{east:.8f}"
    query = (
        "[out:json][timeout:180];("
        f'way["highway"]({box});'
        f'way["railway"]({box});'
        f'way["waterway"]({box});'
        ");out tags geom;"
    )
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_URL, data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
    )
    _notify(feedback, "Requesting roads, railways, and waterways from OpenStreetMap Overpass")
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise AcquisitionError(f"OpenStreetMap Overpass request failed: {exc}") from exc
    outputs, records = {}, []
    role_by_tag = {"highway": "roads", "railway": "railroads", "waterway": "reference_streams"}
    for tag, role in role_by_tag.items():
        collection = _overpass_geojson(payload.get("elements", []), tag)
        if not collection["features"]:
            continue
        target = Path(folder) / f"osm_{role}.geojson"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(collection), encoding="utf-8")
        outputs[role] = str(target)
        records.append(SourceRecord(
            role, "OpenStreetMap current extract", "OpenStreetMap contributors / Overpass API",
            OVERPASS_URL, str(target), "downloaded",
            f"{len(collection['features'])} line features; completeness varies by region.",
        ))
    return outputs, records


def fetch_soilgrids(projected_bbox, folder: str | Path, feedback=None):
    """Fetch surface sand and clay predictions in SoilGrids' native equal-area CRS."""
    west, south, east, north = projected_bbox
    outputs, records = {}, []
    for property_name in ("sand", "clay"):
        coverage = f"{property_name}_0-5cm_mean"
        query = [
            ("map", f"/map/{property_name}.map"), ("SERVICE", "WCS"),
            ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
            ("COVERAGEID", coverage), ("FORMAT", "GEOTIFF_INT16"),
            ("SUBSET", f"X({west:.3f},{east:.3f})"),
            ("SUBSET", f"Y({south:.3f},{north:.3f})"),
            ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/152160"),
            ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/152160"),
        ]
        url = SOILGRIDS_ROOT + "?" + urllib.parse.urlencode(query)
        target = download(url, Path(folder) / f"soilgrids_{coverage}.tif", feedback, timeout=240)
        outputs[property_name] = str(target)
        records.append(SourceRecord(
            "soils", f"SoilGrids 250 m {coverage}", "ISRIC - World Soil Information",
            url, str(target), "downloaded",
            "Continuous soil-property prediction; not a hydrologic soil-group classification.",
        ))
    return outputs, records
