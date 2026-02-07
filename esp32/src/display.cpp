/**
 * AMOLED display control for RadioWall on T-Display-S3-Long.
 *
 * Uses Arduino_GFX library with AXS15231B QSPI display controller (640×180).
 * Based on working LILYGO GFX_AXS15231B_Image example.
 */

#include "display.h"
#include "config.h"
#include "pins_config.h"
#include "Arduino_GFX_Library.h"
#include "ui_state.h"
#include "world_map.h"
#include "menu.h"
#include "favorites.h"
#include "settings.h"
#include "radio_client.h"

#define LCD_CS TFT_QSPI_CS
#define LCD_SCLK TFT_QSPI_SCK
#define LCD_SDIO0 TFT_QSPI_D0
#define LCD_SDIO1 TFT_QSPI_D1
#define LCD_SDIO2 TFT_QSPI_D2
#define LCD_SDIO3 TFT_QSPI_D3
#define LCD_RST TFT_QSPI_RST

#define LCD_WIDTH 180
#define LCD_HEIGHT 640

// Global GFX instance (using Arduino_GFX library)
static Arduino_DataBus *bus = nullptr;
static Arduino_GFX *gfx = nullptr;

static unsigned long _last_activity = 0;
static bool _dimmed = false;

// Current display state
static char _station[128] = "";
static char _location[128] = "";
static char _country[8] = "";
static char _status[32] = "idle";

void display_init() {
    Serial.println("[Display] Initializing Arduino_GFX AXS15231B display...");

    // Initialize backlight with PWM (smooth fade-in like working example)
    pinMode(TFT_BL, OUTPUT);
    ledcAttachPin(TFT_BL, 1);
    ledcSetup(1, 2000, 8);
    ledcWrite(1, 0);  // Start dim

    // Create QSPI bus
    bus = new Arduino_ESP32QSPI(
        LCD_CS /* CS */, LCD_SCLK /* SCK */, LCD_SDIO0 /* SDIO0 */,
        LCD_SDIO1 /* SDIO1 */, LCD_SDIO2 /* SDIO2 */, LCD_SDIO3 /* SDIO3 */);

    // Create AXS15231 display driver
    // Rotation 0 = Portrait (180×640) - STABLE WORKING CONFIGURATION
    // NOTE: Rotations 1 and 3 cause fading/crashing issues
    gfx = new Arduino_AXS15231(bus, LCD_RST /* RST */, 0 /* rotation */,
                               false /* IPS */, LCD_WIDTH, LCD_HEIGHT);

    // Initialize display
    gfx->begin();
    gfx->fillScreen(BLACK);

    // Fade in backlight smoothly
    for (int i = 0; i <= 255; i++) {
        ledcWrite(1, i);
        delay(3);
    }

    // Show RadioWall splash (landscape coordinates: 640 wide × 180 tall)
    gfx->setCursor(220, 60);
    gfx->setTextSize(2);
    gfx->setTextColor(CYAN);
    gfx->println("RadioWall");

    gfx->setCursor(120, 100);
    gfx->setTextSize(1);
    gfx->setTextColor(WHITE);
    gfx->println("Touch the world map to play radio");

    _last_activity = millis();
    _dimmed = false;

    Serial.println("[Display] Arduino_GFX display initialized successfully!");
}

void display_loop() {
    // No-op for now (auto-dimming could go here)
}

