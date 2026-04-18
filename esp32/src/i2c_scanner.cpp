/**
 * I2C Scanner for Heltec Vision Master E213
 *
 * Scans common I2C pin combinations to find devices.
 * Looking for SY6970 PMU at address 0x6A.
 *
 * Flash: pio run -e i2c-scan -t upload
 * Monitor: pio device monitor
 */

#ifdef I2C_SCANNER

#include <Arduino.h>
#include <Wire.h>

struct PinPair {
    int sda;
    int scl;
    const char* label;
};

// Common I2C pin combinations to try
static PinPair pin_pairs[] = {
    {17, 18, "GPIO 17/18 (Heltec default?)"},
    {15, 10, "GPIO 15/10 (T-Display-S3-Long)"},
    {41, 42, "GPIO 41/42 (ESP32-S3 default)"},
    {47, 48, "GPIO 47/48 (alt)"},
    {43, 44, "GPIO 43/44 (UART pins)"},
    {6, 4, "GPIO 6/4 (E-Ink SPI pins, unlikely)"},
};

static void scan_bus(int sda, int scl, const char* label) {
    Serial.printf("\n--- Scanning I2C: SDA=%d, SCL=%d (%s) ---\n", sda, scl, label);

    Wire.end();
    Wire.begin(sda, scl);
    delay(100);

    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        uint8_t error = Wire.endTransmission();

        if (error == 0) {
            Serial.printf("  FOUND device at 0x%02X", addr);
            if (addr == 0x6A) Serial.print(" *** SY6970 PMU! ***");
            if (addr == 0x3C) Serial.print(" (OLED/display?)");
            if (addr == 0x3B) Serial.print(" (touch controller?)");
            if (addr == 0x50) Serial.print(" (EEPROM?)");
            if (addr == 0x68 || addr == 0x69) Serial.print(" (IMU?)");
            Serial.println();
            found++;
        }
    }

    if (found == 0) {
        Serial.println("  No devices found on this bus");
    } else {
        Serial.printf("  %d device(s) found\n", found);
    }
}

void setup() {
    Serial.begin(115200);
    delay(2000);

    Serial.println("=== I2C Scanner for Heltec Vision Master E213 ===");
    Serial.println("Looking for SY6970 PMU at 0x6A...");

    // Enable VExt (GPIO 18) — powers peripherals on Heltec boards
    pinMode(18, OUTPUT);
    digitalWrite(18, HIGH);
    delay(100);
    Serial.println("VExt (GPIO 18) enabled");

    for (int i = 0; i < sizeof(pin_pairs) / sizeof(pin_pairs[0]); i++) {
        scan_bus(pin_pairs[i].sda, pin_pairs[i].scl, pin_pairs[i].label);
    }

    Serial.println("\n=== Scan complete ===");
    Serial.println("If SY6970 found: OTG 5V boost possible (same as T-Display)");
    Serial.println("If NOT found: need external 5V for IR touch frame");
}

void loop() {
    delay(10000);
    Serial.println("(scan complete, reset to re-run)");
}

#endif // I2C_SCANNER
