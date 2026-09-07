# PreHydro GIS Tool 4.2 - Global QGIS Edition

This QGIS Processing plugin extends the supplied 4.1 workflow with automatic,
credential-free public-data acquisition for site and watershed projects worldwide.
It is intended for Zambia, India, Africa, and other regions—not only the United States.

## Automatic source policy

The default policy is **automatic public sources where manual inputs are missing**.
A user-supplied authoritative input always takes priority for its role.

| Role | Automatic source | Notes |
|---|---|---|
| Projected CRS | Local WGS 84 UTM zone | Select a CRS manually for wide or cross-zone projects. |
| DEM | Copernicus DEM GLO-30 Public; GLO-90 fallback | Global DSM; maximum 36 one-degree tiles per automatic run. |
| Roads and railways | OpenStreetMap through Overpass | Site-sized requests only; completeness varies. |
| Reference waterways | OpenStreetMap through Overpass | Used as a reference; derived drainage still comes from the DEM. |
| Land cover | ESA WorldCover 2021 v200, 10 m | Global categorical land-cover raster. |
| Soil reference | ISRIC SoilGrids surface sand and clay | Continuous predictions, not an HSG classification. |
| Flood hazards | Manual authoritative input required | The tool does not convert a visual WMS into analytical flood polygons or imply no hazard. |

Every source, URL, status, and local file is recorded in
`01_Source/INPUT_SOURCE_PROVENANCE.json`.

## Requirements

- QGIS 3.44 or newer
- QGIS Processing, GDAL, and GRASS providers enabled
- Internet access for automatic acquisition
- An official boundary polygon
- A writable parent output folder

No ArcGIS Pro, ArcPy, private portal, API key, GitHub account, or separate Python
installation is required.

## Install

1. Open **Plugins > Manage and Install Plugins > Install from ZIP**.
2. Select `PreHydro-GIS-Tool-QGIS-Global-4.2.zip`.
3. Enable the plugin.
4. Open **Processing > Toolbox**.
5. Expand **PreHydro GIS Tool - Global > 00 - START HERE**.
6. Run **00 - Preflight Environment Check**.

## Run automatically

1. Open **PreHydro GIS Tool 4.2 - Global QGIS**.
2. Choose an existing output parent folder and a new project name.
3. Select the complete official boundary polygon layer.
4. Keep the source policy on automatic.
5. Leave Target CRS blank to select local UTM automatically.
6. Leave DEM and optional layers blank to acquire the supported public sources.
7. Use **Same as target CRS map units** for the automatically downloaded DEM.
8. Review the drainage-area threshold; 25 acres is only a starting value.
9. Run first with a small site or watershed boundary.

For authoritative inputs, populate any override field. That input wins and its
provenance is recorded as `manual_override`. Use manual-only mode to prohibit network
acquisition.

## Safety limits

Automatic acquisition is deliberately bounded. It accepts at most 36 one-degree DEM
tiles, 16 WorldCover tiles, and a four-square-degree OpenStreetMap bounding box. Split
country/continent work into hydrologically meaningful watersheds or supply prepared
regional datasets. Do not run a continent-wide 30 m analysis as one job.

## Outputs

- repaired and dissolved official boundary
- projected/clipped/filled DEM
- flow accumulation, flow direction, basins, and derived streams
- hillshade, slope percent, and aspect
- clipped roads, railways, streams, land cover, soil references, and supplied flood layers
- potential transportation/drainage crossings
- GeoPackage and GeoTIFF HEC-RAS GIS handoff files
- source provenance, QA JSON, and final text/JSON manifests

This tool prepares GIS evidence. Hydraulic geometry, Manning's n, structures, flows,
boundary conditions, rainfall distributions, calibration, and engineering approval
remain qualified-engineer work.
