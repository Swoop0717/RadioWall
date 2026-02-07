#!/usr/bin/env python3
"""
Generate RLE-compressed world map bitmaps for RadioWall ESP32.

Downloads Natural Earth 1:110m data and renders:
  - 4 base (1x) map slices with country borders -> PROGMEM C header
  - 16 zoomed (2x) sub-maps -> LittleFS binary file
  - 36 zoomed (3x) sub-maps -> LittleFS binary file

3-Color RLE format: 0=ocean (black), 1=land (white), 2=border (gray)

Output:
  ../esp32/src/world_map_data.h   (1x PROGMEM arrays)
  ../esp32/data/maps/zoom2.bin    (2x LittleFS binary)
  ../esp32/data/maps/zoom3.bin    (3x LittleFS binary)

Usage:
    python generate_map_bitmaps.py

Requirements:
    pip install geopandas matplotlib numpy Pillow requests
"""

import io
import os
import struct
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import requests
from PIL import Image


# Map dimensions (portrait: 180 wide x 580 tall - fills display above status bar)
MAP_WIDTH = 180
MAP_HEIGHT = 580

# Longitude slices (vertical slices of the world)
LONGITUDE_SLICES = [
    {"name": "americas", "label": "Americas", "lon_range": "-150deg to -30deg", "lon_min": -150.0, "lon_max": -30.0},
    {"name": "europe_africa", "label": "Europe/Africa", "lon_range": "-30deg to 60deg", "lon_min": -30.0, "lon_max": 60.0},
    {"name": "asia", "label": "Asia", "lon_range": "60deg to 150deg", "lon_min": 60.0, "lon_max": 150.0},
    {"name": "pacific", "label": "Pacific", "lon_range": "150deg to -150deg", "lon_min": 150.0, "lon_max": -150.0},
]

# Zoom levels to generate (1x is always generated as PROGMEM)
ZOOM_LEVELS = [2, 3]

# Natural Earth data URLs (1:110m resolution, public domain)
NE_COUNTRIES_URL = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
NE_BORDERS_URL = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_boundary_lines_land.zip"

# Output paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_HEADER = SCRIPT_DIR.parent / "esp32" / "src" / "world_map_data.h"
OUTPUT_MAPS_DIR = SCRIPT_DIR.parent / "esp32" / "data" / "maps"


def download_and_extract(url: str, name: str) -> Path:
    """Download and extract a Natural Earth shapefile."""
    DATA_DIR.mkdir(exist_ok=True)

    # Derive shapefile name from URL
    zip_name = url.rsplit("/", 1)[-1]
    shp_name = zip_name.replace(".zip", ".shp")
    shapefile_path = DATA_DIR / shp_name

    if shapefile_path.exists():
        print(f"  [OK] Using cached {name}: {shapefile_path.name}")
        return shapefile_path

    print(f"  Downloading {name}...")
    zip_path = DATA_DIR / zip_name

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"  [OK] Downloaded {zip_path.stat().st_size / 1024:.1f} KB")

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(DATA_DIR)

    print(f"  [OK] Extracted to {DATA_DIR}")
    return shapefile_path


def render_region(countries: gpd.GeoDataFrame, borders: gpd.GeoDataFrame,
                  lon_min: float, lon_max: float,
                  lat_min: float, lat_max: float) -> np.ndarray:
    """
    Render a geographic region to a 3-color bitmap.

    Rendering pipeline:
      1. Black background (ocean)
      2. Fill country polygons white (land)
      3. Draw border lines gray (country boundaries)

    Args:
        countries: Country polygon GeoDataFrame
        borders: Border line GeoDataFrame
        lon_min, lon_max: Longitude bounds
        lat_min, lat_max: Latitude bounds

    Returns:
        numpy array (MAP_HEIGHT x MAP_WIDTH) with values 0, 1, or 2
    """
    dpi = 100

    def render_half(lmin, lmax, width_px):
        """Render a longitude range to a grayscale image."""
        fig = plt.figure(figsize=(width_px / dpi, MAP_HEIGHT / dpi), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(lmin, lmax)
        ax.set_ylim(lat_min, lat_max)
        ax.axis("off")
        ax.set_facecolor("black")

        # Layer 1: Fill country polygons white (land)
        countries.plot(ax=ax, facecolor="white", edgecolor="none", linewidth=0)

        # Layer 2: Draw country borders as gray
        borders.plot(ax=ax, color="#A0A0A0", linewidth=0.8)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0,
                    facecolor="black")
        plt.close(fig)
        buf.seek(0)
        return Image.open(buf).convert("L").resize((width_px, MAP_HEIGHT), Image.Resampling.LANCZOS)

    if lon_max < lon_min:
        # Wrapping case (e.g. Pacific: 150deg to -150deg across dateline)
        total_span = (lon_max + 360.0) - lon_min
        left_span = 180.0 - lon_min
        right_span = lon_max + 180.0

        left_px = max(1, int(round(MAP_WIDTH * left_span / total_span)))
        right_px = MAP_WIDTH - left_px

        img_l = render_half(lon_min, 180, left_px)
        img_r = render_half(-180, lon_max, right_px)

        img = Image.new("L", (MAP_WIDTH, MAP_HEIGHT), 0)
        img.paste(img_l, (0, 0))
        img.paste(img_r, (left_px, 0))
    else:
        img = render_half(lon_min, lon_max, MAP_WIDTH)

    # Convert to 3-color: ocean=0, land=1, border=2
    pixels = np.array(img)

    result = np.zeros_like(pixels, dtype=np.uint8)
    result[pixels > 200] = 1   # Bright white = land
    result[(pixels > 60) & (pixels <= 200)] = 2  # Gray = border
    # pixels <= 60 stays 0 = ocean (black)

    return result


