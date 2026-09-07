# Port status: Global QGIS 4.2

Implemented: QGIS provider packaging; automatic local UTM; Copernicus GLO-30/GLO-90
terrain acquisition; ESA WorldCover acquisition; site-sized OpenStreetMap roads,
railways, and waterways; ISRIC SoilGrids sand/clay references; manual authoritative
overrides; geometry repair; terrain hydrology; stream conversion; crossing screening;
GeoPackage/GeoTIFF exports; provenance; QA; and manifests.

Not automatically acquired: analytical flood-hazard polygons, rainfall distributions,
or country-specific authoritative datasets. Supply these manually. The tool never
fabricates unavailable data or treats missing flood information as no flood hazard.

Global sources are screening inputs and do not supersede licensed survey, national
mapping, regulator, owner, or engineering data.
