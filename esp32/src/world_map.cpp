/**
 * World Map Rendering Implementation
 *
 * RLE Format: Byte pairs [count, color]
 * - count: Number of pixels
 * - color: 0 = black (ocean), 1 = white (land), 2 = gray (border)
 *
 * 1x maps: stored in PROGMEM (world_map_data.h)
 * 2x/3x maps: stored in LittleFS (/maps/zoom2.bin, /maps/zoom3.bin)
 */

#include "world_map.h"
#include <LittleFS.h>

// Real map data generated from Natural Earth
#include "world_map_data.h"

// 3-color mapping: ocean=black, land=white, border=gray
static inline uint16_t rle_color(uint8_t c) {
    if (c == 0) return BLACK;
    if (c == 2) return 0x8410;  // Mid gray for borders
    return WHITE;               // Land
}

/**
 * Draw RLE-compressed map bitmap from PROGMEM at specified position
 */
void draw_map_slice(Arduino_GFX* gfx, const uint8_t* rle_data, size_t size, int offset_x, int offset_y) {
    unsigned long start = millis();

    int x = 0, y = 0;
    size_t idx = 0;

    while (idx < size - 1) {
        uint8_t count = pgm_read_byte(&rle_data[idx++]);
        uint8_t color = pgm_read_byte(&rle_data[idx++]);

        if (count == 0 && color == 0) break;

        uint16_t display_color = rle_color(color);
        int remaining = count;

        while (remaining > 0 && y < MAP_HEIGHT) {
            int pixels_this_row = min(remaining, MAP_WIDTH - x);
            gfx->drawFastHLine(offset_x + x, offset_y + y, pixels_this_row, display_color);
            remaining -= pixels_this_row;
            x += pixels_this_row;
            if (x >= MAP_WIDTH) { x = 0; y++; }
        }

        if (y >= MAP_HEIGHT) break;
    }

    // Fill remainder with black
    while (y < MAP_HEIGHT) {
        if (x < MAP_WIDTH) {
            gfx->drawFastHLine(offset_x + x, offset_y + y, MAP_WIDTH - x, BLACK);
        }
        x = 0;
        y++;
    }

    Serial.printf("[WorldMap] Map drawn in %lu ms\n", millis() - start);
}

/**
 * Draw RLE-compressed map bitmap from a LittleFS zoom binary file.
 *
 * File format:
 *   Header (8 bytes): 'Z','M', version, zoom, slices, cols, rows, reserved
 *   Index (6 bytes per bitmap): offset(uint32_le), size(uint16_le)
 *   Data: RLE bytes
 *
 * Bitmap index = slice * cols * rows + col * rows + row
 */
bool draw_map_from_file(Arduino_GFX* gfx, const char* path,
                        int zoom_level, int slice_idx, int col, int row,
                        int offset_x, int offset_y) {
    unsigned long start = millis();

    File f = LittleFS.open(path, "r");
    if (!f) {
        Serial.printf("[WorldMap] Failed to open %s\n", path);
        return false;
    }

    // Read and validate header
    uint8_t header[8];
    if (f.read(header, 8) != 8 || header[0] != 'Z' || header[1] != 'M') {
        Serial.println("[WorldMap] Invalid zoom file header");
        f.close();
        return false;
    }

    int file_zoom = header[3];
    int file_cols = header[5];
    int file_rows = header[6];

    if (file_zoom != zoom_level) {
        Serial.printf("[WorldMap] Zoom mismatch: file=%d, expected=%d\n", file_zoom, zoom_level);
        f.close();
        return false;
    }

    // Calculate bitmap index
    int bitmap_idx = slice_idx * file_cols * file_rows + col * file_rows + row;
    int index_offset = 8 + bitmap_idx * 6;

    // Read index entry
    f.seek(index_offset);
    uint8_t idx_buf[6];
    if (f.read(idx_buf, 6) != 6) {
        Serial.println("[WorldMap] Failed to read index entry");
        f.close();
        return false;
    }

    uint32_t data_offset = idx_buf[0] | (idx_buf[1] << 8) | (idx_buf[2] << 16) | (idx_buf[3] << 24);
    uint16_t data_size = idx_buf[4] | (idx_buf[5] << 8);

    // Seek to bitmap data and draw
    f.seek(data_offset);

    int x = 0, y = 0;
    uint16_t bytes_read = 0;

    while (bytes_read < data_size - 1 && y < MAP_HEIGHT) {
        uint8_t count = f.read();
        uint8_t color = f.read();
        bytes_read += 2;

        if (count == 0 && color == 0) break;

        uint16_t display_color = rle_color(color);
        int remaining = count;

        while (remaining > 0 && y < MAP_HEIGHT) {
            int pixels_this_row = min(remaining, MAP_WIDTH - x);
            gfx->drawFastHLine(offset_x + x, offset_y + y, pixels_this_row, display_color);
            remaining -= pixels_this_row;
            x += pixels_this_row;
            if (x >= MAP_WIDTH) { x = 0; y++; }
        }
    }

    // Fill remainder with black
    while (y < MAP_HEIGHT) {
        if (x < MAP_WIDTH) {
            gfx->drawFastHLine(offset_x + x, offset_y + y, MAP_WIDTH - x, BLACK);
        }
        x = 0;
        y++;
    }

    f.close();
    Serial.printf("[WorldMap] Zoom %dx [%d,%d] drawn in %lu ms\n",
                  zoom_level, col, row, millis() - start);
    return true;
}

/**
 * Draw slice label in corner
 */
void draw_slice_label(Arduino_GFX* gfx, const char* name, const char* label) {
    gfx->setTextSize(1);
    gfx->setTextColor(CYAN, BLACK);
    gfx->setCursor(5, 5);
    gfx->print(name);
    gfx->setCursor(5, 15);
    gfx->print(label);
}
