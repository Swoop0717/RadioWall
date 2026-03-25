/**
 * E-Ink Display Test for RadioWall Prototype 3
 *
 * Heltec Vision Master E213: 250x122 pixels, SSD1680, B&W
 * Pins auto-configured by heltec-eink-modules library.
 *
 * Usage:
 *   pio run -e eink -t upload
 *   pio device monitor
 */

#ifdef EINK_DISPLAY

#include <Arduino.h>
#include "heltec-eink-modules.h"

EInkDisplay_VisionMasterE213 display;

// Layout constants (landscape: 250 wide x 122 tall)
#define SCREEN_W 250
#define SCREEN_H 122

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("[EInk] RadioWall E-Ink Test");

    // Landscape mode (connector on left)
    display.landscape();

    // Full refresh: show startup screen
    display.clear();
    display.setTextColor(BLACK);
    display.setTextSize(2);
    display.setCursor(10, 10);
    display.print("RadioWall");

    display.setTextSize(1);
    display.setCursor(10, 40);
    display.print("Prototype 3 - E-Ink");

    display.setCursor(10, 60);
    display.print("250 x 122 pixels");

    display.setCursor(10, 80);
    display.print("Heltec Vision Master E213");

    display.setCursor(10, 105);
    display.print("Ready.");

    display.update();

    Serial.println("[EInk] Startup screen drawn");
    Serial.println("[EInk] Send 'P:Station Name|City, CC' to test now-playing");
    Serial.println("[EInk] Send 'C' to clear display");
}

// Draw a "Now Playing" screen (partial refresh — no flicker)
void draw_now_playing(const char* station, const char* location) {
    Serial.printf("[EInk] Now Playing: %s @ %s\n", station, location);

    display.fastmodeOn();
    display.clearMemory();
    display.setTextColor(BLACK);

    // Header line
    display.setTextSize(1);
    display.setCursor(10, 8);
    display.print("NOW PLAYING");

    // Divider line
    display.drawLine(10, 22, SCREEN_W - 10, 22, BLACK);

    // Station name (large)
    display.setTextSize(2);
    display.setCursor(10, 32);
    // Truncate if too long for display
    char truncated[22];
    strncpy(truncated, station, 21);
    truncated[21] = '\0';
    display.print(truncated);

    // Location (medium)
    display.setTextSize(1);
    display.setCursor(10, 65);
    display.print(location);

    // Bottom divider
    display.drawLine(10, 90, SCREEN_W - 10, 90, BLACK);

    // Status bar
    display.setCursor(10, 100);
    display.print("Touch map to change station");

    display.update();
}

void draw_stopped() {
    display.clear();
    display.setTextColor(BLACK);

    display.setTextSize(2);
    display.setCursor(10, 30);
    display.print("RadioWall");

    display.setTextSize(1);
    display.setCursor(10, 65);
    display.print("Touch the map to play");
    display.setCursor(10, 80);
    display.print("a radio station");

    display.update();
}

void loop() {
    // Serial commands for testing
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();

        if (line.startsWith("P:")) {
            // P:Station Name|City, CC
            int sep = line.indexOf('|', 2);
            if (sep > 0) {
                String station = line.substring(2, sep);
                String location = line.substring(sep + 1);
                draw_now_playing(station.c_str(), location.c_str());
            } else {
                draw_now_playing(line.substring(2).c_str(), "Unknown");
            }
        } else if (line == "C") {
            draw_stopped();
        }
    }

    delay(50);
}

#endif // EINK_DISPLAY
