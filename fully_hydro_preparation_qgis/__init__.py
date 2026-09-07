"""QGIS entry point for PreHydro GIS Tool - Global QGIS Edition."""


def classFactory(iface):
    from .plugin import FullyHydroPreparationPlugin

    return FullyHydroPreparationPlugin(iface)
