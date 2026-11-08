"""Download a void-filled SRTM DEM from OpenTopography and reproject it to the project CRS.

Usage, from the repo root with OPENTOPO_API_KEY set:
    conda activate dam-drainage
    python scripts/get_dem.py

Writes data/dem_<source>_wgs84.tif and data/dem_<source>_utm.tif, where <source> is dem.source
in config/dams.yaml in lower case.
"""

import os
from pathlib import Path

import rasterio
import requests
import yaml
from rasterio.warp import Resampling, calculate_default_transform, reproject
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dams.yaml"
DATA_DIR = ROOT / "data"
API_URL = "https://portal.opentopography.org/API/globaldem"
NODATA = -9999.0


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def download_dem(bbox, demtype, out_path):
    """Request the DEM for the bounding box and save the GeoTIFF, showing download progress."""
    api_key = os.environ.get("OPENTOPO_API_KEY")
    if not api_key:
        raise RuntimeError("Environment variable OPENTOPO_API_KEY is not set.")

    params = {
        "demtype": demtype,
        "west": bbox["west"],
        "south": bbox["south"],
        "east": bbox["east"],
        "north": bbox["north"],
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }

    print("Waiting for OpenTopography to prepare the file ...")
    with requests.get(API_URL, params=params, stream=True, timeout=600) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0)) or None
        with open(out_path, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, unit_divisor=1024, desc="Downloading"
        ) as bar:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                bar.update(len(chunk))

    # A GeoTIFF starts with the TIFF byte-order marker; anything else is an error message.
    with open(out_path, "rb") as f:
        header = f.read(4)
    if header not in (b"II*\x00", b"MM\x00*"):
        message = out_path.read_text(errors="replace")[:500]
        out_path.unlink()
        raise RuntimeError(f"OpenTopography did not return a GeoTIFF:\n{message}")


def reproject_dem(src_path, dst_path, dst_crs, resolution):
    """Reproject the DEM to dst_crs at the given resolution using bilinear resampling."""
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=resolution
        )
        profile = src.profile.copy()
        profile.update(
            crs=dst_crs,
            transform=transform,
            width=width,
            height=height,
            dtype="float32",
            nodata=NODATA,
            compress="lzw",
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs=dst_crs,
                dst_nodata=NODATA,
                resampling=Resampling.bilinear,
            )


def main():
    config = load_config()
    dem_cfg = config["dem"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = DATA_DIR / f"dem_{dem_cfg['source'].lower()}_wgs84.tif"
    utm_path = DATA_DIR / f"dem_{dem_cfg['source'].lower()}_utm.tif"

    print(f"Downloading {dem_cfg['source']} for bbox {dem_cfg['bbox']}")
    download_dem(dem_cfg["bbox"], dem_cfg["source"], raw_path)
    print(f"Saved {raw_path}")

    print(f"Reprojecting to {config['crs']} at {dem_cfg['resolution_m']} m ...")
    reproject_dem(raw_path, utm_path, config["crs"], dem_cfg["resolution_m"])
    print(f"Saved {utm_path}")


if __name__ == "__main__":
    main()
