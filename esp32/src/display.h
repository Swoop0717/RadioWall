/**
 * AMOLED display control for RadioWall on T-Display-S3-Long.
 * Uses Arduino_GFX library with AXS15231B driver.
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>
#include "Arduino_GFX_Library.h"

void display_init();
void display_loop();
void display_show_nowplaying(const char* station, const char* location, const char* country);
void display_show_status(const char* status);
void display_show_connecting();
void display_wake();
void display_draw_touch_feedback(int x, int y);

// Get GFX instance
Arduino_GFX* display_get_gfx();

#endif // DISPLAY_H
