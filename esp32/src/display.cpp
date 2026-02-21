/**
 * AMOLED display control for RadioWall on T-Display-S3-Long.
 *
 * Uses Arduino_GFX library with AXS15231B QSPI display controller (640x180).
 * Based on working LILYGO GFX_AXS15231B_Image example.
 */

#include "display.h"
#include "config.h"
#include "pins_config.h"
#include "theme.h"
#include "Arduino_GFX_Library.h"
#include "ui_state.h"
#include "world_map.h"
#include "menu.h"
#include "favorites.h"
#include "history.h"
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

// Helper: truncate UTF-8 string to max N bytes with "..." without splitting multi-byte chars
static void utf8_truncate(char* buf, size_t max_bytes) {
    if (strlen(buf) <= max_bytes) return;
    int i = max_bytes - 3;
    while (i > 0 && (buf[i] & 0xC0) == 0x80) i--; // back up past continuation bytes
    buf[i++] = '.';
    buf[i++] = '.';
    buf[i++] = '.';
    buf[i] = '\0';
}

// Helper: set u8g2 Unicode font for status bar text
static void set_unicode_font() {
    gfx->setFont(u8g2_font_cubic11_h_cjk);
    gfx->setUTF8Print(true);
}

// Helper: clear u8g2 font (back to default)
static void clear_unicode_font() {
    gfx->setFont((const uint8_t*)nullptr);
    gfx->setUTF8Print(false);
}

// Helper: draw a status bar icon button (icon-only, centered)
static void draw_status_icon_btn(int x, int y, int w, int h, uint16_t color,
                                  void (*draw_icon)(Arduino_GFX*, int, int, uint16_t)) {
    gfx->fillRoundRect(x, y, w, h, TH_CORNER_R, TH_BTN);
    draw_icon(gfx, x + w / 2, y + h / 2, color);
}

// Icon primitives for status bar buttons
static void icon_hamburger(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    g->fillRect(cx - 6, cy - 4, 12, 2, c);
    g->fillRect(cx - 6, cy - 1, 12, 2, c);
    g->fillRect(cx - 6, cy + 2, 12, 2, c);
}

static void icon_back_arrow(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    g->fillTriangle(cx + 5, cy - 6, cx + 5, cy + 6, cx - 5, cy, c);
}

static void icon_next_arrow(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    g->fillTriangle(cx - 5, cy - 6, cx - 5, cy + 6, cx + 5, cy, c);
}

static void icon_plus(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    g->fillRect(cx - 1, cy - 5, 3, 11, c);
    g->fillRect(cx - 5, cy - 1, 11, 3, c);
}

static void icon_x_mark(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    for (int d = -1; d <= 1; d++) {
        g->drawLine(cx - 4 + d, cy - 4, cx + 4 + d, cy + 4, c);
        g->drawLine(cx + 4 + d, cy - 4, cx - 4 + d, cy + 4, c);
    }
}

static void icon_mute(Arduino_GFX* g, int cx, int cy, uint16_t c) {
    // Small speaker with X
    g->fillRect(cx - 5, cy - 2, 4, 5, c);
    g->fillTriangle(cx - 1, cy - 5, cx - 1, cy + 5, cx + 3, cy, c);
    g->drawLine(cx + 4, cy - 3, cx + 7, cy + 3, c);
    g->drawLine(cx + 7, cy - 3, cx + 4, cy + 3, c);
}

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
    // Rotation 0 = Portrait (180x640) - STABLE WORKING CONFIGURATION
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

    // Show RadioWall splash (landscape coordinates: 640 wide x 180 tall)
    gfx->setFont(&FreeSerifBoldItalic12pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(200, 80);
    gfx->print("RadioWall");
    gfx->setFont((const GFXfont*)nullptr);

    gfx->setCursor(120, 100);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT);
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
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_ACCENT);
        gfx->setCursor(10, 50);
        gfx->print("NOW PLAYING:");
        gfx->setFont((const GFXfont*)nullptr);

        // Station name
        gfx->setCursor(10, 80);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT);
        gfx->println(station);

        // Location
        gfx->setCursor(10, 110);
        gfx->setTextColor(TH_PLAYING);
        gfx->println(location);

        // Country
        gfx->setCursor(10, 130);
        gfx->setTextColor(TH_WARNING);
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
        // Landscape coordinates: 640 wide x 180 tall
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_WARNING);
        gfx->setCursor(180, 90);
        gfx->print("Connecting...");
        gfx->setFont((const GFXfont*)nullptr);
    }
}

void display_show_wifi_portal(bool show_cancel) {
    Serial.println("[Display] Showing WiFi portal instructions...");

    if (gfx) {
        gfx->fillScreen(BLACK);

        // Title
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_ACCENT);
        gfx->setCursor(20, 60);
        gfx->print("WiFi Setup");
        gfx->setFont((const GFXfont*)nullptr);

        gfx->setTextSize(1);

        // Step 1
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, 100);
        gfx->print("1. Connect to");
        gfx->setTextColor(TH_WARNING);
        gfx->setCursor(10, 118);
        gfx->print("  \"RadioWall\"");
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, 136);
        gfx->print("  WiFi network");

        // Step 2
        gfx->setCursor(10, 170);
        gfx->print("2. Open browser");

        // IP address
        gfx->setTextColor(TH_ACCENT);
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setCursor(10, 220);
        gfx->print("192.168.4.1");
        gfx->setFont((const GFXfont*)nullptr);

        // Cancel hint (only when opened from settings)
        if (show_cancel) {
            gfx->setTextColor(TH_TEXT_SEC);
            gfx->setCursor(10, 270);
            gfx->print("Press button to cancel");
        }
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

