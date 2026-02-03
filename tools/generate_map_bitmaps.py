#!/usr/bin/env python3
"""
Generate RLE-compressed world map bitmaps for RadioWall ESP32.

Downloads Natural Earth 1:110m coastline data and renders 4 latitude band
bitmaps (640×150 px) with Run-Length Encoding compression.

Output: ../esp32/src/world_map_data.h (C header with PROGMEM arrays)

Usage:
    python generate_map_bitmaps.py

Requirements:
    pip install geopandas matplotlib numpy Pillow requests
"""

import io
import os
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import requests
from PIL import Image


# Map dimensions (portrait: 160 wide × 560 tall - vertical slices)
MAP_WIDTH = 160
MAP_HEIGHT = 560

# Longitude slices (vertical slices of the world)
LONGITUDE_SLICES = [
    {"name": "americas", "label": "Americas", "lon_range": "-150° to -30°", "lon_min": -150.0, "lon_max": -30.0},
    {"name": "europe_africa", "label": "Europe/Africa", "lon_range": "-30° to 60°", "lon_min": -30.0, "lon_max": 60.0},
    {"name": "asia", "label": "Asia", "lon_range": "60° to 150°", "lon_min": 60.0, "lon_max": 150.0},
    {"name": "pacific", "label": "Pacific", "lon_range": "150° to -150°", "lon_min": 150.0, "lon_max": -150.0},
]

# Natural Earth data URL (1:110m resolution, public domain)
NATURAL_EARTH_URL = "https://naciscdn.org/naturalearth/110m/physical/ne_110m_coastline.zip"

# Output paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_HEADER = SCRIPT_DIR.parent / "esp32" / "src" / "world_map_data.h"


