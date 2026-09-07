"""Plugin lifecycle."""

from qgis.core import QgsApplication

from .provider import FullyHydroProvider


class FullyHydroPreparationPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        self.provider = FullyHydroProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
