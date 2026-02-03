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
#include "ui_state.h"
#include "button_handler.h"
#include "places_db.h"

// ------------------------------------------------------------------
// Global State
// ------------------------------------------------------------------

static UIState ui_state;

// ------------------------------------------------------------------
// Callbacks
// ------------------------------------------------------------------

// Legacy callback for backward compatibility
static void on_touch(int x, int y) {
    display_wake();
    display_show_status("Loading...");
    mqtt_publish_touch(x, y);
}

// Map touch callback (new zone-based handling)
static void on_map_touch(int server_x, int server_y) {
    display_wake();
    mqtt_publish_touch(server_x, server_y);
    Serial.printf("[Main] Map touched: sending coordinates (%d, %d) to server\n", server_x, server_y);
}

// UI button callback (status bar buttons)
static void on_ui_button(int button_id) {
    display_wake();
    if (button_id == 0) {
        // STOP button
        Serial.println("[Main] STOP button pressed");
        mqtt_publish_command("stop");
    } else if (button_id == 1) {
        // NEXT button
        Serial.println("[Main] NEXT button pressed");
        mqtt_publish_command("next");
    }
}

// Physical button callbacks
static void on_slice_cycle() {
    ui_state.cycle_slice();
    MapSlice& slice = ui_state.get_current_slice();
    Serial.printf("[Main] Slice cycled to: %s (%s)\n", slice.name, slice.label);
    display_refresh_map_only(&ui_state);
    display_update_status_bar(&ui_state);  // Update status bar to show new region
    display_wake();
}

static void on_stop_button() {
    Serial.println("[Main] Physical STOP button pressed");
    mqtt_publish_command("stop");
    display_wake();
}

static void on_nowplaying(const char* station, const char* location, const char* country) {
    // Update UI state
    ui_state.set_playing(station, location);

    // Update status bar only (keeps map visible)
    display_update_status_bar(&ui_state);

    Serial.printf("[Main] Now playing: %s - %s, %s\n", station, location, country);
}

static void on_status(const char* state, const char* msg) {
    if (strcmp(state, "stopped") == 0) {
        ui_state.set_stopped();
        display_update_status_bar(&ui_state);
        Serial.println("[Main] Playback stopped");
    } else if (strcmp(state, "error") == 0) {
        Serial.printf("[Main] Error from server: %s\n", msg);
        // Keep current state, just log the error
    } else {
        Serial.printf("[Main] Status update: %s\n", state);
    }
}

// ------------------------------------------------------------------
// Arduino setup & loop
// ------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== RadioWall - World Map Edition ===");

    // Initialize display first (visual feedback)
    display_init();

    // Initialize places database from LittleFS
    if (!places_db_init()) {
        Serial.println("[Main] WARNING: Places database not loaded");
        Serial.println("[Main] Run 'pio run -t uploadfs' to upload places.bin");
    }

    // Show temporary connecting screen
    display_show_connecting();

    // Initialize WiFi + MQTT
    mqtt_init();
    mqtt_set_nowplaying_callback(on_nowplaying);
    mqtt_set_status_callback(on_status);

    // Initialize physical buttons
    button_init();
    button_set_band_cycle_callback(on_slice_cycle);
    button_set_stop_callback(on_stop_button);

    // Initialize touch input (built-in or USB, depending on config)
    touch_init();

    #if USE_BUILTIN_TOUCH
        // Use new zone-based touch callbacks for built-in touch
        builtin_touch_set_map_callback(on_map_touch);
        builtin_touch_set_ui_button_callback(on_ui_button);
        builtin_touch_set_ui_state(&ui_state);
        Serial.println("[Main] Built-in touch: zone-based callbacks configured");
    #else
        // Use legacy callback for USB touch (no zones)
        touch_set_callback(on_touch);
        Serial.println("[Main] USB touch: legacy callback configured");
    #endif

    // Show map view
    delay(500);  // Brief pause to let WiFi/MQTT start connecting
    display_show_map_view(&ui_state);

    // Ready
    Serial.printf("[Main] Setup complete - MQTT %s\n",
                  mqtt_is_connected() ? "connected" : "connecting...");
    Serial.printf("[Main] Current slice: %s (%s)\n",
                  ui_state.get_current_slice().name,
                  ui_state.get_current_slice().label);
}

void loop() {
    mqtt_loop();
    touch_task();
    button_task();
    display_loop();
    places_db_serial_task();
}
