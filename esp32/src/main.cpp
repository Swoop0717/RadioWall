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
#include "favorites.h"
#include "history.h"
#include "settings.h"
#include <ESPmDNS.h>
#include <ArduinoJson.h>
#include <LittleFS.h>

// ------------------------------------------------------------------
// Global State
// ------------------------------------------------------------------

static UIState ui_state;

// Forward declarations
static void record_to_history(const StationInfo* station);

// ------------------------------------------------------------------
// Playback persistence (resume after reboot)
// ------------------------------------------------------------------

static const char* PLAYBACK_FILE = "/playback.json";

static void save_playback_state() {
    const StationInfo* station = radio_get_current();
    if (!station || !station->valid) return;

    File f = LittleFS.open(PLAYBACK_FILE, "w");
    if (!f) return;

    DynamicJsonDocument doc(256);
    doc["id"] = station->id;
    doc["t"] = station->title;
    doc["p"] = station->place;
    doc["c"] = station->country;
    doc["lat"] = station->lat;
    doc["lon"] = station->lon;
    serializeJson(doc, f);
    f.close();
    Serial.printf("[Main] Saved playback: %s\n", station->title);
}

static void clear_playback_state() {
    if (LittleFS.exists(PLAYBACK_FILE)) {
        LittleFS.remove(PLAYBACK_FILE);
        Serial.println("[Main] Cleared saved playback");
    }
}

static bool resume_playback() {
    if (!LittleFS.exists(PLAYBACK_FILE)) return false;

    File f = LittleFS.open(PLAYBACK_FILE, "r");
    if (!f) return false;

    DynamicJsonDocument doc(256);
    if (deserializeJson(doc, f)) { f.close(); return false; }
    f.close();

    const char* id = doc["id"] | "";
    const char* title = doc["t"] | "";
    const char* place = doc["p"] | "";
    const char* country = doc["c"] | "";
    float lat = doc["lat"] | 0.0f;
    float lon = doc["lon"] | 0.0f;

    if (strlen(id) == 0) return false;

    Serial.printf("[Main] Resuming: %s (%s, %s)\n", title, place, country);

    if (radio_play_by_id(id, title, place, country, lat, lon)) {
        ui_state.set_playing(title, place);
        ui_state.set_marker(lat, lon);

        int slice_idx = ui_state.slice_index_for_lon(lon);
        ui_state.set_slice_index(slice_idx);
        return true;
    }

    Serial.println("[Main] Resume failed - clearing saved state");
    clear_playback_state();
    return false;
}

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
            ui_state.set_marker(station->lat, station->lon);
            save_playback_state();
            record_to_history(station);
            display_draw_marker_at_latlon(station->lat, station->lon, &ui_state);
            display_update_status_bar(&ui_state);
        }
    } else {
        ui_state.set_status_text("No stations found");
        display_update_status_bar(&ui_state);
    }
}

// ------------------------------------------------------------------
// Double-tap zoom callback
// ------------------------------------------------------------------

static void on_map_double_tap(int portrait_x, int portrait_y) {
    display_wake();

    const int MAP_AREA_HEIGHT = 580;
    const int MAP_W = 180;

    // Convert portrait coords to lat/lon (same math as fire_map_tap)
    float norm_x = portrait_x / (float)(MAP_W - 1);
    float norm_y = portrait_y / (float)(MAP_AREA_HEIGHT - 1);

    float lon_min = ui_state.get_view_lon_min();
    float lon_max = ui_state.get_view_lon_max();
    float lat_max = ui_state.get_view_lat_max();
    float lat_min = ui_state.get_view_lat_min();

    float lon_range = lon_max - lon_min;
    if (lon_range < 0) lon_range += 360.0f;

    float lon = lon_min + norm_x * lon_range;
    float lat = lat_max - norm_y * (lat_max - lat_min);

    if (lon > 180.0f) lon -= 360.0f;
    if (lon < -180.0f) lon += 360.0f;

    // Cycle zoom: 1 -> 2 -> 3 -> 4 -> 5 -> 1
    int current_zoom = ui_state.get_zoom_level();
    int new_zoom = (current_zoom >= 5) ? 1 : current_zoom + 1;

    Serial.printf("[Main] Double-tap zoom: %dx -> %dx at (%.1f, %.1f)\n",
                  current_zoom, new_zoom, lat, lon);

    ui_state.set_zoom_centered(new_zoom, lat, lon);
    settings_set_zoom_no_render(new_zoom);

    display_show_map_view(&ui_state);
}

// ------------------------------------------------------------------
// Favorites callbacks
// ------------------------------------------------------------------