def download_natural_earth_data() -> Path:
    """Download and extract Natural Earth coastline data."""
    DATA_DIR.mkdir(exist_ok=True)
    shapefile_path = DATA_DIR / "ne_110m_coastline.shp"

    if shapefile_path.exists():
        print(f"✓ Using cached Natural Earth data: {shapefile_path}")
        return shapefile_path

    print("Downloading Natural Earth 1:110m coastline data...")
    zip_path = DATA_DIR / "ne_110m_coastline.zip"

    response = requests.get(NATURAL_EARTH_URL, stream=True)
    response.raise_for_status()

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"✓ Downloaded {zip_path.stat().st_size / 1024:.1f} KB")

    # Extract zip
    print("Extracting...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(DATA_DIR)

    print(f"✓ Extracted to {DATA_DIR}")
    return shapefile_path


def render_longitude_slice(coastlines: gpd.GeoDataFrame, lon_min: float, lon_max: float) -> np.ndarray:
    """
    Render a vertical longitude slice to a binary bitmap (160×560).

    Args:
        coastlines: GeoDataFrame with coastline geometries
        lon_min: Minimum longitude for this slice
        lon_max: Maximum longitude for this slice

    Returns:
        Binary numpy array (560×160) where 1 = land, 0 = ocean
    """
    dpi = 100

    if lon_max < lon_min:
        # Wrapping slice (e.g. Pacific: 150° to -150° via the dateline)
        # Actual span in degrees going eastward
        total_span = (lon_max + 360.0) - lon_min  # e.g. (-150+360) - 150 = 60°

        # Left half: lon_min to 180° (e.g. 150° to 180°)
        left_span = 180.0 - lon_min
        # Right half: -180° to lon_max (e.g. -180° to -150°)
        right_span = lon_max + 180.0

        # Pixel widths proportional to their angular span
        left_px = max(1, int(round(MAP_WIDTH * left_span / total_span)))
        right_px = MAP_WIDTH - left_px

        # Render left half (lon_min to 180°)
        fig_l = plt.figure(figsize=(left_px / dpi, MAP_HEIGHT / dpi), dpi=dpi)
        ax_l = fig_l.add_axes([0, 0, 1, 1])
        ax_l.set_xlim(lon_min, 180)
        ax_l.set_ylim(-90, 90)
        ax_l.axis("off")
        ax_l.set_facecolor("white")
        coastlines.plot(ax=ax_l, color="black", linewidth=0.5)
        buf_l = io.BytesIO()
        plt.savefig(buf_l, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0)
        plt.close(fig_l)
        buf_l.seek(0)
        img_l = Image.open(buf_l).convert("L").resize((left_px, MAP_HEIGHT), Image.Resampling.LANCZOS)

        # Render right half (-180° to lon_max)
        fig_r = plt.figure(figsize=(right_px / dpi, MAP_HEIGHT / dpi), dpi=dpi)
        ax_r = fig_r.add_axes([0, 0, 1, 1])
        ax_r.set_xlim(-180, lon_max)
        ax_r.set_ylim(-90, 90)
        ax_r.axis("off")
        ax_r.set_facecolor("white")
        coastlines.plot(ax=ax_r, color="black", linewidth=0.5)
        buf_r = io.BytesIO()
        plt.savefig(buf_r, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0)
        plt.close(fig_r)
        buf_r.seek(0)
        img_r = Image.open(buf_r).convert("L").resize((right_px, MAP_HEIGHT), Image.Resampling.LANCZOS)

        # Stitch left + right
        img = Image.new("L", (MAP_WIDTH, MAP_HEIGHT), 255)
        img.paste(img_l, (0, 0))
        img.paste(img_r, (left_px, 0))
    else:
        # Normal non-wrapping slice
        fig = plt.figure(figsize=(MAP_WIDTH / dpi, MAP_HEIGHT / dpi), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(-90, 90)
        ax.axis("off")
        ax.set_facecolor("white")
        coastlines.plot(ax=ax, color="black", linewidth=0.5)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0)
        plt.close(fig)

        buf.seek(0)
        img = Image.open(buf).convert("L")
        img = img.resize((MAP_WIDTH, MAP_HEIGHT), Image.Resampling.LANCZOS)

    # Convert to binary array (threshold at 128)
    bitmap = np.array(img)
    binary = (bitmap < 128).astype(np.uint8)  # Black (coastlines) = 1, White (ocean) = 0

    return binary


def rle_compress(bitmap: np.ndarray) -> List[Tuple[int, int]]:
    """
    Run-Length Encode a binary bitmap.

    Args:
        bitmap: Binary 2D array (640×150) with values 0 or 1

    Returns:
        List of (count, color) tuples
    """
    # Flatten to 1D row-major order
    flat = bitmap.flatten()

    rle = []
    current_color = flat[0]
    count = 1

    for pixel in flat[1:]:
        if pixel == current_color and count < 255:
            count += 1
        else:
            rle.append((count, current_color))
            current_color = pixel
            count = 1

    # Add last run
    rle.append((count, current_color))

    # Add end marker
    rle.append((0, 0))

    return rle


def generate_c_header(slice_data: List[dict]) -> str:
    """
    Generate C header file with PROGMEM bitmap arrays.

    Args:
        slice_data: List of dicts with 'name', 'rle', 'original_size', 'compressed_size', 'lon_range'

    Returns:
        C header file content as string
    """
    lines = [
        "/**",
        " * Auto-generated world map bitmaps for RadioWall ESP32",
        " *",
        " * Generated from Natural Earth 1:110m coastline data (public domain)",
        " * https://www.naturalearthdata.com/",
        " *",
        " * Format: RLE-compressed 160×560 bitmaps (byte pairs: [count, color])",
        " * Color: 0 = black (ocean), 1 = white (land)",
        " *",
        " * DO NOT EDIT - Regenerate with tools/generate_map_bitmaps.py",
        " */",
        "",
        "#ifndef WORLD_MAP_DATA_H",
        "#define WORLD_MAP_DATA_H",
        "",
        "#include <Arduino.h>",
        "",
    ]

    # Generate arrays for each longitude slice
    for slice_item in slice_data:
        name = slice_item["name"]
        rle = slice_item["rle"]
        original_size = slice_item["original_size"]
        compressed_size = slice_item["compressed_size"]
        compression_ratio = original_size / compressed_size

        lines.append(f"// {slice_item['label']} ({slice_item['lon_range']})")
        lines.append(f"// Original: {original_size} bytes, Compressed: {compressed_size} bytes "
                     f"({compression_ratio:.1f}x compression)")
        lines.append(f"const uint8_t map_slice_{name}[] PROGMEM = {{")

        # Format RLE data (16 bytes per line for readability)
        for i in range(0, len(rle), 8):
            chunk = rle[i:i + 8]
            formatted = ", ".join(f"{count}, {color}" for count, color in chunk)
            lines.append(f"    {formatted},")

        lines.append("};")
        lines.append(f"const size_t map_slice_{name}_size = sizeof(map_slice_{name});")
        lines.append("")

    lines.append("#endif // WORLD_MAP_DATA_H")
    lines.append("")

    return "\n".join(lines)


def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   RadioWall Map Bitmap Generator                          ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()

    # Download/load Natural Earth data
    try:
        shapefile_path = download_natural_earth_data()
    except Exception as e:
        print(f"✗ Error downloading Natural Earth data: {e}")
        print("\nYou can manually download from:")
        print(NATURAL_EARTH_URL)
        print(f"Extract to: {DATA_DIR}")
        sys.exit(1)

    # Load coastlines
    print("Loading coastline geometries...")
    coastlines = gpd.read_file(shapefile_path)
    print(f"✓ Loaded {len(coastlines)} coastline segments")
    print()

    # Generate bitmaps for each longitude slice
    slice_data = []

    for slice_def in LONGITUDE_SLICES:
        print(f"Rendering {slice_def['label']} ({slice_def['lon_range']})...")

        # Render bitmap
        bitmap = render_longitude_slice(coastlines, slice_def["lon_min"], slice_def["lon_max"])

        # RLE compress
        rle = rle_compress(bitmap)

        original_size = MAP_WIDTH * MAP_HEIGHT  # bytes (1 bit per pixel → 1 byte per pixel uncompressed)
        compressed_size = len(rle) * 2  # bytes (count + color pairs)
        compression_ratio = original_size / compressed_size

        print(f"  ✓ Bitmap: {MAP_WIDTH}×{MAP_HEIGHT} = {original_size} bytes")
        print(f"  ✓ RLE compressed: {len(rle)} runs = {compressed_size} bytes "
              f"({compression_ratio:.1f}x compression)")

        slice_data.append({
            "name": slice_def["name"],
            "label": slice_def["label"],
            "lon_range": slice_def["lon_range"],
            "rle": rle,
            "original_size": original_size,
            "compressed_size": compressed_size,
        })
        print()

    # Generate C header
    print(f"Generating C header: {OUTPUT_HEADER}")
    header_content = generate_c_header(slice_data)

    OUTPUT_HEADER.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HEADER, "w") as f:
        f.write(header_content)

    total_compressed = sum(s["compressed_size"] for s in slice_data)
    print(f"✓ Generated {OUTPUT_HEADER}")
    print(f"✓ Total size: {total_compressed} bytes ({total_compressed / 1024:.1f} KB)")
    print()
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   SUCCESS! Map bitmaps generated.                         ║")
    print("║   Next step: Rebuild ESP32 firmware (pio run)             ║")
    print("╚════════════════════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
