"""Global, public-data-capable QGIS implementation of PreHydro GIS Tool."""

from __future__ import annotations

import shutil
from pathlib import Path

from qgis import processing
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputFolder,
    QgsProcessingOutputRasterLayer,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProject,
    QgsRectangle,
    QgsRasterLayer,
    QgsUnitTypes,
    QgsVectorLayer,
)

from ..core import (
    create_workspace,
    elevation_conversion_factor,
    threshold_cells,
    utc_now,
    write_json,
    write_manifest,
)
from ..acquisition import (
    AcquisitionError,
    SourceRecord,
    fetch_copernicus_dem,
    fetch_osm_lines,
    fetch_soilgrids,
    fetch_worldcover,
)


GRASS_WATERSHED_IDS = ("grass:r.watershed", "grass7:r.watershed")
GRASS_TO_VECTOR_IDS = ("grass:r.to.vect", "grass7:r.to.vect")


class FullyHydroPreparationAlgorithm(QgsProcessingAlgorithm):
    PROJECT_NAME = "PROJECT_NAME"
    OUTPUT_PARENT = "OUTPUT_PARENT"
    BOUNDARY = "BOUNDARY"
    TARGET_CRS = "TARGET_CRS"
    DEM = "DEM"
    DEM_Z_UNITS = "DEM_Z_UNITS"
    SOURCE_MODE = "SOURCE_MODE"
    ROADS = "ROADS"
    RAILROADS = "RAILROADS"
    REFERENCE_STREAMS = "REFERENCE_STREAMS"
    LAND_COVER = "LAND_COVER"
    SOILS = "SOILS"
    FEMA_100 = "FEMA_100"
    FEMA_500 = "FEMA_500"
    DRAINAGE_ACRES = "DRAINAGE_ACRES"
    MIN_SLOPE = "MIN_SLOPE"
    ADD_TO_MAP = "ADD_TO_MAP"

    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT_BOUNDARY = "OUTPUT_BOUNDARY"
    OUTPUT_DEM = "OUTPUT_DEM"
    OUTPUT_STREAMS = "OUTPUT_STREAMS"
    OUTPUT_CROSSINGS = "OUTPUT_CROSSINGS"
    OUTPUT_MANIFEST = "OUTPUT_MANIFEST"

    def name(self):
        return "fully_hydro_preparation"

    def displayName(self):
        return "PreHydro GIS Tool 4.2 - Global QGIS"

    def group(self):
        return "00 - START HERE"

    def groupId(self):
        return "start_here"

    def createInstance(self):
        return FullyHydroPreparationAlgorithm()

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return (
            "Creates a structured, auditable QGIS hydrology-preparation package. Only a polygon "
            "boundary and output location are required in automatic mode. Manual authoritative "
            "DEM, roads, rail, streams, land cover, soils, and flood-hazard layers override public "
            "sources. QGIS 3.44+, GDAL, GRASS, and internet access for automatic mode "
            "are required. This tool prepares GIS inputs; it does not create or approve "
            "a hydraulic model."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.OUTPUT_PARENT, "Existing parent folder for project outputs",
            behavior=QgsProcessingParameterFile.Folder,
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PROJECT_NAME, "Project name", defaultValue="Hydro_Project",
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BOUNDARY, "Official project boundary polygon(s)",
            types=[QgsProcessing.TypeVectorPolygon],
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.SOURCE_MODE,
            "Input source policy",
            options=[
                "Automatically fetch public global sources where manual inputs are missing",
                "Manual/authoritative inputs only (no network acquisition)",
            ],
            defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS, "Projected target CRS (optional; blank selects local WGS 84 UTM)", optional=True,
        ))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, "Authoritative/local DEM override (optional in automatic mode)", optional=True,
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.DEM_Z_UNITS,
            "DEM elevation (Z) units",
            options=["Same as target CRS map units", "Metres", "Feet"],
            defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROADS, "Roads (optional)", types=[QgsProcessing.TypeVectorLine], optional=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.RAILROADS, "Railroads (optional)", types=[QgsProcessing.TypeVectorLine], optional=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.REFERENCE_STREAMS, "Reference streams (optional)",
            types=[QgsProcessing.TypeVectorLine], optional=True,
        ))
        self.addParameter(QgsProcessingParameterRasterLayer(self.LAND_COVER, "Land-cover raster (optional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SOILS, "Authoritative hydrologic soils polygons override (optional)",
            types=[QgsProcessing.TypeVectorPolygon], optional=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FEMA_100, "Authoritative 100-year flood-hazard polygons override (optional)",
            types=[QgsProcessing.TypeVectorPolygon], optional=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FEMA_500, "Authoritative 500-year flood-hazard polygons override (optional)",
            types=[QgsProcessing.TypeVectorPolygon], optional=True,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.DRAINAGE_ACRES, "Minimum drainage area (acres; review required)",
            type=QgsProcessingParameterNumber.Double, defaultValue=25.0, minValue=0.01,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_SLOPE, "Sink-fill minimum slope (degrees; review required)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.1, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_TO_MAP, "Add final review layers to current QGIS project", defaultValue=True,
        ))

        self.addOutput(QgsProcessingOutputFolder(self.OUTPUT_FOLDER, "Project output folder"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_BOUNDARY, "Official project boundary"))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_DEM, "Filled project DEM"))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_STREAMS, "Derived stream raster"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_CROSSINGS, "Potential crossing points"))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_MANIFEST, "Final output manifest"))

    def checkParameterValues(self, parameters, context):
        ok, message = super().checkParameterValues(parameters, context)
        if not ok:
            return ok, message
        project_name = self.parameterAsString(parameters, self.PROJECT_NAME, context).strip()
        if not project_name:
            return False, "Project name is required."
        source = self.parameterAsSource(parameters, self.BOUNDARY, context)
        if source is None or source.featureCount() < 1:
            return False, "Boundary must contain at least one polygon."
        target = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        if target.isValid():
            if target.isGeographic():
                return False, "Choose a projected target CRS or leave the field blank for automatic local UTM."
            unit_name = QgsUnitTypes.toString(target.mapUnits()).lower()
            if "meter" not in unit_name and "metre" not in unit_name and "foot" not in unit_name and "feet" not in unit_name:
                return False, "Target CRS map units must be metres or feet."
        source_mode = self.parameterAsEnum(parameters, self.SOURCE_MODE, context)
        if source_mode == 1 and self.parameterAsRasterLayer(parameters, self.DEM, context) is None:
            return False, "A DEM is required when the source policy is Manual/authoritative inputs only."
        return True, ""

    @staticmethod
    def _wgs84_bbox(source, context):
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        try:
            transform = QgsCoordinateTransform(source.sourceCrs(), wgs84, context.transformContext())
            extent = transform.transformBoundingBox(source.sourceExtent())
        except Exception as exc:
            raise QgsProcessingException(f"Could not transform the boundary extent to WGS 84: {exc}") from exc
        west, south, east, north = extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise QgsProcessingException("The boundary has an invalid or antimeridian-crossing WGS 84 extent.")
        return west, south, east, north

    @staticmethod
    def _automatic_utm(bbox):
        west, south, east, north = bbox
        longitude = (west + east) / 2.0
        latitude = (south + north) / 2.0
        zone = max(1, min(60, int((longitude + 180.0) // 6.0) + 1))
        epsg = (32600 if latitude >= 0 else 32700) + zone
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")

    def _mosaic(self, inputs, output, context, feedback):
        if len(inputs) == 1:
            return inputs[0]
        return self._run("gdal:buildvirtualraster", {
            "INPUT": inputs, "RESOLUTION": 0, "SEPARATE": False,
            "PROJ_DIFFERENCE": False, "ADD_ALPHA": False,
            "ASSIGN_CRS": None, "RESAMPLING": 0,
            "SRC_NODATA": "", "EXTRA": "", "OUTPUT": str(output),
        }, context, feedback)["OUTPUT"]

    @staticmethod
    def _algorithm_id(candidates):
        registry = QgsApplication.processingRegistry()
        return next((item for item in candidates if registry.algorithmById(item) is not None), None)

    @staticmethod
    def _gpkg(path: Path, layer_name: str) -> str:
        return f"{path}|layername={layer_name}"

    def _run(self, algorithm_id, parameters, context, feedback):
        if feedback.isCanceled():
            raise QgsProcessingException("Processing canceled by user.")
        feedback.pushInfo(f"Running {algorithm_id}")
        return processing.run(algorithm_id, parameters, context=context, feedback=feedback, is_child_algorithm=True)

    def _clip_vector(self, raw_input, name, target_crs, boundary, gpkg, context, feedback):
        if raw_input in (None, ""):
            return None
        projected = self._run("native:reprojectlayer", {
            "INPUT": raw_input, "TARGET_CRS": target_crs,
            "CONVERT_CURVED_GEOMETRIES": True, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
        }, context, feedback)["OUTPUT"]
        output = self._gpkg(gpkg, name)
        self._run("native:clip", {
            "INPUT": projected, "OVERLAY": boundary, "OUTPUT": output,
        }, context, feedback)
        return output

    def _grass_watershed(self, filled_dem, cells, output_dir, context, feedback):
        algorithm_id = self._algorithm_id(GRASS_WATERSHED_IDS)
        if not algorithm_id:
            raise QgsProcessingException(
                "GRASS r.watershed is unavailable. Enable the GRASS Processing provider and rerun preflight."
            )
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        values = {}
        outputs = {
            "accumulation": str(output_dir / "flow_accumulation.tif"),
            "drainage": str(output_dir / "flow_direction.tif"),
            "basin": str(output_dir / "watershed_basins.tif"),
            "stream": str(output_dir / "derived_streams.tif"),
        }
        defaults = {"elevation": filled_dem, "threshold": int(cells), "convergence": 5, "memory": 300}
        for definition in algorithm.parameterDefinitions():
            name = definition.name()
            lower = name.lower()
            if lower in defaults:
                values[name] = defaults[lower]
            elif lower in outputs:
                values[name] = outputs[lower]
            elif lower.startswith("grass_region_cellsize"):
                values[name] = 0
            elif lower.startswith("grass_raster_format"):
                values[name] = ""
        result = self._run(algorithm_id, values, context, feedback)
        return {key: result.get(key, result.get(key.upper(), path)) for key, path in outputs.items()}

    def _stream_to_vector(self, stream_raster, output, context, feedback):
        algorithm_id = self._algorithm_id(GRASS_TO_VECTOR_IDS)
        if not algorithm_id:
            raise QgsProcessingException(
                "GRASS r.to.vect is unavailable. Enable the GRASS Processing provider and rerun preflight."
            )
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        values = {}
        for definition in algorithm.parameterDefinitions():
            name = definition.name()
            lower = name.lower()
            if lower == "input":
                values[name] = stream_raster
            elif lower == "type":
                values[name] = 1
            elif lower in {"output", "output_vector"}:
                values[name] = output
            elif lower.startswith("grass_region_cellsize"):
                values[name] = 0
            elif lower.startswith("grass_raster_format"):
                values[name] = ""
        result = self._run(algorithm_id, values, context, feedback)
        return result.get("output", result.get("OUTPUT", output))

    def processAlgorithm(self, parameters, context, feedback):
        project_name = self.parameterAsString(parameters, self.PROJECT_NAME, context).strip()
        parent = self.parameterAsFile(parameters, self.OUTPUT_PARENT, context)
        boundary_input = parameters[self.BOUNDARY]
        boundary_source = self.parameterAsSource(parameters, self.BOUNDARY, context)
        bbox_wgs84 = self._wgs84_bbox(boundary_source, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        automatic_crs = not target_crs.isValid()
        if not target_crs.isValid():
            target_crs = self._automatic_utm(bbox_wgs84)
        unit_name = QgsUnitTypes.toString(target_crs.mapUnits())

        try:
            paths = create_workspace(parent, project_name)
        except (OSError, ValueError) as exc:
            raise QgsProcessingException(str(exc)) from exc
        root, gpkg, hec_gpkg = paths["root"], paths["gpkg"], paths["hec_gpkg"]
        review_notes = [
            "Hydraulic geometry, Manning's n, structures, flows, boundary conditions, temporal distribution, calibration, and approval remain engineer work.",
            "This QGIS edition is local-first and does not use private ArcGIS organization services or credentials.",
        ]
        if bbox_wgs84[2] - bbox_wgs84[0] > 6.0:
            review_notes.append(
                "The boundary spans more than six degrees of longitude. Automatic UTM may not be suitable; "
                "review the target CRS or split the work into watershed/regional projects."
            )
        source_records = []
        source_records.append({
            "role": "target_crs", "dataset": target_crs.authid() or target_crs.toProj(),
            "provider": "Automatic WGS 84 UTM selection" if automatic_crs else "User selection",
            "url": "", "local_path": "", "status": "automatic" if automatic_crs else "manual_override",
            "note": "Review for wide, cross-zone, polar, or antimeridian projects.",
        })
        outputs = {}
        feedback.setProgress(2)
        feedback.pushInfo("Workflow 1/8: creating the project workspace.")

        feedback.pushInfo("Workflow 2/8: repairing, dissolving, and projecting the official boundary.")
        fixed = self._run("native:fixgeometries", {
            "INPUT": boundary_input, "METHOD": 1, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
        }, context, feedback)["OUTPUT"]
        dissolved = self._run("native:dissolve", {
            "INPUT": fixed, "FIELD": [], "SEPARATE_DISJOINT": False,
            "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
        }, context, feedback)["OUTPUT"]
        boundary = self._gpkg(gpkg, "official_project_boundary")
        self._run("native:reprojectlayer", {
            "INPUT": dissolved, "TARGET_CRS": target_crs,
            "CONVERT_CURVED_GEOMETRIES": True, "OUTPUT": boundary,
        }, context, feedback)
        outputs["official_project_boundary"] = boundary
        self._run("native:savefeatures", {
            "INPUT": boundary, "OUTPUT": self._gpkg(hec_gpkg, "Official_Project_Boundary"),
        }, context, feedback)
        feedback.setProgress(15)

        feedback.pushInfo("Automatic acquisition: resolving missing public inputs with manual layers taking priority.")
        automatic = self.parameterAsEnum(parameters, self.SOURCE_MODE, context) == 0
        dem = self.parameterAsRasterLayer(parameters, self.DEM, context)
        automatic_dem = False
        raw_inputs = {
            self.ROADS: parameters.get(self.ROADS),
            self.RAILROADS: parameters.get(self.RAILROADS),
            self.REFERENCE_STREAMS: parameters.get(self.REFERENCE_STREAMS),
            self.SOILS: parameters.get(self.SOILS),
            self.FEMA_100: parameters.get(self.FEMA_100),
            self.FEMA_500: parameters.get(self.FEMA_500),
        }
        land_cover = self.parameterAsRasterLayer(parameters, self.LAND_COVER, context)
        if dem is not None:
            source_records.append(SourceRecord(
                "dem", "User-supplied authoritative/local DEM", "User input",
                dem.source(), dem.source(), "manual_override",
            ).to_dict())
        elif automatic:
            try:
                dem_tiles, records = fetch_copernicus_dem(
                    bbox_wgs84, root / "01_Source" / "Terrain", feedback,
                )
                source_records.extend(record.to_dict() for record in records)
                dem = self._mosaic(
                    dem_tiles, root / "01_Source" / "Terrain" / "copernicus_dem_mosaic.vrt",
                    context, feedback,
                )
                automatic_dem = True
            except AcquisitionError as exc:
                raise QgsProcessingException(
                    f"Automatic DEM acquisition failed: {exc} Supply a local DEM and rerun."
                ) from exc
        else:
            raise QgsProcessingException("No DEM was supplied and automatic public acquisition is disabled.")

        z_unit_choice = self.parameterAsEnum(parameters, self.DEM_Z_UNITS, context)
        if automatic_dem:
            z_unit_name = "metres"
        else:
            z_unit_name = unit_name if z_unit_choice == 0 else ("metres" if z_unit_choice == 1 else "feet")
        z_factor = elevation_conversion_factor(z_unit_name, unit_name)

        for key, role in (
            (self.ROADS, "roads"), (self.RAILROADS, "railroads"),
            (self.REFERENCE_STREAMS, "reference_streams"), (self.SOILS, "soils"),
            (self.FEMA_100, "flood_hazard_100yr"), (self.FEMA_500, "flood_hazard_500yr"),
        ):
            if raw_inputs[key]:
                source_records.append(SourceRecord(
                    role, "User-supplied authoritative/local layer", "User input",
                    str(raw_inputs[key]), str(raw_inputs[key]), "manual_override",
                ).to_dict())
        if land_cover is not None:
            source_records.append(SourceRecord(
                "land_cover", "User-supplied authoritative/local raster", "User input",
                land_cover.source(), land_cover.source(), "manual_override",
            ).to_dict())

        osm_keys = (self.ROADS, self.RAILROADS, self.REFERENCE_STREAMS)
        if automatic and any(not raw_inputs[key] for key in osm_keys):
            try:
                missing_osm_roles = {
                    role for key, role in (
                        (self.ROADS, "roads"), (self.RAILROADS, "railroads"),
                        (self.REFERENCE_STREAMS, "reference_streams"),
                    ) if not raw_inputs[key]
                }
                osm, records = fetch_osm_lines(
                    bbox_wgs84, root / "01_Source" / "Reference", feedback,
                )
                source_records.extend(
                    record.to_dict() for record in records if record.role in missing_osm_roles
                )
                if not raw_inputs[self.ROADS]:
                    raw_inputs[self.ROADS] = osm.get("roads")
                if not raw_inputs[self.RAILROADS]:
                    raw_inputs[self.RAILROADS] = osm.get("railroads")
                if not raw_inputs[self.REFERENCE_STREAMS]:
                    raw_inputs[self.REFERENCE_STREAMS] = osm.get("reference_streams")
            except AcquisitionError as exc:
                review_notes.append(f"Automatic OpenStreetMap acquisition was skipped or failed: {exc}")

        if automatic and land_cover is None:
            try:
                land_tiles, records = fetch_worldcover(
                    bbox_wgs84, root / "01_Source" / "Reference" / "WorldCover", feedback,
                )
                source_records.extend(record.to_dict() for record in records)
                land_cover = self._mosaic(
                    land_tiles, root / "01_Source" / "Reference" / "WorldCover" / "worldcover_mosaic.vrt",
                    context, feedback,
                )
            except AcquisitionError as exc:
                review_notes.append(f"Automatic ESA WorldCover acquisition failed: {exc}")

        soil_rasters = {}
        if automatic and not raw_inputs[self.SOILS]:
            soil_crs = QgsCoordinateReferenceSystem("EPSG:152160")
            if soil_crs.isValid():
                try:
                    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                    transform = QgsCoordinateTransform(wgs84, soil_crs, context.transformContext())
                    soil_extent = transform.transformBoundingBox(QgsRectangle(*bbox_wgs84))
                    soil_rasters, records = fetch_soilgrids(
                        (soil_extent.xMinimum(), soil_extent.yMinimum(), soil_extent.xMaximum(), soil_extent.yMaximum()),
                        root / "01_Source" / "Reference" / "SoilGrids", feedback,
                    )
                    source_records.extend(record.to_dict() for record in records)
                except Exception as exc:
                    review_notes.append(f"Automatic SoilGrids acquisition failed: {exc}")
            else:
                review_notes.append("EPSG:152160 was unavailable, so automatic SoilGrids acquisition was skipped.")

        for flood_key, role, label in (
            (self.FEMA_100, "flood_hazard_100yr", "100-year"),
            (self.FEMA_500, "flood_hazard_500yr", "500-year"),
        ):
            if not raw_inputs[flood_key]:
                source_records.append({
                    "role": role, "dataset": "Global analytical flood hazard",
                    "provider": "Not automatically selected", "url": "", "local_path": "",
                    "status": "not_available",
                    "note": "No credential-free globally authoritative analysis layer was found; supply an approved national/regional layer.",
                })
                review_notes.append(
                    f"No automatic {label} flood-hazard layer was used. Missing flood data is not evidence of no flood hazard."
                )
        write_json(root / "01_Source" / "INPUT_SOURCE_PROVENANCE.json", {
            "boundary_wgs84_bbox": bbox_wgs84,
            "source_policy": "automatic_public_with_manual_overrides" if automatic else "manual_only",
            "sources": source_records,
        })

        feedback.pushInfo("Workflow 3/8: reprojecting and clipping the DEM.")
        terrain_dir = root / "02_Processed" / "Terrain"
        warped_dem = terrain_dir / "dem_project_crs.tif"
        self._run("gdal:warpreproject", {
            "INPUT": dem, "SOURCE_CRS": None, "TARGET_CRS": target_crs,
            "RESAMPLING": 1, "NODATA": None, "TARGET_RESOLUTION": None,
            "OPTIONS": "COMPRESS=DEFLATE|TILED=YES", "DATA_TYPE": 0,
            "TARGET_EXTENT": None, "TARGET_EXTENT_CRS": None,
            "MULTITHREADING": True, "EXTRA": "", "OUTPUT": str(warped_dem),
        }, context, feedback)
        elevation_dem = warped_dem
        if abs(z_factor - 1.0) > 1e-12:
            converted_dem = terrain_dir / "dem_project_crs_and_z_units.tif"
            self._run("gdal:rastercalculator", {
                "INPUT_A": str(warped_dem), "BAND_A": 1,
                "INPUT_B": None, "BAND_B": None, "INPUT_C": None, "BAND_C": None,
                "INPUT_D": None, "BAND_D": None, "INPUT_E": None, "BAND_E": None,
                "INPUT_F": None, "BAND_F": None,
                "FORMULA": f"A*{z_factor:.15g}", "NO_DATA": None,
                "EXTENT_OPT": 0, "PROJWIN": None, "RTYPE": 5,
                "OPTIONS": "COMPRESS=DEFLATE|TILED=YES", "EXTRA": "",
                "OUTPUT": str(converted_dem),
            }, context, feedback)
            elevation_dem = converted_dem
            review_notes.append(
                f"DEM elevations were converted from {z_unit_name} to {unit_name} "
                f"using factor {z_factor:.12g}; verify the declared source Z units."
            )
        clipped_dem = terrain_dir / "dem_clipped.tif"
        self._run("gdal:cliprasterbymasklayer", {
            "INPUT": str(elevation_dem), "MASK": boundary, "SOURCE_CRS": None,
            "TARGET_CRS": target_crs, "NODATA": None, "ALPHA_BAND": False,
            "CROP_TO_CUTLINE": True, "KEEP_RESOLUTION": True,
            "SET_RESOLUTION": False, "X_RESOLUTION": None, "Y_RESOLUTION": None,
            "MULTITHREADING": True, "OPTIONS": "COMPRESS=DEFLATE|TILED=YES",
            "DATA_TYPE": 0, "EXTRA": "", "OUTPUT": str(clipped_dem),
        }, context, feedback)
        feedback.setProgress(30)

        feedback.pushInfo("Workflow 4/8: filling sinks and deriving terrain review rasters.")
        filled_dem = terrain_dir / "dem_filled.tif"
        flow_direction_native = terrain_dir / "flow_direction_native.tif"
        basins_native = terrain_dir / "watershed_basins_native.tif"
        self._run("native:fillsinkswangliu", {
            "INPUT": str(clipped_dem), "BAND": 1,
            "MIN_SLOPE": self.parameterAsDouble(parameters, self.MIN_SLOPE, context),
            "OUTPUT_FILLED_DEM": str(filled_dem),
            "OUTPUT_FLOW_DIRECTIONS": str(flow_direction_native),
            "OUTPUT_WATERSHED_BASINS": str(basins_native),
            "CREATION_OPTIONS": "COMPRESS=DEFLATE|TILED=YES",
        }, context, feedback)
        hillshade = terrain_dir / "hillshade.tif"
        slope = terrain_dir / "slope_percent.tif"
        aspect = terrain_dir / "aspect_degrees.tif"
        self._run("native:hillshade", {
            "INPUT": str(filled_dem), "Z_FACTOR": 1.0, "AZIMUTH": 300.0,
            "V_ANGLE": 40.0, "OUTPUT": str(hillshade),
        }, context, feedback)
        self._run("gdal:slope", {
            "INPUT": str(filled_dem), "BAND": 1, "SCALE": 1.0,
            "AS_PERCENT": True, "COMPUTE_EDGES": True, "ZEVENBERGEN": False,
            "OPTIONS": "COMPRESS=DEFLATE|TILED=YES", "EXTRA": "", "OUTPUT": str(slope),
        }, context, feedback)
        self._run("native:aspect", {
            "INPUT": str(filled_dem), "Z_FACTOR": 1.0, "OUTPUT": str(aspect),
        }, context, feedback)
        outputs.update({"filled_dem": str(filled_dem), "hillshade": str(hillshade), "slope_percent": str(slope), "aspect": str(aspect)})
        feedback.setProgress(52)

        feedback.pushInfo("Workflow 5/8: calculating flow accumulation and drainage candidates.")
        filled_layer = QgsRasterLayer(str(filled_dem), "filled_dem")
        pixel_x = filled_layer.rasterUnitsPerPixelX()
        pixel_y = filled_layer.rasterUnitsPerPixelY()
        cells = threshold_cells(
            self.parameterAsDouble(parameters, self.DRAINAGE_ACRES, context),
            pixel_x, pixel_y, unit_name,
        )
        drainage = self._grass_watershed(filled_dem, cells, root / "02_Processed" / "Drainage", context, feedback)
        outputs.update(drainage)
        derived_stream_lines = self._gpkg(gpkg, "derived_streams")
        vector_streams = self._stream_to_vector(drainage["stream"], derived_stream_lines, context, feedback)
        outputs["derived_stream_lines"] = vector_streams
        self._run("native:savefeatures", {
            "INPUT": vector_streams, "OUTPUT": self._gpkg(hec_gpkg, "Derived_Streams"),
        }, context, feedback)
        hec_terrain = root / "HEC_RAS_GIS_Export" / "Terrain_Elevation.tif"
        hec_stream_raster = root / "HEC_RAS_GIS_Export" / "Derived_Streams_Raster.tif"
        shutil.copy2(filled_dem, hec_terrain)
        shutil.copy2(drainage["stream"], hec_stream_raster)
        outputs["hec_ras_terrain"] = str(hec_terrain)
        outputs["hec_ras_stream_raster"] = str(hec_stream_raster)
        feedback.setProgress(68)

        feedback.pushInfo("Workflow 6/8: clipping optional reference layers.")
        optional_specs = (
            (self.ROADS, "roads", "Roads"),
            (self.RAILROADS, "railroads", "Railroads"),
            (self.REFERENCE_STREAMS, "reference_streams", "Reference_Streams"),
            (self.SOILS, "hydrologic_soils", "Hydrologic_Soils"),
            (self.FEMA_100, "flood_hazard_100yr", "Flood_Hazard_100yr"),
            (self.FEMA_500, "flood_hazard_500yr", "Flood_Hazard_500yr"),
        )
        clipped = {}
        for key, local_name, hec_name in optional_specs:
            raw = raw_inputs.get(key)
            result = self._clip_vector(raw, local_name, target_crs, boundary, gpkg, context, feedback)
            if result:
                clipped[key] = result
                outputs[local_name] = result
                self._run("native:savefeatures", {
                    "INPUT": result, "OUTPUT": self._gpkg(hec_gpkg, hec_name),
                }, context, feedback)

        if land_cover is not None:
            land_cover_output = root / "02_Processed" / "Categorical" / "land_cover_clipped.tif"
            self._run("gdal:cliprasterbymasklayer", {
                "INPUT": land_cover, "MASK": boundary, "SOURCE_CRS": None,
                "TARGET_CRS": target_crs, "NODATA": None, "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True, "KEEP_RESOLUTION": True,
                "SET_RESOLUTION": False, "X_RESOLUTION": None, "Y_RESOLUTION": None,
                "MULTITHREADING": True, "OPTIONS": "COMPRESS=DEFLATE|TILED=YES",
                "DATA_TYPE": 0, "EXTRA": "", "OUTPUT": str(land_cover_output),
            }, context, feedback)
            outputs["land_cover"] = str(land_cover_output)
        for property_name, raster in soil_rasters.items():
            soil_output = root / "02_Processed" / "Categorical" / f"soilgrids_{property_name}_surface.tif"
            self._run("gdal:warpreproject", {
                "INPUT": raster, "SOURCE_CRS": QgsCoordinateReferenceSystem("EPSG:152160"),
                "TARGET_CRS": target_crs, "RESAMPLING": 1, "NODATA": None,
                "TARGET_RESOLUTION": None, "OPTIONS": "COMPRESS=DEFLATE|TILED=YES",
                "DATA_TYPE": 0, "TARGET_EXTENT": None, "TARGET_EXTENT_CRS": None,
                "MULTITHREADING": True, "EXTRA": "", "OUTPUT": str(soil_output),
            }, context, feedback)
            outputs[f"soilgrids_{property_name}"] = str(soil_output)
        feedback.setProgress(80)

        feedback.pushInfo("Workflow 7/8: screening potential transportation/drainage crossings.")
        crossings = None
        crossing_streams = clipped.get(self.REFERENCE_STREAMS) or vector_streams
        transport_layers = [
            layer for layer in (clipped.get(self.ROADS), clipped.get(self.RAILROADS)) if layer
        ]
        transportation = None
        if len(transport_layers) == 1:
            transportation = transport_layers[0]
        elif len(transport_layers) > 1:
            transportation = self._run("native:mergevectorlayers", {
                "LAYERS": transport_layers, "CRS": target_crs,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            }, context, feedback)["OUTPUT"]
        if crossing_streams and transportation:
            crossings = self._gpkg(gpkg, "potential_crossings")
            self._run("native:lineintersections", {
                "INPUT": crossing_streams, "INTERSECT": transportation,
                "INPUT_FIELDS": [], "INTERSECT_FIELDS": [],
                "INTERSECT_FIELDS_PREFIX": "transport_", "OUTPUT": crossings,
            }, context, feedback)
            outputs["potential_crossings"] = crossings
            self._run("native:savefeatures", {
                "INPUT": crossings, "OUTPUT": self._gpkg(hec_gpkg, "Potential_Crossings"),
            }, context, feedback)
        else:
            review_notes.append("Potential crossings were not created because both a usable stream line layer and transportation line layer were not available.")
        feedback.setProgress(90)

        feedback.pushInfo("Workflow 8/8: writing QA and final output manifests.")
        qa = {
            "product": "PreHydro GIS Tool 4.2 - Global QGIS Edition",
            "status": "COMPLETE_WITH_REVIEW" if review_notes else "COMPLETE",
            "completed_utc": utc_now(),
            "target_crs": target_crs.authid() or target_crs.toWkt(),
            "target_map_units": unit_name,
            "input_dem_z_units": z_unit_name,
            "dem_z_conversion_factor": z_factor,
            "drainage_area_acres": self.parameterAsDouble(parameters, self.DRAINAGE_ACRES, context),
            "drainage_threshold_cells": cells,
            "pixel_width": pixel_x,
            "pixel_height": pixel_y,
            "outputs": outputs,
            "source_provenance": str(root / "01_Source" / "INPUT_SOURCE_PROVENANCE.json"),
            "review_notes": review_notes,
        }
        write_json(paths["qa"], qa)
        manifest = dict(qa)
        manifest["project_root"] = str(root)
        write_manifest(paths, manifest)

        feedback.setProgress(100)
        for note in review_notes:
            feedback.pushWarning("REVIEW REQUIRED: " + note)
        feedback.pushInfo(f"Complete workflow outputs: {root}")

        self._load_paths = []
        if self.parameterAsBoolean(parameters, self.ADD_TO_MAP, context):
            self._load_paths = [
                ("vector", boundary, "Official project boundary"),
                ("raster", str(filled_dem), "Terrain elevation"),
                ("raster", str(hillshade), "Terrain hillshade"),
                ("raster", str(slope), "Terrain slope percent"),
                ("raster", drainage["stream"], "Derived stream raster"),
            ]
            if vector_streams:
                self._load_paths.append(("vector", vector_streams, "Derived streams"))
            if crossings:
                self._load_paths.append(("vector", crossings, "Potential crossings - review required"))
            for key, name in (
                (self.ROADS, "Roads"), (self.RAILROADS, "Railroads"),
                (self.REFERENCE_STREAMS, "Reference streams"),
                (self.SOILS, "Authoritative soils"),
                (self.FEMA_100, "100-year flood hazard"),
                (self.FEMA_500, "500-year flood hazard"),
            ):
                if clipped.get(key):
                    self._load_paths.append(("vector", clipped[key], name))
            if outputs.get("land_cover"):
                self._load_paths.append(("raster", outputs["land_cover"], "Land cover"))
            for property_name in ("sand", "clay"):
                source = outputs.get(f"soilgrids_{property_name}")
                if source:
                    self._load_paths.append(("raster", source, f"SoilGrids surface {property_name}"))

        return {
            self.OUTPUT_FOLDER: str(root),
            self.OUTPUT_BOUNDARY: boundary,
            self.OUTPUT_DEM: str(filled_dem),
            self.OUTPUT_STREAMS: drainage["stream"],
            self.OUTPUT_CROSSINGS: crossings or "",
            self.OUTPUT_MANIFEST: str(paths["manifest"]),
        }

    def postProcessAlgorithm(self, context, feedback):
        project = QgsProject.instance()
        group = project.layerTreeRoot().findGroup("PreHydro GIS Tool - Global")
        if group is None:
            group = project.layerTreeRoot().addGroup("PreHydro GIS Tool - Global")
        boundary_layer = None
        for layer_type, source, name in getattr(self, "_load_paths", []):
            layer = QgsRasterLayer(source, name) if layer_type == "raster" else QgsVectorLayer(source, name, "ogr")
            if layer.isValid():
                project.addMapLayer(layer, False)
                group.addLayer(layer)
                if name == "Official project boundary":
                    boundary_layer = layer
            else:
                feedback.pushWarning(f"Output exists but could not be added to the map: {source}")
        if boundary_layer is not None:
            try:
                from qgis.utils import iface
                iface.mapCanvas().setExtent(boundary_layer.extent())
                iface.mapCanvas().refresh()
            except (AttributeError, ImportError):
                feedback.pushWarning("Layers were added, but the map canvas could not be zoomed automatically.")
        return {}
