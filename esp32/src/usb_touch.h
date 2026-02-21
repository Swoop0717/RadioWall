#ifndef USB_TOUCH_H
#define USB_TOUCH_H

#include <Arduino.h>

// Forward declaration
class UIState;

// Callback types (same as builtin_touch.h for compatibility)
typedef void (*MapTouchCallback)(int map_x, int map_y);
typedef void (*UIButtonCallback)(int button_id);
typedef void (*MenuTouchCallback)(int portrait_x, int portrait_y);
typedef void (*SwipeCallback)(int direction);
typedef void (*VolumeChangeCallback)(int volume);
typedef void (*MapDoubleTapCallback)(int portrait_x, int portrait_y);

// Initialize USB Host, PMU OTG, and HID touch driver
// Call AFTER WiFi is connected (needs WiFi for UDP logging)
void usb_touch_init();

// Process USB events and touch reports (call from loop())
void usb_touch_task();

// Callback setters (mirror builtin_touch API)
void usb_touch_set_map_callback(MapTouchCallback cb);
void usb_touch_set_ui_button_callback(UIButtonCallback cb);
void usb_touch_set_menu_callback(MenuTouchCallback cb);
void usb_touch_set_swipe_callback(SwipeCallback cb);
void usb_touch_set_volume_change_callback(VolumeChangeCallback cb);
void usb_touch_set_map_double_tap_callback(MapDoubleTapCallback cb);
void usb_touch_set_ui_state(UIState* state);

#endif // USB_TOUCH_H
