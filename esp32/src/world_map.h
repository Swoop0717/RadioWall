/**
 * World Map Rendering for RadioWall
 *
 * Stores longitude slice bitmaps and provides drawing functions.
 * Bitmaps are RLE-compressed and stored in PROGMEM (flash).
 */

#ifndef WORLD_MAP_H
#define WORLD_MAP_H

#include <Arduino.h>
#include "Arduino_GFX_Library.h"

// Map dimensions (portrait: 180×580, fills display above status bar)
#define MAP_WIDTH 180
#define MAP_HEIGHT 580

// Bitmap data (PROGMEM arrays, defined in world_map.cpp)
extern const uint8_t map_slice_americas[];
extern const size_t map_slice_americas_size;

extern const uint8_t map_slice_europe_africa[];
extern const size_t map_slice_europe_africa_size;

extern const uint8_t map_slice_asia[];
extern const size_t map_slice_asia_size;

extern const uint8_t map_slice_pacific[];
extern const size_t map_slice_pacific_size;

// Drawing functions
void draw_map_slice(Arduino_GFX* gfx, const uint8_t* rle_data, size_t size, int offset_x, int offset_y);
void draw_slice_label(Arduino_GFX* gfx, const char* name, const char* label);

#endif // WORLD_MAP_H