void display_show_nowplaying(const char* station, const char* location, const char* country) {
    strncpy(_station, station, sizeof(_station) - 1);
    strncpy(_location, location, sizeof(_location) - 1);
    strncpy(_country, country, sizeof(_country) - 1);
    strncpy(_status, "Playing", sizeof(_status) - 1);

    // Print to serial
    Serial.println("");
    Serial.println("╔════════════════════════════════════════╗");
    Serial.println("║         NOW PLAYING                    ║");
    Serial.println("╠════════════════════════════════════════╣");
    Serial.printf("║ Station:  %-28s ║\n", station);
    Serial.printf("║ Location: %-28s ║\n", location);
    Serial.printf("║ Country:  %-28s ║\n", country);
    Serial.println("╚════════════════════════════════════════╝");
    Serial.println("");

    // Update display
    if (gfx) {
        gfx->fillScreen(BLACK);

        // Title
        gfx->setCursor(10, 50);
        gfx->setTextSize(1);
        gfx->setTextColor(CYAN);
        gfx->println("NOW PLAYING:");

        // Station name (larger)
        gfx->setCursor(10, 80);
        gfx->setTextSize(2);
        gfx->setTextColor(WHITE);
        gfx->println(station);

        // Location
        gfx->setCursor(10, 110);
        gfx->setTextSize(1);
        gfx->setTextColor(GREEN);
        gfx->println(location);

        // Country
        gfx->setCursor(10, 130);
        gfx->setTextColor(YELLOW);
        gfx->println(country);
    }

    display_wake();
}

void display_show_status(const char* status) {
    strncpy(_status, status, sizeof(_status) - 1);
    Serial.printf("[Display] Status: %s\n", status);

    if (gfx) {
        gfx->setCursor(10, 550);
        gfx->setTextSize(1);
        gfx->setTextColor(MAGENTA);
        gfx->printf("Status: %s", status);
    }
}

void display_show_connecting() {
    _station[0] = '\0';
    _location[0] = '\0';
    _country[0] = '\0';
    strncpy(_status, "Connecting...", sizeof(_status) - 1);

    Serial.println("[Display] Connecting to WiFi and MQTT...");

    if (gfx) {
        gfx->fillScreen(BLACK);
        // Landscape coordinates: 640 wide × 180 tall
        gfx->setCursor(200, 80);
        gfx->setTextSize(2);
        gfx->setTextColor(YELLOW);
        gfx->println("Connecting...");
    }
}

void display_wake() {
    _last_activity = millis();
    if (_dimmed) {
        _dimmed = false;
        if (gfx) {
            // Restore brightness
            ledcWrite(1, 255);
        }
    }
}

// Store previous marker position for efficient clearing
static int _prev_marker_x = -1;
static int _prev_marker_y = -1;

void display_draw_touch_feedback(int x, int y, UIState* state) {
    if (!gfx || !state) return;

    const int mark_size = 4;  // Half-size of the X

    // Clear previous marker by drawing over it with black
    // Note: This works well for ocean areas but may leave artifacts on land
    // A full map refresh only happens on region change, which is acceptable
    if (_prev_marker_x >= 0 && _prev_marker_y >= 0) {
        gfx->drawLine(_prev_marker_x - mark_size, _prev_marker_y - mark_size,
                      _prev_marker_x + mark_size, _prev_marker_y + mark_size, BLACK);
        gfx->drawLine(_prev_marker_x - mark_size, _prev_marker_y + mark_size,
                      _prev_marker_x + mark_size, _prev_marker_y - mark_size, BLACK);
    }

    // Draw new X marker at touch location
    if (x >= 0 && x < LCD_WIDTH && y >= 0 && y < LCD_HEIGHT - 60) {  // Stay above status bar
        gfx->drawLine(x - mark_size, y - mark_size, x + mark_size, y + mark_size, RED);
        gfx->drawLine(x - mark_size, y + mark_size, x + mark_size, y - mark_size, RED);
        _prev_marker_x = x;
        _prev_marker_y = y;
    }
}

Arduino_GFX* display_get_gfx() {
    return gfx;
}

// Map view functions

/**
 * Show full map view (map + status bar)
 */
void display_show_map_view(UIState* state) {
    if (!gfx) {
        Serial.println("[Display] ERROR: gfx is null!");
        return;
    }

    Serial.println("[Display] Showing portrait map view (180×640)...");

    // Clear screen with black
    gfx->fillScreen(BLACK);

    // Draw the map slice at top-left (160x560 bitmap)
    MapSlice& slice = state->get_current_slice();
    if (slice.bitmap && slice.bitmap_size > 0) {
        draw_map_slice(gfx, slice.bitmap, slice.bitmap_size, 0, 0);
    }

    // Draw marker if set
    if (state->has_marker()) {
        display_draw_marker_at_latlon(state->get_marker_lat(), state->get_marker_lon(), state);
    }

    // === STATUS BAR (580 to 640) ===
    display_update_status_bar(state);

    Serial.println("[Display] Portrait view complete!");
}

