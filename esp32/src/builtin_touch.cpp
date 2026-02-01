/**
 * Built-in touchscreen input for RadioWall (T-Display-S3-Long).
 *
 * Reads touch coordinates from the 640×180 built-in AMOLED touchscreen and
 * maps them to the expected 1024×600 coordinate space used by the server.
 *
 * Uses AXS15231B I2C capacitive touch controller (integrated display+touch IC).
 * Based on working LILYGO GFX_AXS15231B_Image example.
 */

#include "builtin_touch.h"
#include "config.h"
#include "display.h"
#include "Arduino_DriveBus_Library.h"
#include <Wire.h>

// T-Display-S3-Long touch controller pins
#define TOUCH_SDA 15
#define TOUCH_SCL 10
#define TOUCH_RST 16
#define TOUCH_INT 11
#define TOUCH_I2C_ADDR 0x3B

// Display dimensions
#define LCD_WIDTH 180
#define LCD_HEIGHT 640

// Touch read command (from working LILYGO example)
static const uint8_t read_touchpad_cmd[] = {0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00};

static TouchCallback _touch_callback = nullptr;
static unsigned long _last_touch_ms = 0;
static bool _initialized = false;
static volatile bool _touch_interrupt = false;

// I2C bus (using Arduino_DriveBus library like working example)
static std::shared_ptr<Arduino_IIC_DriveBus> IIC_Bus = nullptr;

// Interrupt handler
void IRAM_ATTR AXS15231_Touch_ISR() {
    _touch_interrupt = true;
}

// Helper function for I2C write (from working example)
bool IIC_WriteC8D8(uint8_t device_address, uint8_t c, uint8_t d) {
    Wire.beginTransmission(device_address);
    if (Wire.write(c) == 0) {
        return false;
    }
    if (Wire.write(d) == 0) {
        return false;
    }
    return (Wire.endTransmission() == 0);
}

void builtin_touch_init() {
    Serial.println("[Touch] Initializing built-in touchscreen...");

    // Initialize interrupt pin
    pinMode(TOUCH_INT, INPUT_PULLUP);

    // NOTE: Do NOT reset GPIO 16 here - display_init() already reset it!
    // The AXS15231B is a combined display+touch chip, so they share the reset pin.
    // Resetting again would crash the display.

    // Initialize I2C bus using Arduino_DriveBus
    IIC_Bus = std::make_shared<Arduino_HWIIC>(TOUCH_SDA, TOUCH_SCL, &Wire);
    IIC_Bus->begin();

    // Configure power management chip (from working example)
    // Disable ILIM pin and set input current limit to maximum
    IIC_WriteC8D8(0x6A, 0x00, 0B00111111);
    // Turn off BATFET without using battery
    IIC_WriteC8D8(0x6A, 0x09, 0B01100100);

    // Attach interrupt for touch events
    attachInterrupt(digitalPinToInterrupt(TOUCH_INT), AXS15231_Touch_ISR, FALLING);

    _initialized = true;
    Serial.println("[Touch] AXS15231B touch controller initialized");
    Serial.printf("[Touch] I2C: SDA=%d, SCL=%d, INT=%d, Addr=0x%02X\n",
                  TOUCH_SDA, TOUCH_SCL, TOUCH_INT, TOUCH_I2C_ADDR);
    Serial.println("[Touch] Mode: 640x180 display -> 1024x600 map coordinates");

    #if TOUCH_MAP_MODE == TOUCH_MAP_MODE_FIT
        Serial.println("[Touch] Mapping: Aspect-ratio preserving (letterbox)");
    #else
        Serial.println("[Touch] Mapping: Stretch (full screen)");
    #endif
}

void builtin_touch_set_callback(TouchCallback cb) {
    _touch_callback = cb;
}

