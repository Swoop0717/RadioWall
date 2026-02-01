/**
 * USB Host HID touch panel reading for RadioWall.
 *
 * Reads touch coordinates from a USB capacitive touch panel connected
 * via USB-C OTG. The touch panel appears as a standard HID device.
 *
 * NOTE: ESP32-S3 USB Host support is still maturing. This uses the
 * esp_tinyusb library. You may need to adjust the HID report parsing
 * based on your specific touch controller (GT911, Goodix, etc.).
 */

#include "usb_touch.h"
#include "config.h"

#include <USB.h>
#include <USBHIDMouse.h>

static TouchCallback _touch_callback = nullptr;
static unsigned long _last_touch_ms = 0;
static bool _initialized = false;

// HID report buffer
static uint8_t _report_buf[64];

void usb_touch_init() {
    Serial.println("[Touch] Initializing USB Host for touch panel...");

    // Enable OTG mode on T-Display-S3-Long
    // The SY6970 PMU needs OTG enabled for USB Host
    // Note: actual OTG init depends on board variant and PMU library
    USB.begin();

    _initialized = true;
    Serial.println("[Touch] USB Host initialized");
}

void usb_touch_set_callback(TouchCallback cb) {
    _touch_callback = cb;
}

void usb_touch_task() {
    if (!_initialized) return;

    // TODO: Full USB Host HID implementation
    //
    // The complete implementation requires:
    // 1. USB Host stack initialization (tinyusb host mode)
    // 2. HID device enumeration and connection
    // 3. Parsing HID touch reports (format depends on controller)
    //
    // Typical HID touch report structure:
    //   Byte 0: Report ID
    //   Byte 1: Contact count / touch status
    //   Byte 2-3: X coordinate (little-endian)
    //   Byte 4-5: Y coordinate (little-endian)
    //
    // For now, this is a skeleton that will be completed once
    // the USB-C OTG adapter arrives and the actual HID descriptor
    // can be inspected.
    //
    // To test without hardware, use Serial commands:
    //   Send "T:512,300" over serial to simulate a touch at (512, 300)

    // Serial simulation for development
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();

        if (line.startsWith("T:")) {
            int comma = line.indexOf(',', 2);
            if (comma > 0) {
                int x = line.substring(2, comma).toInt();
                int y = line.substring(comma + 1).toInt();

                // Debounce
                unsigned long now = millis();
                if (now - _last_touch_ms < TOUCH_DEBOUNCE_MS) return;
                _last_touch_ms = now;

                Serial.printf("[Touch] Touch at (%d, %d)\n", x, y);
                if (_touch_callback) {
                    _touch_callback(x, y);
                }
            }
        }
    }
}
