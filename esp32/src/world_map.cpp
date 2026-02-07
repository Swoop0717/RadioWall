/**
 * World Map Rendering Implementation
 *
 * RLE Format: Byte pairs [count, color]
 * - count: Number of pixels
 * - color: 0 = black (ocean), 1 = white (land)
 *
 * IMPORTANT: To use real map data instead of test patterns:
 * 1. Install Python dependencies: pip install -r ../tools/requirements.txt
 * 2. Generate map bitmaps: python ../tools/generate_map_bitmaps.py
 * 3. Uncomment the include below and comment out the stub patterns
 */

#include "world_map.h"

// Real map data generated from Natural Earth coastlines
#include "world_map_data.h"

// Stub test patterns disabled (using real map data now)
#if 0  // Stub test patterns (will be replaced by real coastline data)
// Format: RLE compressed (count, color pairs)
// These patterns are VERY distinct to make slice changes obvious

// Test pattern 1: Wide vertical stripes (Americas)
const uint8_t map_slice_americas[] PROGMEM = {
    100, 1,  // 100 white pixels (wide stripe)
    100, 0,  // 100 black pixels (wide stripe)
    0, 0     // End marker
};
const size_t map_slice_americas_size = sizeof(map_slice_americas);

// Test pattern 2: Small checkerboard (Europe/Africa) - DEFAULT SLICE
const uint8_t map_slice_europe_africa[] PROGMEM = {
    20, 1, 20, 0,  // Medium alternating pattern
    0, 0
};
const size_t map_slice_europe_africa_size = sizeof(map_slice_europe_africa);

// Test pattern 3: Large checkerboard blocks (Asia)
const uint8_t map_slice_asia[] PROGMEM = {
    50, 1, 50, 0,  // Large alternating blocks
    0, 0
};
const size_t map_slice_asia_size = sizeof(map_slice_asia);

// Test pattern 4: Sparse dots (Pacific)
const uint8_t map_slice_pacific[] PROGMEM = {
    3, 1, 30, 0,  // Small dots with lots of space
    0, 0
};
const size_t map_slice_pacific_size = sizeof(map_slice_pacific);
#endif  // End of stub patterns

/**
 * Draw RLE-compressed map bitmap at specified position
 *
 * OPTIMIZED: Uses drawFastHLine() instead of drawPixel() for much faster rendering.
 * Draws horizontal line segments for each RLE run, splitting across rows as needed.
 *
 * @param gfx Display object
 * @param rle_data Pointer to PROGMEM RLE data
 * @param size Size of RLE data in bytes
 * @param offset_x X offset on display
 * @param offset_y Y offset on display
 */
void draw_map_slice(Arduino_GFX* gfx, const uint8_t* rle_data, size_t size, int offset_x, int offset_y) {
    unsigned long start = millis();

    int x = 0, y = 0;
    size_t idx = 0;

    while (idx < size - 1) {
        uint8_t count = pgm_read_byte(&rle_data[idx++]);
        uint8_t color = pgm_read_byte(&rle_data[idx++]);

        // End marker
        if (count == 0 && color == 0) {
            break;
        }

        uint16_t display_color = color ? WHITE : BLACK;
        int remaining = count;

        // Draw horizontal lines, splitting across rows as needed
        while (remaining > 0 && y < MAP_HEIGHT) {
            int pixels_this_row = min(remaining, MAP_WIDTH - x);

            // Draw horizontal line segment
            gfx->drawFastHLine(offset_x + x, offset_y + y, pixels_this_row, display_color);

            remaining -= pixels_this_row;
            x += pixels_this_row;

            if (x >= MAP_WIDTH) {
                x = 0;
                y++;
            }
        }

        if (y >= MAP_HEIGHT) break;
    }

    // Fill remainder with black (ocean) using fast horizontal lines
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
 * Draw slice label in corner
 *
 * @param gfx Display object
 * @param name Slice name (e.g., "Europe/Africa")
 * @param label Slice longitude range (e.g., "-30° to 60°")
 */
void draw_slice_label(Arduino_GFX* gfx, const char* name, const char* label) {
    // Draw label in top-left corner (portrait mode)
    gfx->setTextSize(1);
    gfx->setTextColor(CYAN, BLACK);

    // Slice name
    gfx->setCursor(5, 5);
    gfx->print(name);

    // Longitude range
    gfx->setCursor(5, 15);
    gfx->print(label);
}