// Draw map area using current zoom level
static void draw_current_map(UIState* state) {
    int zoom = state->get_zoom_level();
    if (zoom <= 1) {
        MapSlice& slice = state->get_current_slice();
        if (slice.bitmap && slice.bitmap_size > 0) {
            draw_map_slice(gfx, slice.bitmap, slice.bitmap_size, 0, 0);
        }
    } else {
        char path[24];
        snprintf(path, sizeof(path), "/maps/zoom%d.bin", zoom);
        if (!draw_map_from_file(gfx, path, zoom,
                                state->get_current_slice_index(),
                                state->get_zoom_col(),
                                state->get_zoom_row(), 0, 0)) {
            // Fallback: draw 1x if zoom file missing
            MapSlice& slice = state->get_current_slice();
            if (slice.bitmap && slice.bitmap_size > 0) {
                draw_map_slice(gfx, slice.bitmap, slice.bitmap_size, 0, 0);
            }
        }
    }
}

void display_show_map_view(UIState* state) {
    if (!gfx) {
        Serial.println("[Display] ERROR: gfx is null!");
        return;
    }

    Serial.println("[Display] Showing portrait map view (180x640)...");

    // Clear screen with black
    gfx->fillScreen(BLACK);

    // Draw the map slice at top-left
    draw_current_map(state);

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

    // Portrait mode: 180 wide x 640 tall
    const int STATUS_Y = 580;  // Status bar starts at y=580
    const int STATUS_H = 60;    // Status bar height

    // Clear status bar area
    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, STATUS_H, TH_BG);

    gfx->setTextSize(1);
    set_unicode_font();

    // Line 1: City, CC (idx/total) when playing, else region name
    // u8g2 font uses baseline coords: y=STATUS_Y+13 gives ~ascent(8)+5px padding
    const char* status_text = state->get_status_text();
    if (status_text[0] != '\0') {
        gfx->setTextColor(MAGENTA);
        gfx->setCursor(4, STATUS_Y + 13);
        gfx->print(status_text);
    } else if (state->get_is_playing()) {
        // Show: "City, CC (2/5)"
        const StationInfo* station = radio_get_current();
        int idx = radio_get_station_index();
        int total = radio_get_total_stations();
        char line1[48];
        if (station && total > 0) {
            snprintf(line1, sizeof(line1), "%s, %s (%d/%d)",
                     station->place, station->country, idx, total);
        } else {
            snprintf(line1, sizeof(line1), "%s", state->get_location());
        }
        utf8_truncate(line1, 26);
        gfx->setTextColor(TH_PLAYING);
        gfx->setCursor(4, STATUS_Y + 13);
        gfx->print(line1);
    } else {
        MapSlice& slice = state->get_current_slice();
        gfx->setTextColor(TH_ACCENT);
        gfx->setCursor(4, STATUS_Y + 13);
        int zoom = state->get_zoom_level();
        if (zoom > 1) {
            char zoom_label[28];
            // Compact position labels
            static const char* pos2x[] = {"NW", "NE", "SW", "SE"};
            int col = state->get_zoom_col();
            int row = state->get_zoom_row();
            if (zoom == 2) {
                snprintf(zoom_label, sizeof(zoom_label), "%s 2x %s",
                         slice.name, pos2x[col * 2 + row]);
            } else {
                snprintf(zoom_label, sizeof(zoom_label), "%s 3x [%d,%d]",
                         slice.name, col, row);
            }
            gfx->print(zoom_label);
        } else {
            gfx->print(slice.name);
        }
    }

    // Line 2: Station name or idle text
    if (state->get_is_playing() && status_text[0] == '\0') {
        char line2[48];
        strncpy(line2, state->get_station_name(), 47);
        line2[47] = '\0';
        utf8_truncate(line2, 26);
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(4, STATUS_Y + 27);
        gfx->print(line2);
    } else if (!state->get_is_playing() && status_text[0] == '\0') {
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(4, STATUS_Y + 27);
        gfx->print("Tap map to play");
    }

    clear_unicode_font();

    // Line 3: MENU and NEXT icon buttons (90px each)
    draw_status_icon_btn(0, STATUS_Y + 35, 88, 25, TH_ACCENT, icon_hamburger);
    draw_status_icon_btn(90, STATUS_Y + 35, 90, 25, TH_ACCENT, icon_next_arrow);
}

/**
 * Refresh map area only (not status bar)
 */