def rle_compress(bitmap: np.ndarray) -> List[Tuple[int, int]]:
    """
    Run-Length Encode a bitmap with values 0, 1, or 2.

    Returns:
        List of (count, color) tuples, ending with (0, 0) marker
    """
    flat = bitmap.flatten()

    rle = []
    current_color = int(flat[0])
    count = 1

    for pixel in flat[1:]:
        pixel = int(pixel)
        if pixel == current_color and count < 255:
            count += 1
        else:
            rle.append((count, current_color))
            current_color = pixel
            count = 1

    rle.append((count, current_color))
    rle.append((0, 0))  # End marker

    return rle


def generate_c_header(slice_data: List[dict]) -> str:
    """Generate C header file with PROGMEM bitmap arrays (1x zoom)."""
    lines = [
        "/**",
        " * Auto-generated world map bitmaps for RadioWall ESP32",
        " *",
        " * Generated from Natural Earth 1:110m data (public domain)",
        " * https://www.naturalearthdata.com/",
        " *",
        " * Format: RLE-compressed 180x580 bitmaps (byte pairs: [count, color])",
        " * Color: 0 = black (ocean), 1 = white (land), 2 = gray (border)",
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

    for s in slice_data:
        name = s["name"]
        rle = s["rle"]
        original_size = s["original_size"]
        compressed_size = s["compressed_size"]
        ratio = original_size / compressed_size

        lines.append(f"// {s['label']} ({s['lon_range']})")
        lines.append(f"// Original: {original_size} bytes, Compressed: {compressed_size} bytes "
                     f"({ratio:.1f}x compression)")
        lines.append(f"const uint8_t map_slice_{name}[] PROGMEM = {{")

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


def generate_zoom_binary(zoom_level: int, all_slice_bitmaps: List[List[List[bytes]]]) -> bytes:
    """
    Pack zoom sub-map bitmaps into a LittleFS binary file.

    File format:
      Header (8 bytes): magic('Z','M'), version(1), zoom, slices(4), cols, rows, reserved(0)
      Index (6 bytes per bitmap): offset(uint32), size(uint16) -- ordered slice->col->row
      Data: concatenated RLE bytes

    Args:
        zoom_level: 2 or 3
        all_slice_bitmaps: [slice_idx][col][row] -> RLE bytes

    Returns:
        Complete binary file content
    """
    num_slices = 4
    cols = zoom_level
    rows = zoom_level
    num_bitmaps = num_slices * cols * rows

    # Header
    header = struct.pack("BBBBBBBB",
                         ord('Z'), ord('M'),  # magic
                         1,                     # version
                         zoom_level,            # zoom
                         num_slices,            # slices
                         cols,                  # cols per slice
                         rows,                  # rows per slice
                         0)                     # reserved

    index_size = num_bitmaps * 6  # 4 bytes offset + 2 bytes size per entry
    data_start = len(header) + index_size

    # Build data section and index
    index_entries = []
    data_chunks = []
    current_offset = data_start

    for slice_idx in range(num_slices):
        for col in range(cols):
            for row in range(rows):
                rle_bytes = all_slice_bitmaps[slice_idx][col][row]
                index_entries.append(struct.pack("<IH", current_offset, len(rle_bytes)))
                data_chunks.append(rle_bytes)
                current_offset += len(rle_bytes)

    return header + b"".join(index_entries) + b"".join(data_chunks)


def get_sub_bounds(slice_def: dict, zoom: int, col: int, row: int):
    """Calculate geographic bounds for a zoom sub-map."""
    lon_min = slice_def["lon_min"]
    lon_max = slice_def["lon_max"]

    lon_range = lon_max - lon_min
    if lon_range < 0:
        lon_range += 360.0

    sub_lon_range = lon_range / zoom
    sub_lon_min = lon_min + col * sub_lon_range
    sub_lon_max = sub_lon_min + sub_lon_range

    # Normalize to [-180, 180]
    if sub_lon_min > 180:
        sub_lon_min -= 360
    if sub_lon_max > 180:
        sub_lon_max -= 360

    lat_range = 180.0 / zoom
    sub_lat_max = 90.0 - row * lat_range
    sub_lat_min = sub_lat_max - lat_range

    return sub_lon_min, sub_lon_max, sub_lat_min, sub_lat_max


def main():
    print("=" * 62)
    print("   RadioWall Map Bitmap Generator")
    print("   (with country borders + zoom levels)")
    print("=" * 62)
    print()

    # Download Natural Earth data
    print("Loading Natural Earth data...")
    try:
        countries_path = download_and_extract(NE_COUNTRIES_URL, "country polygons")
        borders_path = download_and_extract(NE_BORDERS_URL, "border lines")
    except Exception as e:
        print(f"[ERROR] Error downloading Natural Earth data: {e}")
        sys.exit(1)

    print()
    print("Loading geometries...")
    countries = gpd.read_file(countries_path)
    borders = gpd.read_file(borders_path)
    print(f"[OK] Loaded {len(countries)} countries, {len(borders)} border segments")
    print()

    # -- 1x bitmaps (PROGMEM) --------------------------------------
    print("-" * 50)
    print("  Generating 1x base maps (PROGMEM)")
    print("-" * 50)

    slice_data = []

    for slice_def in LONGITUDE_SLICES:
        print(f"\nRendering {slice_def['label']} ({slice_def['lon_range']})...")

        bitmap = render_region(countries, borders,
                               slice_def["lon_min"], slice_def["lon_max"],
                               -90.0, 90.0)
        rle = rle_compress(bitmap)

        original_size = MAP_WIDTH * MAP_HEIGHT
        compressed_size = len(rle) * 2
        ratio = original_size / compressed_size

        print(f"  [OK] {MAP_WIDTH}x{MAP_HEIGHT} = {original_size} bytes")
        print(f"  [OK] RLE: {len(rle)} runs = {compressed_size} bytes ({ratio:.1f}x)")

        slice_data.append({
            "name": slice_def["name"],
            "label": slice_def["label"],
            "lon_range": slice_def["lon_range"],
            "rle": rle,
            "original_size": original_size,
            "compressed_size": compressed_size,
        })

    # Write C header
    print(f"\nGenerating C header: {OUTPUT_HEADER}")
    header_content = generate_c_header(slice_data)

    OUTPUT_HEADER.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HEADER, "w") as f:
        f.write(header_content)

    total_1x = sum(s["compressed_size"] for s in slice_data)
    print(f"[OK] 1x total: {total_1x} bytes ({total_1x / 1024:.1f} KB)")

    # -- Zoom bitmaps (LittleFS) -----------------------------------
    OUTPUT_MAPS_DIR.mkdir(parents=True, exist_ok=True)

    for zoom in ZOOM_LEVELS:
        print()
        print("-" * 50)
        print(f"  Generating {zoom}x zoom maps (LittleFS)")
        print(f"  {4 * zoom * zoom} sub-maps ({zoom}x{zoom} grid per slice)")
        print("-" * 50)

        all_slice_bitmaps = []  # [slice][col][row] -> rle bytes
        total_bytes = 0

        for s_idx, slice_def in enumerate(LONGITUDE_SLICES):
            slice_bitmaps = []
            for col in range(zoom):
                col_bitmaps = []
                for row in range(zoom):
                    sub_lon_min, sub_lon_max, sub_lat_min, sub_lat_max = \
                        get_sub_bounds(slice_def, zoom, col, row)

                    label = f"{slice_def['label']} [{col},{row}]"
                    print(f"  {label}: lon({sub_lon_min:.0f}..{sub_lon_max:.0f}) "
                          f"lat({sub_lat_min:.0f}..{sub_lat_max:.0f})", end="")

                    bitmap = render_region(countries, borders,
                                           sub_lon_min, sub_lon_max,
                                           sub_lat_min, sub_lat_max)
                    rle = rle_compress(bitmap)

                    # Convert RLE tuples to raw bytes
                    rle_bytes = bytes()
                    for count, color in rle:
                        rle_bytes += bytes([count, color])

                    total_bytes += len(rle_bytes)
                    print(f" -> {len(rle_bytes)} bytes")

                    col_bitmaps.append(rle_bytes)
                slice_bitmaps.append(col_bitmaps)
            all_slice_bitmaps.append(slice_bitmaps)

        # Write binary file
        bin_data = generate_zoom_binary(zoom, all_slice_bitmaps)
        out_path = OUTPUT_MAPS_DIR / f"zoom{zoom}.bin"
        with open(out_path, "wb") as f:
            f.write(bin_data)

        print(f"\n[OK] {zoom}x: {len(bin_data)} bytes ({len(bin_data) / 1024:.1f} KB) -> {out_path}")

    # -- Summary ---------------------------------------------------
    print()
    print("=" * 60)
    print("  SUCCESS! All map bitmaps generated.")
    print()
    print(f"  1x PROGMEM: {total_1x / 1024:6.1f} KB  (world_map_data.h)")
    for zoom in ZOOM_LEVELS:
        p = OUTPUT_MAPS_DIR / f"zoom{zoom}.bin"
        if p.exists():
            sz = p.stat().st_size
            print(f"  {zoom}x LittleFS: {sz / 1024:5.1f} KB  (data/maps/zoom{zoom}.bin)")
    print()
    print("  Next steps:")
    print("    pio run                  (rebuild firmware)")
    print("    pio run -t uploadfs      (upload LittleFS)")
    print("=" * 60)


if __name__ == "__main__":
    main()
