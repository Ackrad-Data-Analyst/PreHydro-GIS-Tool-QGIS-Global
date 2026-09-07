"""Processing provider registration."""

from qgis.core import QgsProcessingProvider

from .algorithms.fully_hydro import FullyHydroPreparationAlgorithm
from .algorithms.preflight import FullyHydroPreflightAlgorithm


class FullyHydroProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(FullyHydroPreflightAlgorithm())
        self.addAlgorithm(FullyHydroPreparationAlgorithm())

    def id(self):
        return "fullyhydro"

    def name(self):
        return "PreHydro GIS Tool - Global"

    def longName(self):
        return self.name()
