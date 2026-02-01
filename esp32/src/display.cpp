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

    // Show RadioWall splash
    gfx->setCursor(40, 300);
    gfx->setTextSize(2);
    gfx->setTextColor(CYAN);
    gfx->println("RadioWall");

    gfx->setCursor(20, 330);
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
        gfx->setCursor(40, 300);
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

void display_draw_touch_feedback(int x, int y) {
    Serial.printf("[Display] Touch feedback: (%d, %d)\n", x, y);

    // Draw a small red circle at touch location
    if (gfx && x >= 0 && x < LCD_WIDTH && y >= 0 && y < LCD_HEIGHT) {
        gfx->fillCircle(x, y, 5, RED);
    }
}

Arduino_GFX* display_get_gfx() {
    return gfx;
}