/**
 * Update status bar only (bottom 60px in portrait mode)
 */
void display_update_status_bar(UIState* state) {
    if (!gfx) return;

    // Portrait mode: 180 wide × 640 tall
    const int STATUS_Y = 580;  // Status bar starts at y=580
    const int STATUS_H = 60;    // Status bar height
    const int STATUS_W = 180;   // Display width

    // Clear status bar area
    gfx->fillRect(0, STATUS_Y, STATUS_W, STATUS_H, BLACK);

    gfx->setTextSize(1);

    // Line 1: City, CC (idx/total) when playing, else region name
    const char* status_text = state->get_status_text();
    if (status_text[0] != '\0') {
        gfx->setTextColor(MAGENTA);
        gfx->setCursor(5, STATUS_Y + 5);
        gfx->print(status_text);
    } else if (state->get_is_playing()) {
        // Show: "City, CC (2/5)"
        const StationInfo* station = radio_get_current();
        int idx = radio_get_station_index();
        int total = radio_get_total_stations();
        char line1[32];
        if (station && total > 0) {
            snprintf(line1, sizeof(line1), "%s, %s (%d/%d)",
                     station->place, station->country, idx, total);
        } else {
            snprintf(line1, sizeof(line1), "%s", state->get_location());
        }
        if (strlen(line1) > 28) {
            line1[25] = '.';
            line1[26] = '.';
            line1[27] = '.';
            line1[28] = '\0';
        }
        gfx->setTextColor(GREEN);
        gfx->setCursor(5, STATUS_Y + 5);
        gfx->print(line1);
    } else {
        MapSlice& slice = state->get_current_slice();
        gfx->setTextColor(CYAN);
        gfx->setCursor(5, STATUS_Y + 5);
        gfx->print(slice.name);
    }

    // Line 2: Station name when playing, else tap prompt
    if (state->get_is_playing() && status_text[0] == '\0') {
        char sname[29];
        strncpy(sname, state->get_station_name(), 28);
        sname[28] = '\0';
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(sname);
    } else if (!state->get_is_playing() && status_text[0] == '\0') {
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print("Tap map to play");
    }

    // Line 3: STOP and NEXT buttons (90px each)
    // STOP button (left half: 0-89)
    gfx->fillRect(0, STATUS_Y + 35, 90, 25, 0x0841);  // Dark blue
    gfx->setTextColor(WHITE);
    gfx->setCursor(25, STATUS_Y + 43);
    gfx->print("STOP");

    // NEXT button (right half: 90-179)
    gfx->fillRect(90, STATUS_Y + 35, 90, 25, 0x0841);  // Dark blue
    gfx->setCursor(115, STATUS_Y + 43);
    gfx->print("NEXT");
}

/**
 * Refresh map area only (not status bar)
 */
void display_refresh_map_only(UIState* state) {
    if (!gfx || !state) return;

    Serial.println("[Display] Refreshing map area...");

    // Clear map area (0 to 580) with black
    gfx->fillRect(0, 0, 180, 580, BLACK);

    // Draw the map slice at top-left (160x560 bitmap)
    MapSlice& slice = state->get_current_slice();
    if (slice.bitmap && slice.bitmap_size > 0) {
        draw_map_slice(gfx, slice.bitmap, slice.bitmap_size, 0, 0);
    }

    Serial.println("[Display] Map refresh complete");
}

/**
 * Show full menu view (menu items + status bar)
 */
void display_show_menu_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing menu view...");

    menu_render(gfx);
    display_update_status_bar_menu(state);

    Serial.println("[Display] Menu view complete!");
}

