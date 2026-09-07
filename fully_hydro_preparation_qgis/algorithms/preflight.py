"""QGIS environment preflight."""

from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingParameterFile,
)

from ..core import utc_now, write_json


REQUIRED_ALGORITHMS = (
    "native:fixgeometries",
    "native:dissolve",
    "native:reprojectlayer",
    "native:clip",
    "native:lineintersections",
    "native:mergevectorlayers",
    "native:savefeatures",
    "gdal:warpreproject",
    "gdal:cliprasterbymasklayer",
    "gdal:rastercalculator",
    "gdal:buildvirtualraster",
    "native:fillsinkswangliu",
    "native:hillshade",
    "native:aspect",
    "gdal:slope",
)

GRASS_WATERSHED_IDS = ("grass:r.watershed", "grass7:r.watershed")
GRASS_TO_VECTOR_IDS = ("grass:r.to.vect", "grass7:r.to.vect")


class FullyHydroPreflightAlgorithm(QgsProcessingAlgorithm):
    OUTPUT_PARENT = "OUTPUT_PARENT"
    REPORT = "REPORT"

    def name(self):
        return "preflight"

    def displayName(self):
        return "00 - Preflight Environment Check"

    def group(self):
        return "00 - START HERE"

    def groupId(self):
        return "start_here"

    def shortHelpString(self):
        return (
            "Checks QGIS 3.44+, write access, required native/GDAL algorithms, and "
            "the GRASS r.watershed and r.to.vect algorithms. Run this before a full project."
        )

    def createInstance(self):
        return FullyHydroPreflightAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.OUTPUT_PARENT,
                "Existing writable parent folder for project outputs",
                behavior=QgsProcessingParameterFile.Folder,
            )
        )
        self.addOutput(QgsProcessingOutputFile(self.REPORT, "Preflight report"))

    def processAlgorithm(self, parameters, context, feedback):
        parent = Path(self.parameterAsFile(parameters, self.OUTPUT_PARENT, context)).resolve()
        if not parent.is_dir():
            raise QgsProcessingException(f"Output parent folder does not exist: {parent}")

        registry = QgsApplication.processingRegistry()
        missing = [algorithm_id for algorithm_id in REQUIRED_ALGORITHMS if registry.algorithmById(algorithm_id) is None]
        grass_id = next((item for item in GRASS_WATERSHED_IDS if registry.algorithmById(item)), None)
        grass_vector_id = next((item for item in GRASS_TO_VECTOR_IDS if registry.algorithmById(item)), None)

        write_test = parent / ".fully_hydro_qgis_write_test"
        try:
            write_test.write_text("ok", encoding="utf-8")
            write_test.unlink()
            writable = True
        except OSError:
            writable = False

        qgis_version = Qgis.version()
        qgis_version_int = int(Qgis.versionInt())
        checks = {
            "qgis_3_44_or_newer": qgis_version_int >= 34400,
            "output_parent_writable": writable,
            "required_processing_algorithms": not missing,
            "grass_watershed_available": grass_id is not None,
            "grass_raster_to_vector_available": grass_vector_id is not None,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        report = {
            "product": "PreHydro GIS Tool 4.2 - Global QGIS Edition",
            "checked_utc": utc_now(),
            "status": status,
            "qgis_version": qgis_version,
            "checks": checks,
            "missing_algorithms": missing,
            "grass_watershed_algorithm": grass_id,
            "grass_raster_to_vector_algorithm": grass_vector_id,
            "output_parent": str(parent),
        }
        report_path = parent / "FULLY_HYDRO_QGIS_PREFLIGHT.json"
        write_json(report_path, report)

        feedback.pushInfo(f"QGIS version: {qgis_version}")
        feedback.pushInfo(f"Required algorithms available: {not missing}")
        feedback.pushInfo(f"GRASS watershed provider: {grass_id or 'MISSING'}")
        feedback.pushInfo(f"GRASS raster-to-vector provider: {grass_vector_id or 'MISSING'}")
        feedback.pushInfo(f"Output parent writable: {writable}")
        feedback.pushInfo(f"Preflight status: {status}")

        if status != "PASS":
            details = []
            if qgis_version_int < 34400:
                details.append("Install QGIS 3.44 or newer")
            if missing:
                details.append("missing algorithms: " + ", ".join(missing))
            if grass_id is None:
                details.append("enable/install the GRASS Processing provider")
            if grass_vector_id is None:
                details.append("GRASS r.to.vect is missing from the Processing provider")
            if not writable:
                details.append("choose a writable output folder")
            raise QgsProcessingException(
                "Preflight failed. " + "; ".join(details) + f". Report: {report_path}"
            )
        return {self.REPORT: str(report_path)}