static void on_favorite_play(int index) {
    const FavoriteStation* fav = favorites_get(index);
    if (!fav) return;

    ui_state.set_status_text("Loading...");
    display_show_favorites_view(&ui_state);

    if (radio_play_by_id(fav->station_id, fav->title, fav->place, fav->country,
                         fav->lat, fav->lon)) {
        ui_state.set_playing(fav->title, fav->place);
        ui_state.set_marker(fav->lat, fav->lon);
        save_playback_state();
        record_to_history(radio_get_current());

        // Auto-switch to correct map slice
        int slice_idx = ui_state.slice_index_for_lon(fav->lon);
        ui_state.set_slice_index(slice_idx);

        // Go to map view with marker
        ui_state.set_view_mode(VIEW_MAP);
        display_show_map_view(&ui_state);
    } else {
        ui_state.set_status_text("Failed to play");
        display_show_favorites_view(&ui_state);
    }
}

static void on_favorite_delete(int index) {
    favorites_remove(index);
    display_show_favorites_view(&ui_state);
}

// ------------------------------------------------------------------
// History helpers
// ------------------------------------------------------------------

static void record_to_history(const StationInfo* station) {
    if (!station || !station->valid) return;
    HistoryEntry entry;
    strncpy(entry.station_id, station->id, 15);
    entry.station_id[15] = '\0';
    strncpy(entry.title, station->title, 63);
    entry.title[63] = '\0';
    strncpy(entry.place, station->place, 31);
    entry.place[31] = '\0';
    strncpy(entry.country, station->country, 3);
    entry.country[3] = '\0';
    entry.lat = station->lat;
    entry.lon = station->lon;
    history_record(entry);
}

static void on_history_play(int index) {
    const HistoryEntry* entry = history_get(index);
    if (!entry) return;

    ui_state.set_status_text("Loading...");
    display_show_history_view(&ui_state);

    if (radio_play_by_id(entry->station_id, entry->title, entry->place, entry->country,
                         entry->lat, entry->lon)) {
        ui_state.set_playing(entry->title, entry->place);
        ui_state.set_marker(entry->lat, entry->lon);
        save_playback_state();

        int slice_idx = ui_state.slice_index_for_lon(entry->lon);
        ui_state.set_slice_index(slice_idx);

        ui_state.set_view_mode(VIEW_MAP);
        display_show_map_view(&ui_state);
    } else {
        ui_state.set_status_text("Failed to play");
        display_show_history_view(&ui_state);
    }
}

// ------------------------------------------------------------------
// Settings callback
// ------------------------------------------------------------------

static void on_device_selected(const char* ip, const char* name) {
    Serial.printf("[Main] WiiM device selected: %s (%s)\n", name, ip);

    // Stop playback on the old device before switching
    if (ui_state.get_is_playing()) {
        linkplay_stop();
        radio_stop();
        ui_state.set_stopped();
        clear_playback_state();
    }

    // Ungroup all slaves from the OLD master before switching
    linkplay_multiroom_ungroup();

    // Switch to new primary
    linkplay_set_ip(ip);

    // Re-join saved group members to the NEW master
    char grp_ips[MAX_GROUP_DEVICES][16];
    int grp_count = settings_get_group_ips(grp_ips, MAX_GROUP_DEVICES);
    for (int i = 0; i < grp_count; i++) {
        if (strcmp(grp_ips[i], ip) == 0) continue;  // Skip self
        Serial.printf("[Main] Re-joining %s to new master\n", grp_ips[i]);
        linkplay_multiroom_join(grp_ips[i]);
        delay(500);
    }

    ui_state.set_status_text("Device set!");
    display_update_status_bar_settings(&ui_state);
}

static void on_group_changed(const char* slave_ip, bool joined) {
    if (joined) {
        Serial.printf("[Main] Joining %s to multiroom group\n", slave_ip);
        linkplay_multiroom_join(slave_ip);
    } else {
        Serial.printf("[Main] Removing %s from multiroom group\n", slave_ip);
        linkplay_multiroom_kick(slave_ip);
    }
}

// Helper: toggle between map and menu views
static void toggle_menu();

