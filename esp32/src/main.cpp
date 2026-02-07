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
#include "menu.h"
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

    // Show loading feedback in status bar
    ui_state.set_status_text("Loading...");
    display_update_status_bar(&ui_state);

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
        ui_state.set_status_text("No stations found");
        display_update_status_bar(&ui_state);
    }
}

// Helper: toggle between map and menu views
static void toggle_menu();

static void on_ui_button(int button_id) {
    display_wake();

    ViewMode mode = ui_state.get_view_mode();

    if (mode == VIEW_VOLUME) {
        // Volume mode: left = BACK (to menu), right = MUTE
        if (button_id == 0) {
            Serial.println("[Main] BACK (to menu)");
            ui_state.set_view_mode(VIEW_MENU);
            display_show_menu_view(&ui_state);
        } else if (button_id == 1) {
            Serial.println("[Main] MUTE (TODO)");
        }
    } else if (mode == VIEW_MENU) {
        // Menu mode: left = BACK, right = STOP
        if (button_id == 0) {
            Serial.println("[Main] BACK (to map)");
            toggle_menu();
        } else if (button_id == 1) {
            Serial.println("[Main] STOP (from menu)");
            radio_stop();
            ui_state.set_stopped();
            display_update_status_bar_menu(&ui_state);
        }
    } else {
        // Map mode: left = STOP, right = NEXT
        if (button_id == 0) {
            Serial.println("[Main] STOP");
            radio_stop();
            ui_state.set_stopped();
            display_update_status_bar(&ui_state);
        } else if (button_id == 1) {
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
}

static void on_slice_cycle() {
    if (ui_state.is_menu_active()) return;
    ui_state.cycle_slice();
    MapSlice& slice = ui_state.get_current_slice();
    Serial.printf("[Main] Region: %s\n", slice.name);
    display_refresh_map_only(&ui_state);
    display_update_status_bar(&ui_state);
    display_wake();
}

static void on_stop_button() {
    Serial.println("[Main] Long press -> Toggle menu");
    display_wake();
    toggle_menu();
}

static void on_next_button() {
    if (ui_state.is_menu_active()) return;
    Serial.println("[Main] NEXT (button)");
    display_wake();

    ui_state.set_status_text("Loading...");
    display_update_status_bar(&ui_state);

    if (radio_play_next()) {
        const StationInfo* station = radio_get_current();
        if (station) {
            ui_state.set_playing(station->title, station->place);
            display_update_status_bar(&ui_state);
        }
    } else {
        ui_state.set_status_text("No more stations");
        display_update_status_bar(&ui_state);
    }
}

// ------------------------------------------------------------------
// Swipe callback
// ------------------------------------------------------------------

static void on_swipe(int direction) {
    display_wake();
    if (direction > 0) {
        ui_state.cycle_slice();
    } else {
        ui_state.cycle_slice_reverse();
    }
    MapSlice& slice = ui_state.get_current_slice();
    Serial.printf("[Main] Swipe %s -> %s\n", direction > 0 ? "right" : "left", slice.name);
    display_refresh_map_only(&ui_state);
    display_update_status_bar(&ui_state);
}

// ------------------------------------------------------------------
// Volume callback
// ------------------------------------------------------------------

static unsigned long _last_vol_update = 0;

static void on_volume_change(int volume) {
    ui_state.set_volume(volume);
    display_update_volume_bar(&ui_state);

    // Debounce LinkPlay calls to every 200ms
    unsigned long now = millis();
    if (now - _last_vol_update > 200) {
        linkplay_set_volume(volume);
        _last_vol_update = now;
        Serial.printf("[Main] Volume: %d%%\n", volume);
    }
}

// ------------------------------------------------------------------
// Menu callbacks
// ------------------------------------------------------------------

static void toggle_menu() {
    if (ui_state.get_view_mode() == VIEW_MAP) {
        ui_state.set_view_mode(VIEW_MENU);
        display_show_menu_view(&ui_state);
    } else {
        // From menu or volume -> back to map
        ui_state.set_view_mode(VIEW_MAP);
        display_show_map_view(&ui_state);
    }
}

static void on_menu_item(MenuItemId item_id) {
    Serial.printf("[Main] Menu item selected: %d\n", item_id);

    switch (item_id) {
        case MENU_VOLUME:
            ui_state.set_view_mode(VIEW_VOLUME);
            display_show_volume_view(&ui_state);
            break;
        case MENU_PAUSE_RESUME:
            if (ui_state.get_is_playing() && !ui_state.is_paused()) {
                linkplay_pause();
                ui_state.set_paused(true);
                ui_state.set_status_text("Paused");
            } else if (ui_state.is_paused()) {
                linkplay_resume();
                ui_state.set_paused(false);
                ui_state.set_status_text("Resumed");
            }
            display_update_status_bar_menu(&ui_state);
            break;
        case MENU_FAVORITES:    Serial.println("[Main] TODO: Favorites"); break;
        case MENU_SLEEP_TIMER: {
            // Cycle through presets: Off -> 15 -> 30 -> 60 -> 90 -> Off
            static const int presets[] = {0, 15, 30, 60, 90};
            static const int num_presets = 5;
            int current = ui_state.get_sleep_timer();
            int next_idx = 0;
            for (int i = 0; i < num_presets; i++) {
                if (presets[i] == current) {
                    next_idx = (i + 1) % num_presets;
                    break;
                }
            }
            int next_min = presets[next_idx];
            linkplay_set_sleep_timer(next_min);
            ui_state.set_sleep_timer(next_min);
            if (next_min > 0) {
                char buf[24];
                snprintf(buf, sizeof(buf), "Sleep: %d min", next_min);
                ui_state.set_status_text(buf);
            } else {
                ui_state.set_status_text("Sleep: off");
            }
            display_update_status_bar_menu(&ui_state);
            break;
        }
        case MENU_EQUALIZER:    Serial.println("[Main] TODO: Equalizer"); break;
        case MENU_SETTINGS:     Serial.println("[Main] TODO: Settings"); break;
        default: break;
    }
}

static void on_menu_touch(int portrait_x, int portrait_y) {
    display_wake();
    menu_handle_touch(portrait_x, portrait_y, display_get_gfx());
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

    // Initialize menu
    menu_init();
    menu_set_item_callback(on_menu_item);

    // Initialize buttons (GPIO 0 only - GPIO 21 conflicts with display)
    // Short press: cycle region, Long press: toggle menu, Double-tap: NEXT
    button_init();
    button_set_band_cycle_callback(on_slice_cycle);
    button_set_stop_callback(on_stop_button);
    button_set_next_callback(on_next_button);

    // Initialize touch
    touch_init();
    #if USE_BUILTIN_TOUCH
        builtin_touch_set_map_callback(on_map_touch);
        builtin_touch_set_ui_button_callback(on_ui_button);
        builtin_touch_set_menu_callback(on_menu_touch);
        builtin_touch_set_swipe_callback(on_swipe);
        builtin_touch_set_volume_change_callback(on_volume_change);
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
