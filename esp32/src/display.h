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

void display_wake();
void display_draw_touch_feedback(int x, int y, UIState* state);

// Get GFX instance
Arduino_GFX* display_get_gfx();

#endif // DISPLAY_H