/**
 * Update status bar for menu mode (BACK + STOP)
 */
void display_update_status_bar_menu(UIState* state) {
    if (!gfx) return;

    const int STATUS_Y = 580;
    const int STATUS_H = 60;
    const int STATUS_W = 180;

    gfx->fillRect(0, STATUS_Y, STATUS_W, STATUS_H, BLACK);
    gfx->setTextSize(1);

    // Line 1: Context label
    gfx->setTextColor(CYAN);
    gfx->setCursor(5, STATUS_Y + 5);
    gfx->print("Menu");

    // Line 2: Playback info if playing
    if (state->get_is_playing()) {
        char info[32];
        strncpy(info, state->get_station_name(), sizeof(info) - 1);
        info[sizeof(info) - 1] = '\0';
        if (strlen(info) > 28) {
            info[25] = '.';
            info[26] = '.';
            info[27] = '.';
            info[28] = '\0';
        }
        gfx->setTextColor(GREEN);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(info);
    } else {
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print("Not playing");
    }

    // Line 3: BACK (left) + STOP (right)
    gfx->fillRect(0, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(YELLOW);
    gfx->setCursor(25, STATUS_Y + 43);
    gfx->print("BACK");

    gfx->fillRect(90, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(WHITE);
    gfx->setCursor(115, STATUS_Y + 43);
    gfx->print("STOP");
}

// ------------------------------------------------------------------
// Volume view
// ------------------------------------------------------------------

// Volume slider layout constants
static const int VOL_SLIDER_X = 40;
static const int VOL_SLIDER_W = 100;
static const int VOL_SLIDER_TOP = 70;
static const int VOL_SLIDER_BOTTOM = 560;
static const int VOL_SLIDER_H = VOL_SLIDER_BOTTOM - VOL_SLIDER_TOP;  // 490

/**
 * Show full volume control view
 */
void display_show_volume_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing volume view...");

    gfx->fillScreen(BLACK);

    // Title
    gfx->setTextSize(2);
    gfx->setTextColor(CYAN);
    gfx->setCursor(40, 10);
    gfx->print("Volume");

    // Draw the slider
    display_update_volume_bar(state);

    // Status bar: BACK + MUTE
    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, 180, 60, BLACK);
    gfx->setTextSize(1);

    // Line 1: Current volume as text
    gfx->setTextColor(WHITE);
    gfx->setCursor(5, STATUS_Y + 5);
    gfx->printf("Vol: %d%%", state->get_volume());

    // Line 3: BACK (left) + MUTE (right)
    gfx->fillRect(0, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(YELLOW);
    gfx->setCursor(25, STATUS_Y + 43);
    gfx->print("BACK");

    gfx->fillRect(90, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(WHITE);
    gfx->setCursor(115, STATUS_Y + 43);
    gfx->print("MUTE");

    Serial.println("[Display] Volume view complete!");
}

/**
 * Update just the volume slider bar and percentage (fast, for live dragging)
 */
void display_update_volume_bar(UIState* state) {
    if (!gfx) return;

    int vol = state->get_volume();

    // Calculate fill height (bottom-up)
    int fill_h = (int)((vol / 100.0f) * VOL_SLIDER_H);
    int fill_y = VOL_SLIDER_BOTTOM - fill_h;

    // Empty part (dark gray)
    if (fill_y > VOL_SLIDER_TOP) {
        gfx->fillRect(VOL_SLIDER_X, VOL_SLIDER_TOP, VOL_SLIDER_W,
                       fill_y - VOL_SLIDER_TOP, 0x2104);  // Dark gray
    }

    // Filled part (cyan)
    if (fill_h > 0) {
        gfx->fillRect(VOL_SLIDER_X, fill_y, VOL_SLIDER_W, fill_h, CYAN);
    }

    // Update percentage text (clear area first)
    gfx->fillRect(40, 38, 100, 24, BLACK);
    gfx->setTextSize(3);
    gfx->setTextColor(WHITE);
    // Center the text roughly
    if (vol < 10) {
        gfx->setCursor(68, 38);
    } else if (vol < 100) {
        gfx->setCursor(50, 38);
    } else {
        gfx->setCursor(32, 38);
    }
    gfx->printf("%d%%", vol);

    // Update status bar volume text
    gfx->fillRect(0, 580, 180, 15, BLACK);
    gfx->setTextSize(1);
    gfx->setTextColor(WHITE);
    gfx->setCursor(5, 585);
    gfx->printf("Vol: %d%%", vol);
}

// ------------------------------------------------------------------
// Favorites view
// ------------------------------------------------------------------

void display_show_favorites_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing favorites view...");

    favorites_render(gfx, favorites_get_page());

    // Status bar: BACK + ADD
    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, 180, 60, BLACK);
    gfx->setTextSize(1);

    // Line 1: Context
    gfx->setTextColor(CYAN);
    gfx->setCursor(5, STATUS_Y + 5);
    gfx->print("Favorites");

    // Line 2: Status text or playing info
    const char* status_text = state->get_status_text();
    if (status_text[0] != '\0') {
        gfx->setTextColor(MAGENTA);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(status_text);
    } else if (state->get_is_playing()) {
        char info[29];
        strncpy(info, state->get_station_name(), 28);
        info[28] = '\0';
        gfx->setTextColor(GREEN);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(info);
    } else {
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print("Not playing");
    }

    // Line 3: BACK (left) + ADD (right)
    gfx->fillRect(0, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(YELLOW);
    gfx->setCursor(25, STATUS_Y + 43);
    gfx->print("BACK");

    gfx->fillRect(90, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(GREEN);
    gfx->setCursor(120, STATUS_Y + 43);
    gfx->print("ADD");
}

// ------------------------------------------------------------------
// Settings view
// ------------------------------------------------------------------

void display_show_settings_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing settings view...");

    settings_render(gfx);
    display_update_status_bar_settings(state);

    Serial.println("[Display] Settings view complete!");
}

void display_update_status_bar_settings(UIState* state) {
    if (!gfx) return;

    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, 180, 60, BLACK);
    gfx->setTextSize(1);

    // Line 1: Context
    gfx->setTextColor(CYAN);
    gfx->setCursor(5, STATUS_Y + 5);
    gfx->print("Settings");

    // Line 2: Status text or playing info
    const char* status_text = state->get_status_text();
    if (status_text[0] != '\0') {
        gfx->setTextColor(MAGENTA);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(status_text);
    } else if (state->get_is_playing()) {
        char info[29];
        strncpy(info, state->get_station_name(), 28);
        info[28] = '\0';
        gfx->setTextColor(GREEN);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(info);
    } else {
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print("Not playing");
    }

    // Line 3: BACK (left) + STOP (right)
    gfx->fillRect(0, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(YELLOW);
    gfx->setCursor(25, STATUS_Y + 43);
    gfx->print("BACK");

    gfx->fillRect(90, STATUS_Y + 35, 90, 25, 0x0841);
    gfx->setTextColor(WHITE);
    gfx->setCursor(115, STATUS_Y + 43);
    gfx->print("STOP");
}

// ------------------------------------------------------------------
// Map marker at lat/lon
// ------------------------------------------------------------------

void display_draw_marker_at_latlon(float lat, float lon, UIState* state) {
    if (!gfx || !state) return;

    MapSlice& slice = state->get_current_slice();

    float lon_range = slice.lon_max - slice.lon_min;
    if (lon_range < 0) lon_range += 360.0f;

    float norm_lon = lon - slice.lon_min;
    if (norm_lon < 0) norm_lon += 360.0f;
    float norm_x = norm_lon / lon_range;
    float norm_y = (90.0f - lat) / 180.0f;

    int portrait_x = constrain((int)(norm_x * 179), 0, 179);
    int portrait_y = constrain((int)(norm_y * 579), 0, 579);

    display_draw_touch_feedback(portrait_x, portrait_y, state);
}