void builtin_touch_task() {
    if (!_initialized) return;

    // Check for touch interrupt
    if (!_touch_interrupt) {
        // Also check for serial simulation (for testing)
        if (Serial.available()) {
            String line = Serial.readStringUntil('\n');
            line.trim();

            if (line.startsWith("T:")) {
                int comma = line.indexOf(',', 2);
                if (comma > 0) {
                    int map_x = line.substring(2, comma).toInt();
                    int map_y = line.substring(comma + 1).toInt();
                    Serial.printf("[Touch] Serial simulation: Map (%d, %d)\n", map_x, map_y);

                    if (_touch_callback) {
                        _touch_callback(map_x, map_y);
                    }
                }
            }
        }
        return;
    }

    // Clear interrupt flag
    _touch_interrupt = false;

    // Debounce
    unsigned long now = millis();
    if (now - _last_touch_ms < 20) {  // 20ms debounce from working example
        return;
    }
    _last_touch_ms = now;

    // Read touch data using Arduino_DriveBus
    uint8_t temp_buf[8] = {0};
    bool read_success = IIC_Bus->IIC_ReadCData_Data(
        TOUCH_I2C_ADDR,
        read_touchpad_cmd, sizeof(read_touchpad_cmd),
        temp_buf, sizeof(temp_buf)
    );

    if (!read_success) {
        static bool first_error = true;
        if (first_error) {
            Serial.println("[Touch] I2C read error");
            first_error = false;
        }
        return;
    }

    // Parse touch data (from working example)
    uint8_t fingers_number = temp_buf[1];
    uint8_t touch_event = temp_buf[2] >> 4;

    // Check for valid touch (1 finger, touch event 0x08)
    if (fingers_number != 1 || touch_event != 0x08) {
        return;
    }

    // Extract raw touch coordinates
    uint16_t touch_x = ((uint16_t)(temp_buf[4] & 0x0F) << 8) | (uint16_t)temp_buf[5];
    uint16_t touch_y = LCD_HEIGHT - (((uint16_t)(temp_buf[2] & 0x0F) << 8) | (uint16_t)temp_buf[3]);

    Serial.printf("[Touch] Raw: X=%d, Y=%d, Fingers=%d, Event=%#X\n",
                  touch_x, touch_y, fingers_number, touch_event);

    // Map 180×640 display coordinates to 1024×600 map coordinates
    int map_x, map_y;

    #if TOUCH_MAP_MODE == TOUCH_MAP_MODE_FIT
        // Preserve aspect ratio (letterbox mode)
        // The display is 180×640 (aspect 0.28:1, very tall)
        // Map is 1024×600 (aspect 1.71:1, wider)

        // Scale to fit width: 1024/180 = 5.69
        float scale = (float)TOUCH_MAX_X / (float)LCD_WIDTH;
        map_x = (int)(touch_x * scale);
        map_y = (int)(touch_y * scale);

        // Center vertically in 1024×600 space
        int scaled_height = (int)(LCD_HEIGHT * scale);
        int y_offset = (TOUCH_MAX_Y - scaled_height) / 2;
        map_y += y_offset;

    #else
        // Stretch mode - use full screen but distorts aspect ratio
        map_x = (touch_x * TOUCH_MAX_X) / LCD_WIDTH;   // 180 -> 1024
        map_y = (touch_y * TOUCH_MAX_Y) / LCD_HEIGHT;  // 640 -> 600
    #endif

    // Clamp to valid range
    if (map_x < TOUCH_MIN_X) map_x = TOUCH_MIN_X;
    if (map_x > TOUCH_MAX_X) map_x = TOUCH_MAX_X;
    if (map_y < TOUCH_MIN_Y) map_y = TOUCH_MIN_Y;
    if (map_y > TOUCH_MAX_Y) map_y = TOUCH_MAX_Y;

    Serial.printf("[Touch] Display (%d, %d) -> Map (%d, %d)\n",
                  touch_x, touch_y, map_x, map_y);

    // Visual feedback (if enabled)
    #if TOUCH_VISUAL_FEEDBACK
        display_draw_touch_feedback(touch_x, touch_y);
    #endif

    // Trigger callback
    if (_touch_callback) {
        _touch_callback(map_x, map_y);
    }
}