static void on_ui_button(int button_id) {
    display_wake();

    ViewMode mode = ui_state.get_view_mode();

    if (mode == VIEW_FAVORITES) {
        // Favorites mode: left = BACK (to menu), right = ADD
        if (button_id == 0) {
            Serial.println("[Main] BACK (to menu)");
            ui_state.set_view_mode(VIEW_MENU);
            display_show_menu_view(&ui_state);
        } else if (button_id == 1) {
            const StationInfo* station = radio_get_current();
            if (station && station->valid) {
                if (favorites_contains(station->id)) {
                    ui_state.set_status_text("Already saved");
                } else {
                    FavoriteStation fav;
                    strncpy(fav.station_id, station->id, 15);
                    fav.station_id[15] = '\0';
                    strncpy(fav.title, station->title, 63);
                    fav.title[63] = '\0';
                    strncpy(fav.place, station->place, 31);
                    fav.place[31] = '\0';
                    strncpy(fav.country, station->country, 3);
                    fav.country[3] = '\0';
                    fav.lat = station->lat;
                    fav.lon = station->lon;
                    if (favorites_add(fav)) {
                        ui_state.set_status_text("Added!");
                    } else {
                        ui_state.set_status_text("Favorites full");
                    }
                }
            } else {
                ui_state.set_status_text("Nothing playing");
            }
            display_show_favorites_view(&ui_state);
        }
    } else if (mode == VIEW_HISTORY) {
        // History mode: left = BACK (to menu), right = CLEAR
        if (button_id == 0) {
            Serial.println("[Main] BACK (to menu)");
            ui_state.set_view_mode(VIEW_MENU);
            display_show_menu_view(&ui_state);
        } else if (button_id == 1) {
            Serial.println("[Main] CLEAR history");
            history_clear();
            display_show_history_view(&ui_state);
        }
    } else if (mode == VIEW_SETTINGS) {
        // Settings mode: left = BACK (to menu), right = STOP
        if (button_id == 0) {
            Serial.println("[Main] BACK (to menu)");
            ui_state.set_view_mode(VIEW_MENU);
            display_show_menu_view(&ui_state);
        } else if (button_id == 1) {
            Serial.println("[Main] STOP (from settings)");
            radio_stop();
            ui_state.set_stopped();
            clear_playback_state();
            display_update_status_bar_settings(&ui_state);
        }
    } else if (mode == VIEW_VOLUME) {
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
            clear_playback_state();
            display_update_status_bar_menu(&ui_state);
        }
    } else {
        // Map mode: left = STOP, right = NEXT
        if (button_id == 0) {
            Serial.println("[Main] STOP");
            radio_stop();
            ui_state.set_stopped();
            clear_playback_state();
            display_update_status_bar(&ui_state);
        } else if (button_id == 1) {
            Serial.println("[Main] NEXT");
            ui_state.set_status_text("Loading...");
            display_update_status_bar(&ui_state);
            if (radio_play_next()) {
                const StationInfo* station = radio_get_current();
                if (station) {
                    ui_state.set_playing(station->title, station->place);
                    ui_state.set_marker(station->lat, station->lon);
                    save_playback_state();
                    record_to_history(station);
                    display_draw_marker_at_latlon(station->lat, station->lon, &ui_state);
                    display_update_status_bar(&ui_state);
                }
            } else {
                ui_state.set_status_text("No more stations");
                display_update_status_bar(&ui_state);
            }
        }
    }
}

static void on_slice_cycle() {
    if (ui_state.get_view_mode() == VIEW_FAVORITES) {
        favorites_next_page();
        display_show_favorites_view(&ui_state);
        display_wake();
        return;
    }
    if (ui_state.get_view_mode() == VIEW_HISTORY) {
        history_next_page();
        display_show_history_view(&ui_state);
        display_wake();
        return;
    }
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
            ui_state.set_marker(station->lat, station->lon);
            save_playback_state();
            record_to_history(station);
            display_draw_marker_at_latlon(station->lat, station->lon, &ui_state);
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
    if (ui_state.get_view_mode() != VIEW_MAP) return;

    bool changed = false;
    int zoom = ui_state.get_zoom_level();

    if (direction == 1 || direction == -1) {
        // Horizontal swipe
        if (zoom > 1) {
            changed = (direction == 1) ? ui_state.zoom_move_right()
                                       : ui_state.zoom_move_left();
        } else {
            if (direction > 0) ui_state.cycle_slice();
            else ui_state.cycle_slice_reverse();
            changed = true;
        }
    } else if (direction == 2 || direction == -2) {
        // Vertical swipe (only meaningful at zoom > 1)
        if (zoom > 1) {
            changed = (direction == 2) ? ui_state.zoom_move_down()
                                       : ui_state.zoom_move_up();
        }
    }

    if (changed) {
        MapSlice& slice = ui_state.get_current_slice();
        Serial.printf("[Main] Swipe dir=%d -> %s (zoom=%d col=%d row=%d)\n",
                      direction, slice.name, zoom,
                      ui_state.get_zoom_col(), ui_state.get_zoom_row());
        display_refresh_map_only(&ui_state);
        display_update_status_bar(&ui_state);
    }
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
        ui_state.set_zoom_level(settings_get_zoom());  // Sync zoom from settings
        ui_state.set_view_mode(VIEW_MAP);
        display_show_map_view(&ui_state);
    }
}

