/**
 * Built-in touchscreen input for RadioWall (T-Display-S3-Long).
 *
 * Reads touch coordinates from the built-in AMOLED capacitive touchscreen
 * (640×180) and maps them to the expected touch panel coordinate space
 * (1024×600).
 *
 * This is a temporary solution for testing while waiting for the USB touch
 * panel hardware (OTG adapter). The API matches usb_touch.h for easy switching
 * via the USE_BUILTIN_TOUCH compile flag.
 */

#ifndef BUILTIN_TOUCH_H
#define BUILTIN_TOUCH_H

#include <Arduino.h>

// Callback type (same as usb_touch.h for compatibility)
typedef void (*TouchCallback)(int x, int y);

void builtin_touch_init();
void builtin_touch_set_callback(TouchCallback cb);
void builtin_touch_task();

#endif // BUILTIN_TOUCH_H
