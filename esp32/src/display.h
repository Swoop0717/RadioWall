/**
 * AMOLED display control for RadioWall on T-Display-S3-Long.
 * Uses Arduino_GFX library with AXS15231B driver.
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>
#include "Arduino_GFX_Library.h"

// Forward declaration
class UIState;

void display_init();
void display_loop();

// Legacy functions (deprecated - use map view instead)
void display_show_nowplaying(const char* station, const char* location, const char* country);
void display_show_status(const char* status);
void display_show_connecting();

// Map view functions
void display_show_map_view(UIState* state);         // Full redraw
void display_update_status_bar(UIState* state);     // Status bar only
void display_refresh_map_only(UIState* state);      // Map area only

// Menu view functions
void display_show_menu_view(UIState* state);
void display_update_status_bar_menu(UIState* state);

// Volume view functions
void display_show_volume_view(UIState* state);
void display_update_volume_bar(UIState* state);

// Favorites view functions
void display_show_favorites_view(UIState* state);

// Map marker at lat/lon (converts to portrait coords using current slice)
void display_draw_marker_at_latlon(float lat, float lon, UIState* state);

void display_wake();
void display_draw_touch_feedback(int x, int y, UIState* state);

// Get GFX instance
Arduino_GFX* display_get_gfx();

#endif // DISPLAY_H
