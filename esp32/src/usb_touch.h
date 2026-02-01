#ifndef USB_TOUCH_H
#define USB_TOUCH_H

#include <Arduino.h>

// Callback type for touch events
typedef void (*TouchCallback)(int x, int y);

void usb_touch_init();
void usb_touch_set_callback(TouchCallback cb);
void usb_touch_task();

#endif // USB_TOUCH_H
