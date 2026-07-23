import json
import math
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.request import urlretrieve
from xml.etree import ElementTree as ET

import mercantile
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "nrcan" / "raw"
WORK_DIR = ROOT / "data" / "nrcan" / "work"
OUT_DIR = ROOT / "data" / "nrcan" / "out"
DOCS_TILES = ROOT / "docs" / "tiles"

KMZ_URL = "https://ftp.maps.canada.ca/pub/elevation/dem_mne/highresolution_hauteresolution/dtm_mnt/1m/PEI/Prince_Edward_Island_2020/INDEX_utm20_PEI_Prince_Edward_Island_2020.kmz"
UTM_BASE_URL = "https://ftp.maps.canada.ca/pub/elevation/dem_mne/highresolution_hauteresolution/dtm_mnt/1m/PEI/Prince_Edward_Island_2020/utm20/"

GEOJSON_PATH = ROOT / "docs" / "data" / "cemetery_clean.geojson"


def ensure_dirs() -> None:
    for p in [RAW_DIR, WORK_DIR, OUT_DIR, DOCS_TILES]:
        p.mkdir(parents=True, exist_ok=True)


def bbox_from_points() -> Tuple[float, float, float, float]:
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    lons = [f["geometry"]["coordinates"][0] for f in data["features"]]
    lats = [f["geometry"]["coordinates"][1] for f in data["features"]]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # Add ~220m pad for contextual terrain
    pad_deg = 0.0020
    return (min_lon - pad_deg, min_lat - pad_deg, max_lon + pad_deg, max_lat + pad_deg)


def download_if_missing(url: str, out_path: Path) -> None:
    if out_path.exists():
        return
    print(f"Downloading {url}")
    urlretrieve(url, out_path)


def parse_kmz_tiles(kmz_path: Path) -> Dict[str, Tuple[float, float, float, float]]:
    with zipfile.ZipFile(kmz_path) as zf:
        kml_bytes = zf.read("doc.kml")

    root = ET.fromstring(kml_bytes)
    ns = {"k": "http://www.opengis.net/kml/2.2"}

    tiles = {}
    for pm in root.findall(".//k:Placemark", ns):
        name_el = pm.find("k:name", ns)
        coords_el = pm.find(".//k:coordinates", ns)
        if name_el is None or coords_el is None or coords_el.text is None:
            continue

        coords = []
        for token in coords_el.text.strip().split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            lon = float(parts[0])
            lat = float(parts[1])
            coords.append((lon, lat))

        if not coords:
            continue

        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        tiles[name_el.text.strip()] = (min(lons), min(lats), max(lons), max(lats))

    return tiles


def intersects(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def build_tile_name_variants(tile_id: str) -> Tuple[str, str]:
    # tile id is like 1m_utm20_e_0_109
    stem = tile_id
    return (f"dtm_{stem}.tif", f"hillshade_dtm_{stem}.tif")


def reproject_to_3857(src_path: Path, dst_path: Path) -> None:
    with rasterio.open(src_path) as src:
        dst_crs = CRS.from_epsg(3857)
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update(
            {
                "crs": dst_crs,
                "transform": transform,
                "width": width,
                "height": height,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
                "predictor": 2,
            }
        )

        with rasterio.open(dst_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )


def clip_raster(src_path: Path, dst_path: Path, bbox_4326: Tuple[float, float, float, float]) -> None:
    with rasterio.open(src_path) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox_4326, densify_pts=21)
        window = rasterio.windows.from_bounds(left, bottom, right, top, src.transform)
        window = window.round_offsets().round_lengths()
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

        data = src.read(window=window)
        transform = rasterio.windows.transform(window, src.transform)

        meta = src.meta.copy()
        meta.update(
            {
                "height": data.shape[1],
                "width": data.shape[2],
                "transform": transform,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
            }
        )

        with rasterio.open(dst_path, "w", **meta) as dst:
            dst.write(data)


def write_hillshade_tiles(hillshade_3857: Path, out_tiles_dir: Path) -> None:
    out_tiles_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(hillshade_3857) as src:
        bbox4326 = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        minx, miny, maxx, maxy = bbox4326

        z_min = 14
        z_max = 19

        for z in range(z_min, z_max + 1):
            tiles = list(mercantile.tiles(minx, miny, maxx, maxy, [z]))
            for tile in tiles:
                b = mercantile.xy_bounds(tile)
                width = 256
                height = 256
                transform = from_bounds(b.left, b.bottom, b.right, b.top, width, height)

                arr = np.zeros((1, height, width), dtype=np.uint8)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=arr,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=src.crs,
                    resampling=Resampling.bilinear,
                    dst_nodata=0,
                )

                out_dir = out_tiles_dir / str(z) / str(tile.x)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_png = out_dir / f"{tile.y}.png"

                profile = {
                    "driver": "PNG",
                    "height": height,
                    "width": width,
                    "count": 1,
                    "dtype": "uint8",
                }
                with rasterio.open(out_png, "w", **profile) as dst:
                    dst.write(arr)