void display_refresh_map_only(UIState* state) {
    if (!gfx || !state) return;

    Serial.println("[Display] Refreshing map area...");

    // Clear map area (0 to 580) with black
    gfx->fillRect(0, 0, 180, 580, BLACK);

    // Draw the map using current zoom level
    draw_current_map(state);

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
 * Update status bar for menu mode (BACK icon only)
 */
void display_update_status_bar_menu(UIState* state) {
    if (!gfx) return;

    const int STATUS_Y = 580;
    const int STATUS_H = 60;

    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, STATUS_H, TH_BG);

    // Full-width BACK button
    draw_status_icon_btn(0, STATUS_Y + 18, TH_DISPLAY_W, 28, TH_ACCENT, icon_back_arrow);
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

    // Title (FreeSansBold)
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(40, FONT_SANS_ASCENT + 10);
    gfx->print("Volume");
    gfx->setFont((const GFXfont*)nullptr);

    // Draw the slider
    display_update_volume_bar(state);

    // Status bar: BACK + MUTE icons
    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, 60, TH_BG);

    draw_status_icon_btn(0, STATUS_Y + 18, 88, 28, TH_ACCENT, icon_back_arrow);
    draw_status_icon_btn(90, STATUS_Y + 18, 90, 28, TH_ACCENT, icon_mute);

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

    // Empty part (dark card color)
    if (fill_y > VOL_SLIDER_TOP) {
        gfx->fillRoundRect(VOL_SLIDER_X, VOL_SLIDER_TOP, VOL_SLIDER_W,
                           fill_y - VOL_SLIDER_TOP, TH_CORNER_R, TH_CARD);
    }

    // Filled part (accent cyan)
    if (fill_h > 0) {
        gfx->fillRoundRect(VOL_SLIDER_X, fill_y, VOL_SLIDER_W, fill_h,
                           TH_CORNER_R, TH_ACCENT);
    }

    // Update percentage text (FreeSansBold)
    gfx->fillRect(30, 38, 120, 26, TH_BG);
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT);
    // Center the text roughly
    if (vol < 10) {
        gfx->setCursor(68, 56);
    } else if (vol < 100) {
        gfx->setCursor(56, 56);
    } else {
        gfx->setCursor(44, 56);
    }
    gfx->printf("%d%%", vol);
    gfx->setFont((const GFXfont*)nullptr);
}

// ------------------------------------------------------------------
// Favorites view
// ------------------------------------------------------------------

void display_show_favorites_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing favorites view...");

    favorites_render(gfx, favorites_get_page());

    // Status bar: BACK + ADD icons
    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, 60, TH_BG);

    draw_status_icon_btn(0, STATUS_Y + 18, 88, 28, TH_ACCENT, icon_back_arrow);
    draw_status_icon_btn(90, STATUS_Y + 18, 90, 28, TH_ACCENT, icon_plus);
}

// ------------------------------------------------------------------
// History view
// ------------------------------------------------------------------

void display_show_history_view(UIState* state) {
    if (!gfx) return;

    Serial.println("[Display] Showing history view...");

    history_render(gfx, history_get_page());

    // Status bar: BACK + CLEAR icons
    const int STATUS_Y = 580;
    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, 60, TH_BG);

    draw_status_icon_btn(0, STATUS_Y + 18, 88, 28, TH_ACCENT, icon_back_arrow);
    draw_status_icon_btn(90, STATUS_Y + 18, 90, 28, TH_DANGER, icon_x_mark);
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
    gfx->fillRect(0, STATUS_Y, TH_DISPLAY_W, 60, TH_BG);

    // Full-width BACK button
    draw_status_icon_btn(0, STATUS_Y + 18, TH_DISPLAY_W, 28, TH_ACCENT, icon_back_arrow);
}

void display_show_settings_wifi_view(UIState* state) {
    if (!gfx) return;
    settings_wifi_render(gfx);
    display_update_status_bar_settings(state);
}

void display_show_settings_devices_view(UIState* state) {
    if (!gfx) return;
    settings_devices_render(gfx);
    display_update_status_bar_settings(state);
}

// ------------------------------------------------------------------
// Map marker at lat/lon
// ------------------------------------------------------------------

void display_draw_marker_at_latlon(float lat, float lon, UIState* state) {
    if (!gfx || !state) return;

    // Use zoom-aware geographic bounds
    float lon_min = state->get_view_lon_min();
    float lon_max = state->get_view_lon_max();
    float lat_max = state->get_view_lat_max();
    float lat_min = state->get_view_lat_min();

    float lon_range = lon_max - lon_min;
    if (lon_range < 0) lon_range += 360.0f;

    float norm_lon = lon - lon_min;
    if (norm_lon < 0) norm_lon += 360.0f;
    float norm_x = norm_lon / lon_range;
    float norm_y = (lat_max - lat) / (lat_max - lat_min);

    // Only draw if marker is within current view
    if (norm_x < 0.0f || norm_x > 1.0f || norm_y < 0.0f || norm_y > 1.0f) return;

    int portrait_x = constrain((int)(norm_x * 179), 0, 179);
    int portrait_y = constrain((int)(norm_y * 579), 0, 579);

    display_draw_touch_feedback(portrait_x, portrait_y, state);
}
