/**
 * Built-in touchscreen input for RadioWall (T-Display-S3-Long).
 *
 * Reads touch coordinates from the built-in AMOLED capacitive touchscreen
 * (640×180) with zone-based handling:
 * - Map area (y < 150): Coordinates translated based on current latitude band
 * - Status bar (y >= 150): Button detection (stop/next)
 */

#ifndef BUILTIN_TOUCH_H
#define BUILTIN_TOUCH_H

#include <Arduino.h>

// Forward declaration
class UIState;

// Legacy callback (deprecated - use zone-based callbacks instead)
typedef void (*TouchCallback)(int x, int y);

// Zone-based callbacks
typedef void (*MapTouchCallback)(int map_x, int map_y);  // Map coordinates (1024×600)
typedef void (*UIButtonCallback)(int button_id);          // 0=stop, 1=next

void builtin_touch_init();
void builtin_touch_task();

// Legacy callback (deprecated)
void builtin_touch_set_callback(TouchCallback cb);

// Zone-based callbacks
void builtin_touch_set_map_callback(MapTouchCallback cb);
void builtin_touch_set_ui_button_callback(UIButtonCallback cb);
void builtin_touch_set_ui_state(UIState* state);  // For coordinate translation

#endif // BUILTIN_TOUCH_H
