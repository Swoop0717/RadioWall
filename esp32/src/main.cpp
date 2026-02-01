/**
 * RadioWall ESP32 Firmware - Main Entry Point
 *
 * T-Display-S3-Long reads touch coordinates from a USB capacitive touch
 * panel, publishes them via MQTT, and displays "Now Playing" info on
 * the built-in AMOLED screen.
 */

#include <Arduino.h>
#include "config.h"

// Conditional compilation: built-in touch vs USB touch panel
#if USE_BUILTIN_TOUCH
  #include "builtin_touch.h"
  #define touch_init    builtin_touch_init
  #define touch_task    builtin_touch_task
  #define touch_set_callback builtin_touch_set_callback
#else
  #include "usb_touch.h"
  #define touch_init    usb_touch_init
  #define touch_task    usb_touch_task
  #define touch_set_callback usb_touch_set_callback
#endif

#include "mqtt_client.h"
#include "display.h"

// ------------------------------------------------------------------
// Callbacks
// ------------------------------------------------------------------

static void on_touch(int x, int y) {
    display_wake();
    display_show_status("Loading...");
    mqtt_publish_touch(x, y);
}

static void on_nowplaying(const char* station, const char* location, const char* country) {
    display_show_nowplaying(station, location, country);
}

static void on_status(const char* state, const char* msg) {
    if (strcmp(state, "playing") == 0) {
        display_show_status("Playing");
    } else if (strcmp(state, "stopped") == 0) {
        display_show_status("Stopped");
    } else if (strcmp(state, "loading") == 0) {
        display_show_status("Loading...");
    } else if (strcmp(state, "error") == 0) {
        char buf[64];
        snprintf(buf, sizeof(buf), "Error: %s", msg);
        display_show_status(buf);
    } else {
        display_show_status(state);
    }
}

// ------------------------------------------------------------------
// Arduino setup & loop
// ------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== RadioWall ===");

    // Initialize display first (visual feedback)
    display_init();

    // Initialize WiFi + MQTT
    display_show_connecting();
    mqtt_init();
    mqtt_set_nowplaying_callback(on_nowplaying);
    mqtt_set_status_callback(on_status);

    // Initialize touch input (built-in or USB, depending on config)
    touch_init();
    touch_set_callback(on_touch);

    // Ready
    display_show_status(mqtt_is_connected() ? "Ready" : "MQTT disconnected");
    Serial.println("[Main] Setup complete");
}

void loop() {
    mqtt_loop();
    touch_task();
    display_loop();
}
