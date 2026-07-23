# St. Andrew's Point Pioneer Cemetery Interactive Maps

This project converts the workbook `St. Andrew's Point Pioneer Cemetery Data.xlsx` into georeferenced point data and publishes an interactive 2D map that can be hosted on GitHub Pages without API keys.
https://joshuahoy.github.io/Dembo/

## Research context

This research investigates African cultural retention and embodied resistance within the burial landscape of the St. Andrew’s Point Pioneer Cemetery in PEI—an understudied site in the Northeast Atlantic African Diaspora. Central to this site’s history is Dembo Suckles, who was taken from Benin as a teenager and enslaved through regional Atlantic networks, and whom oral traditions identify as being buried at the site alongside his family. A preliminary archaeological survey reveals burial markers and spatial patterns suggesting syncretic West African and European mortuary traditions, including possible slab-stone grave coverings, west‑facing orientations linked to “homecoming” symbolism, and paired sandstone head‑and‑foot markers. These material choices indicate how the Suckles family expressed belonging, memory, and spiritual continuity despite displacement and structural erasure. By situating PEI within broader diasporic movements, this study demonstrates how mortuary practice served as acts of resistance and cultural retention, illuminating understandings of agency and spiritual continuity in life and death.

## What is included

- `scripts/00_inspect_excel.py` - quick workbook schema inspection.
- `scripts/01_validate_and_export.py` - coordinate validation, georeferencing, and export.
- `scripts/03_prepare_nrcan_elevation.py` - downloads and processes NRCan 1m DEM/hillshade tiles for local web mapping.
- `data/cemetery_clean.csv` - cleaned tabular output.
- `data/cemetery_clean.geojson` - canonical geospatial output.
- `validation/coordinate_report.txt` - QA summary and transform residuals.
- `docs/index.html` - primary 2D interactive topographic map at the GitHub Pages root URL.
- `docs/map2d.html` - legacy path that now redirects to the root map (`docs/index.html`).
- `docs/data/cemetery_clean.geojson` - hosted map data used by the 2D page.
- `docs/tiles/nrcan_hillshade/` - local XYZ hillshade PNG tiles (generated).

## Run locally

1. Ensure Python is available (the current workspace uses Python 3.14).
2. Rebuild outputs:

```powershell
C:/Users/HOYJOS1/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/01_validate_and_export.py
```

3. Build local NRCan elevation tiles (2D hillshade):

```powershell
C:/Users/HOYJOS1/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/03_prepare_nrcan_elevation.py
```

4. Open `docs/index.html` in a local web server for reliable fetch behavior:

```powershell
C:/Users/HOYJOS1/AppData/Local/Python/pythoncore-3.14-64/python.exe -m http.server 8080
```

4. Visit `http://localhost:8080/docs/`.

## Data method summary

- The workbook includes local grid coordinates (`Northing (Y)`, `Easting (X)`) for most points.
- The `Coordinate Points` sheet contains anchor points with known latitude and longitude.
- Script `01_validate_and_export.py` fits an affine-like plane mapping from local grid `(Y, X)` to `(lat, lon)` using least-squares over anchor points.
- Surface and subterranean points are projected into WGS84 and exported.

## Attribution

- OpenStreetMap contributors for map data and alternate raster tiles.
- OpenTopoMap (CC-BY-SA) style tiles with SRTM terrain context.
- Natural Resources Canada high-resolution 1m DTM/Hillshade (PEI 2020) for local elevation layers.