static void on_menu_item(MenuItemId item_id) {
    Serial.printf("[Main] Menu item selected: %d\n", item_id);

    switch (item_id) {
        case MENU_VOLUME: {
            // Fetch actual volume from WiiM before showing slider
            int current_vol = linkplay_get_volume();
            if (current_vol >= 0) {
                ui_state.set_volume(current_vol);
            }
            ui_state.set_view_mode(VIEW_VOLUME);
            display_show_volume_view(&ui_state);
            break;
        }
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
        case MENU_FAVORITES:
            favorites_set_page(0);
            ui_state.set_view_mode(VIEW_FAVORITES);
            display_show_favorites_view(&ui_state);
            break;
        case MENU_HISTORY:
            history_set_page(0);
            ui_state.set_view_mode(VIEW_HISTORY);
            display_show_history_view(&ui_state);
            break;
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
        case MENU_SETTINGS:
            ui_state.set_view_mode(VIEW_SETTINGS);
            display_show_settings_view(&ui_state);  // Shows "Scanning..."
            settings_start_scan();                   // Blocking ~2s mDNS query
            display_show_settings_view(&ui_state);  // Shows results
            break;
        default: break;
    }
}

static void on_menu_touch(int portrait_x, int portrait_y) {
    display_wake();
    ViewMode mode = ui_state.get_view_mode();
    if (mode == VIEW_FAVORITES) {
        favorites_handle_touch(portrait_x, portrait_y, display_get_gfx());
    } else if (mode == VIEW_HISTORY) {
        history_handle_touch(portrait_x, portrait_y, display_get_gfx());
    } else if (mode == VIEW_SETTINGS) {
        settings_handle_touch(portrait_x, portrait_y, display_get_gfx());
    } else {
        menu_handle_touch(portrait_x, portrait_y, display_get_gfx());
    }
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

    // Connect to WiFi (retry until connected — no WiFi = no radio)
    display_show_connecting();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);

    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n[WiFi] Connected: %s\n", WiFi.localIP().toString().c_str());

    // Initialize mDNS (for device discovery)
    if (MDNS.begin("radiowall")) {
        Serial.println("[mDNS] Started as radiowall.local");
    }

    // Initialize settings (load saved WiiM IP and zoom level from LittleFS)
    settings_init();
    settings_set_device_callback(on_device_selected);
    settings_set_group_callback(on_group_changed);
    ui_state.set_zoom_level(settings_get_zoom());

    // Initialize LinkPlay client with saved IP (falls back to WIIM_IP from config.h)
    const char* wiim_ip = settings_get_wiim_ip();
    if (wiim_ip[0] != '\0') {
        linkplay_init(wiim_ip);
        Serial.printf("[LinkPlay] WiiM: %s\n", wiim_ip);

        // Rejoin saved multiroom group members (best effort, single attempt)
        char grp_ips[MAX_GROUP_DEVICES][16];
        int grp_count = settings_get_group_ips(grp_ips, MAX_GROUP_DEVICES);
        if (grp_count > 0) {
            Serial.printf("[Main] Rejoining %d group member(s)...\n", grp_count);
            for (int i = 0; i < grp_count; i++) {
                Serial.printf("[Main]   Joining %s\n", grp_ips[i]);
                linkplay_multiroom_join(grp_ips[i]);
                delay(500);
            }
        }
    } else {
        Serial.println("[LinkPlay] No WiiM IP configured - use Settings to scan");
    }

    // Initialize radio client
    radio_client_init();

    // Initialize menu
    menu_init();
    menu_set_item_callback(on_menu_item);

    // Initialize favorites
    favorites_init();
    favorites_set_play_callback(on_favorite_play);
    favorites_set_delete_callback(on_favorite_delete);

    // Initialize history
    history_init();
    history_set_play_callback(on_history_play);

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
        builtin_touch_set_map_double_tap_callback(on_map_double_tap);
        builtin_touch_set_ui_state(&ui_state);
    #endif

    // Resume previous playback or stop stale WiiM playback
    if (!resume_playback()) {
        // No saved state - stop WiiM in case it's still playing from last session
        linkplay_stop();
    }

    // Show map (will show playing state if resumed)
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
