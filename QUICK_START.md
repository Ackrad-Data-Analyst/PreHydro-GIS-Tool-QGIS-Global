# Quick start

1. Install the plugin ZIP in QGIS 3.44+.
2. Run **00 - Preflight Environment Check** and resolve every failure.
3. Add or create the official project/watershed boundary polygon.
4. Run **PreHydro GIS Tool 4.2 - Global QGIS**.
5. Select **Automatically fetch public global sources where manual inputs are missing**.
6. Leave Target CRS blank for automatic local UTM unless the boundary spans multiple UTM zones.
7. Leave a source input blank to fetch it automatically; select a layer to override it.
8. Give the run a new project name and click **Run**.
9. Review `01_Source/INPUT_SOURCE_PROVENANCE.json`, `qa_qc/RUN_QA.json`, and
   `FINAL_OUTPUT_MANIFEST.txt` before using the outputs.

For a first test, use a small boundary. Automatic downloads are not intended for an
entire country or continent in one run.