def write_dem_terrain_rgb_tiles(dem_3857: Path, out_tiles_dir: Path) -> None:
    out_tiles_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_3857) as src:
        bbox4326 = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        minx, miny, maxx, maxy = bbox4326

        z_min = 14
        z_max = 19

        for z in range(z_min, z_max + 1):
            tiles = list(mercantile.tiles(minx, miny, maxx, maxy, [z]))
            for tile in tiles:
                b = mercantile.xy_bounds(tile)
                width = 256
                height = 256
                transform = from_bounds(b.left, b.bottom, b.right, b.top, width, height)

                elev = np.full((height, width), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=elev,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=src.crs,
                    resampling=Resampling.bilinear,
                    dst_nodata=np.nan,
                )

                # Terrarium encoding: height = (R * 256 + G + B / 256) - 32768
                safe = np.where(np.isnan(elev), -32768.0, elev)
                terr = safe + 32768.0
                r = np.floor(terr / 256.0).astype(np.int32)
                g = np.floor(terr % 256.0).astype(np.int32)
                bch = np.floor((terr - np.floor(terr)) * 256.0).astype(np.int32)

                r = np.clip(r, 0, 255).astype(np.uint8)
                g = np.clip(g, 0, 255).astype(np.uint8)
                bch = np.clip(bch, 0, 255).astype(np.uint8)

                rgb = np.stack([r, g, bch], axis=0)

                out_dir = out_tiles_dir / str(z) / str(tile.x)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_png = out_dir / f"{tile.y}.png"

                profile = {
                    "driver": "PNG",
                    "height": height,
                    "width": width,
                    "count": 3,
                    "dtype": "uint8",
                }
                with rasterio.open(out_png, "w", **profile) as dst:
                    dst.write(rgb)


def main() -> None:
    ensure_dirs()

    bbox = bbox_from_points()
    print("AOI bbox (lon/lat):", bbox)

    kmz_path = RAW_DIR / "index.kmz"
    download_if_missing(KMZ_URL, kmz_path)

    tiles = parse_kmz_tiles(kmz_path)
    selected = [t for t, b in tiles.items() if intersects(b, bbox)]
    if not selected:
        raise RuntimeError("No NRCan tiles intersected the project AOI")

    print("Selected tile IDs:", selected)

    dem_files = []
    hs_files = []

    for tile_id in selected:
        dem_name, hs_name = build_tile_name_variants(tile_id)

        dem_path = RAW_DIR / dem_name
        hs_path = RAW_DIR / hs_name

        download_if_missing(f"{UTM_BASE_URL}{dem_name}", dem_path)
        download_if_missing(f"{UTM_BASE_URL}{hs_name}", hs_path)

        dem_files.append(str(dem_path))
        hs_files.append(str(hs_path))

    print("Merging DEM tiles...")
    dem_srcs = [rasterio.open(p) for p in dem_files]
    dem_merged, dem_transform = merge(dem_srcs)
    dem_meta = dem_srcs[0].meta.copy()
    dem_meta.update(
        {
            "height": dem_merged.shape[1],
            "width": dem_merged.shape[2],
            "transform": dem_transform,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }
    )
    dem_mosaic = WORK_DIR / "dem_mosaic.tif"
    with rasterio.open(dem_mosaic, "w", **dem_meta) as dst:
        dst.write(dem_merged)
    for s in dem_srcs:
        s.close()

    print("Merging hillshade tiles...")
    hs_srcs = [rasterio.open(p) for p in hs_files]
    hs_merged, hs_transform = merge(hs_srcs)
    hs_meta = hs_srcs[0].meta.copy()
    hs_meta.update(
        {
            "height": hs_merged.shape[1],
            "width": hs_merged.shape[2],
            "transform": hs_transform,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }
    )
    hs_mosaic = WORK_DIR / "hillshade_mosaic.tif"
    with rasterio.open(hs_mosaic, "w", **hs_meta) as dst:
        dst.write(hs_merged)
    for s in hs_srcs:
        s.close()

    print("Clipping mosaics to AOI...")
    dem_clip = WORK_DIR / "dem_clip_utm20.tif"
    hs_clip = WORK_DIR / "hillshade_clip_utm20.tif"
    clip_raster(dem_mosaic, dem_clip, bbox)
    clip_raster(hs_mosaic, hs_clip, bbox)

    print("Reprojecting to EPSG:3857...")
    dem_3857 = OUT_DIR / "dem_clip_3857.tif"
    hs_3857 = OUT_DIR / "hillshade_clip_3857.tif"
    reproject_to_3857(dem_clip, dem_3857)
    reproject_to_3857(hs_clip, hs_3857)

    print("Generating hillshade XYZ PNG tiles...")
    hs_tiles = DOCS_TILES / "nrcan_hillshade"
    write_hillshade_tiles(hs_3857, hs_tiles)

    print("Generating terrain-rgb (Terrarium) XYZ PNG tiles...")
    dem_tiles = DOCS_TILES / "nrcan_dem_terrarium"
    write_dem_terrain_rgb_tiles(dem_3857, dem_tiles)

    summary = {
        "bbox_lonlat": bbox,
        "selected_tile_ids": selected,
        "outputs": {
            "dem_3857": str(dem_3857),
            "hillshade_3857": str(hs_3857),
            "hillshade_tiles": str(hs_tiles),
            "terrain_tiles": str(dem_tiles),
        },
        "tile_zoom_ranges": {
            "hillshade": [14, 19],
            "terrain": [14, 19],
        },
    }

    summary_path = OUT_DIR / "nrcan_pipeline_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("Done")
    print(f"Wrote summary: {summary_path}")


if __name__ == "__main__":
    main()
