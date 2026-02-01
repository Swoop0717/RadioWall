/**
 * AMOLED display control for RadioWall on T-Display-S3-Long.
 *
 * Shows "Now Playing" information on the 640x180 AMOLED display.
 * Handles brightness dimming after inactivity.
 *
 * NOTE: This uses TFT_eSPI directly. For a more polished UI, consider
 * migrating to LVGL (already in platformio.ini dependencies).
 */

#include "display.h"
#include "config.h"

#include <TFT_eSPI.h>

static TFT_eSPI tft = TFT_eSPI();

static unsigned long _last_activity = 0;
static bool _dimmed = false;

// Current display state
static char _station[128] = "";
static char _location[128] = "";
static char _country[8] = "";
static char _status[32] = "idle";

// Colors
#define BG_COLOR      TFT_BLACK
#define TEXT_COLOR    TFT_WHITE
#define ACCENT_COLOR  0x07FF  // Cyan
#define DIM_COLOR     0x4208  // Dark gray
#define STATUS_COLOR  0xFDA0  // Orange

// Layout for 640x180 display (landscape)
#define MARGIN_X      20
#define STATION_Y     30
#define LOCATION_Y    90
#define STATUS_Y      140

// ------------------------------------------------------------------
// Brightness control
// ------------------------------------------------------------------

static void set_brightness(uint8_t level) {
    // T-Display-S3-Long uses GPIO15 for display power
    // Brightness is controlled via analogWrite or display command
    analogWrite(LCD_POWER_PIN, level);
}

// ------------------------------------------------------------------
// Drawing helpers
// ------------------------------------------------------------------

static void draw_screen() {
    tft.fillScreen(BG_COLOR);

    if (strlen(_station) > 0) {
        // Station name (large)
        tft.setTextColor(TEXT_COLOR, BG_COLOR);
        tft.setTextSize(3);
        tft.setTextDatum(TL_DATUM);
        tft.drawString(_station, MARGIN_X, STATION_Y, 2);

        // Location + country
        tft.setTextColor(ACCENT_COLOR, BG_COLOR);
        tft.setTextSize(2);
        char loc_buf[160];
        if (strlen(_country) > 0) {
            snprintf(loc_buf, sizeof(loc_buf), "%s, %s", _location, _country);
        } else {
            snprintf(loc_buf, sizeof(loc_buf), "%s", _location);
        }
        tft.drawString(loc_buf, MARGIN_X, LOCATION_Y, 2);
    } else {
        // No station - show waiting message
        tft.setTextColor(DIM_COLOR, BG_COLOR);
        tft.setTextSize(2);
        tft.setTextDatum(MC_DATUM);
        tft.drawString("Touch the map...", tft.width() / 2, tft.height() / 2, 2);
    }

    // Status bar at bottom
    tft.setTextColor(STATUS_COLOR, BG_COLOR);
    tft.setTextSize(1);
    tft.setTextDatum(TL_DATUM);
    tft.drawString(_status, MARGIN_X, STATUS_Y, 2);
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

void display_init() {
    // Enable display power (required when on battery)
    pinMode(LCD_POWER_PIN, OUTPUT);
    digitalWrite(LCD_POWER_PIN, HIGH);

    tft.init();
    tft.setRotation(1);  // Landscape
    tft.fillScreen(BG_COLOR);

    set_brightness(DISPLAY_BRIGHTNESS_NORMAL);
    _last_activity = millis();
    _dimmed = false;

    // Show boot screen
    tft.setTextColor(ACCENT_COLOR, BG_COLOR);
    tft.setTextSize(3);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("RadioWall", tft.width() / 2, tft.height() / 2 - 20, 2);
    tft.setTextColor(DIM_COLOR, BG_COLOR);
    tft.setTextSize(1);
    tft.drawString("Connecting...", tft.width() / 2, tft.height() / 2 + 30, 2);

    Serial.println("[Display] Initialized");
}

void display_loop() {
    // Handle dimming after timeout
    unsigned long idle_seconds = (millis() - _last_activity) / 1000;

    if (!_dimmed && idle_seconds >= DISPLAY_TIMEOUT_SECONDS) {
        set_brightness(DISPLAY_BRIGHTNESS_DIM);
        _dimmed = true;
    }
}

void display_show_nowplaying(const char* station, const char* location, const char* country) {
    strncpy(_station, station, sizeof(_station) - 1);
    strncpy(_location, location, sizeof(_location) - 1);
    strncpy(_country, country, sizeof(_country) - 1);
    strncpy(_status, "Playing", sizeof(_status) - 1);

    draw_screen();
    display_wake();
}

void display_show_status(const char* status) {
    strncpy(_status, status, sizeof(_status) - 1);
    draw_screen();
}

void display_show_connecting() {
    _station[0] = '\0';
    _location[0] = '\0';
    _country[0] = '\0';
    strncpy(_status, "Connecting...", sizeof(_status) - 1);
    draw_screen();
}

void display_wake() {
    _last_activity = millis();
    if (_dimmed) {
        set_brightness(DISPLAY_BRIGHTNESS_NORMAL);
        _dimmed = false;
    }
}
