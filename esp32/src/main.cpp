/**
 * RadioWall ESP32 Firmware - Standalone Mode
 *
 * Touch the map -> find nearest city -> fetch stations from Radio.garden
 * -> stream to WiiM via LinkPlay API
 */

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"

#if USE_BUILTIN_TOUCH
  #include "builtin_touch.h"
  #define touch_init    builtin_touch_init
  #define touch_task    builtin_touch_task
#else
  #include "usb_touch.h"
  #define touch_init    usb_touch_init
  #define touch_task    usb_touch_task
#endif

#include "display.h"
#include "ui_state.h"
#include "button_handler.h"
#include "places_db.h"
#include "linkplay_client.h"
#include "radio_client.h"

// ------------------------------------------------------------------
// Global State
// ------------------------------------------------------------------

static UIState ui_state;

// ------------------------------------------------------------------
// Callbacks
// ------------------------------------------------------------------

static void on_map_touch(int server_x, int server_y) {
    display_wake();
    display_show_status("Loading...");

    // Convert server coordinates (1024x600 equirectangular) to lat/lon
    float lon = (server_x / 1024.0f) * 360.0f - 180.0f;
    float lat = 90.0f - (server_y / 600.0f) * 180.0f;

    Serial.printf("[Main] Touch -> lat=%.2f, lon=%.2f\n", lat, lon);

    if (radio_play_at_location(lat, lon)) {
        const StationInfo* station = radio_get_current();
        if (station) {
            ui_state.set_playing(station->title, station->place);
            display_update_status_bar(&ui_state);
        }
    } else {
        display_show_status("No stations found");
    }
}

static void on_ui_button(int button_id) {
    display_wake();
    if (button_id == 0) {
        // STOP button
        Serial.println("[Main] STOP");
        radio_stop();
        ui_state.set_stopped();
        display_update_status_bar(&ui_state);
    } else if (button_id == 1) {
        // NEXT button
        Serial.println("[Main] NEXT");
        if (radio_play_next()) {
            const StationInfo* station = radio_get_current();
            if (station) {
                ui_state.set_playing(station->title, station->place);
                display_update_status_bar(&ui_state);
            }
        }
    }
}

static void on_slice_cycle() {
    ui_state.cycle_slice();
    MapSlice& slice = ui_state.get_current_slice();
    Serial.printf("[Main] Region: %s\n", slice.name);
    display_refresh_map_only(&ui_state);
    display_update_status_bar(&ui_state);
    display_wake();
}

static void on_stop_button() {
    Serial.println("[Main] STOP (physical)");
    radio_stop();
    ui_state.set_stopped();
    display_update_status_bar(&ui_state);
    display_wake();
}

// ------------------------------------------------------------------
// Arduino setup & loop
// ------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== RadioWall Standalone ===");

    // Initialize display
    display_init();

    // Load places database
    if (!places_db_init()) {
        Serial.println("[Main] WARNING: No places.bin - run 'pio run -t uploadfs'");
    }

    // Connect to WiFi
    display_show_connecting();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Connected: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\n[WiFi] Connection failed!");
    }

    // Initialize LinkPlay client
    #ifdef WIIM_IP
        linkplay_init(WIIM_IP);
        Serial.printf("[LinkPlay] WiiM: %s\n", WIIM_IP);
    #else
        Serial.println("[LinkPlay] WIIM_IP not configured");
    #endif

    // Initialize radio client
    radio_client_init();

    // Initialize buttons
    button_init();
    button_set_band_cycle_callback(on_slice_cycle);
    button_set_stop_callback(on_stop_button);

    // Initialize touch
    touch_init();
    #if USE_BUILTIN_TOUCH
        builtin_touch_set_map_callback(on_map_touch);
        builtin_touch_set_ui_button_callback(on_ui_button);
        builtin_touch_set_ui_state(&ui_state);
    #endif

    // Show map
    display_show_map_view(&ui_state);

    Serial.printf("[Main] Ready - Region: %s\n", ui_state.get_current_slice().name);
}

void loop() {
    touch_task();
    button_task();
    display_loop();
    places_db_serial_task();
    linkplay_serial_task();
}
