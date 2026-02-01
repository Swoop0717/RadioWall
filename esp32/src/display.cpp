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

void display_draw_touch_feedback(int x, int y, UIState* state) {
    if (!gfx || !state) return;

    // Refresh the entire map to clear previous mark
    display_refresh_map_only(state);

    // Draw a small X marker at touch location
    if (x >= 0 && x < LCD_WIDTH && y >= 0 && y < LCD_HEIGHT) {
        int mark_size = 4;  // Half-size of the X
        gfx->drawLine(x - mark_size, y - mark_size, x + mark_size, y + mark_size, RED);
        gfx->drawLine(x - mark_size, y + mark_size, x + mark_size, y - mark_size, RED);
        Serial.printf("[Display] Touch feedback X at (%d, %d)\n", x, y);
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

    // Clear screen
    gfx->fillScreen(BLACK);

    // Portrait mode: 180 wide × 640 tall
    // Map area: 180×580 (0-580), Status bar: 180×60 (580-640)

    // === MAP AREA (0 to 580) - Full height ===
    // Map fills entire top area
    int map_x = 10;
    int map_y = 10;
    int map_w = 160;
    int map_h = 560;  // Almost full height (leaving small margins)

    gfx->fillRect(map_x, map_y, map_w, map_h, 0x0020);  // Dark blue
    gfx->drawRect(map_x-1, map_y-1, map_w+2, map_h+2, WHITE);

    // "MAP" label in center
    gfx->setTextSize(3);
    gfx->setTextColor(WHITE);
    gfx->setCursor(map_x + 50, map_y + map_h/2 - 15);
    gfx->println("MAP");

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

    // Line 1: Always show region
    MapSlice& slice = state->get_current_slice();
    gfx->setTextColor(CYAN);
    gfx->setCursor(5, STATUS_Y + 5);
    gfx->print("Region: ");
    gfx->setTextColor(YELLOW);
    gfx->println(slice.name);

    // Line 2: Station info or prompt
    if (state->get_is_playing()) {
        // Combine station and location, truncate if needed
        // Size 1 font: ~6px per char, 170px available = ~28 chars max
        char combined[64];
        snprintf(combined, sizeof(combined), "%s | %s",
                 state->get_station_name(), state->get_location());

        // Truncate if too long (28 chars for line 2, keep some margin)
        if (strlen(combined) > 28) {
            combined[25] = '.';
            combined[26] = '.';
            combined[27] = '.';
            combined[28] = '\0';
        }

        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->print(combined);
    } else {
        // Show tap prompt
        gfx->setTextColor(WHITE);
        gfx->setCursor(5, STATUS_Y + 20);
        gfx->println("Tap map to play");
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

    Serial.println("[Display] Refreshing map area (portrait mode)...");

    // Portrait mode: Clear map area only (0 to 580)
    const int MAP_H = 580;
    gfx->fillRect(0, 0, 180, MAP_H, BLACK);

    // Redraw full-height map (same as display_show_map_view but without status bar)
    int map_x = 10;
    int map_y = 10;
    int map_w = 160;
    int map_h = 560;  // Almost full height

    // Draw border
    gfx->drawRect(map_x-1, map_y-1, map_w+2, map_h+2, WHITE);

    // Get current slice and render bitmap
    MapSlice& slice = state->get_current_slice();

    // Draw the map slice bitmap at the correct position
    draw_map_slice(gfx, slice.bitmap, slice.bitmap_size, map_x, map_y);

    Serial.println("[Display] Map refresh complete");
}
