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
#include "ui_state.h"
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

// Legacy callback
static TouchCallback _touch_callback = nullptr;

// Zone-based callbacks
static MapTouchCallback _map_touch_callback = nullptr;
static UIButtonCallback _ui_button_callback = nullptr;
static MenuTouchCallback _menu_touch_callback = nullptr;
static SwipeCallback _swipe_callback = nullptr;
static VolumeChangeCallback _volume_change_callback = nullptr;
static UIState* _ui_state = nullptr;

static unsigned long _last_touch_ms = 0;
static bool _initialized = false;
static volatile bool _touch_interrupt = false;

// Gesture tracking state
enum TouchZone { ZONE_MAP, ZONE_MENU, ZONE_VOLUME, ZONE_STATUS_BAR };
static bool _gesture_active = false;
static uint16_t _touch_start_x, _touch_start_y;
static uint16_t _touch_current_x, _touch_current_y;
static unsigned long _touch_start_ms = 0;
static TouchZone _touch_start_zone = ZONE_MAP;

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

void builtin_touch_set_map_callback(MapTouchCallback cb) {
    _map_touch_callback = cb;
}

void builtin_touch_set_ui_button_callback(UIButtonCallback cb) {
    _ui_button_callback = cb;
}

void builtin_touch_set_ui_state(UIState* state) {
    _ui_state = state;
}

void builtin_touch_set_menu_callback(MenuTouchCallback cb) {
    _menu_touch_callback = cb;
}

void builtin_touch_set_swipe_callback(SwipeCallback cb) {
    _swipe_callback = cb;
}

void builtin_touch_set_volume_change_callback(VolumeChangeCallback cb) {
    _volume_change_callback = cb;
}

// ------------------------------------------------------------------
// Gesture helper: fire map tap at given portrait coordinates
// ------------------------------------------------------------------
static void fire_map_tap(uint16_t portrait_x, uint16_t portrait_y) {
    if (!_ui_state || !_map_touch_callback) return;

    const int MAP_AREA_HEIGHT = 580;
    const int MAP_WIDTH = 180;

    MapSlice& slice = _ui_state->get_current_slice();

    float norm_x = portrait_x / (float)(MAP_WIDTH - 1);
    float norm_y = portrait_y / (float)(MAP_AREA_HEIGHT - 1);

    float lon_range = slice.lon_max - slice.lon_min;
    if (lon_range < 0) lon_range += 360.0f;
    float lon = slice.lon_min + norm_x * lon_range;
    float lat = 90.0f - norm_y * 180.0f;

    if (lon > 180.0f) lon -= 360.0f;
    if (lon < -180.0f) lon += 360.0f;

    int server_x = (int)((lon + 180.0f) / 360.0f * 1024.0f);
    int server_y = (int)((90.0f - lat) / 180.0f * 600.0f);

    server_x = constrain(server_x, 0, 1023);
    server_y = constrain(server_y, 0, 599);

    Serial.printf("[Touch] Tap: Portrait(%d,%d) -> Lat/Lon(%.2f,%.2f) -> Server(%d,%d)\n",
                 portrait_x, portrait_y, lat, lon, server_x, server_y);

    _map_touch_callback(server_x, server_y);

    #if TOUCH_VISUAL_FEEDBACK
        display_draw_touch_feedback(portrait_x, portrait_y, _ui_state);
    #endif
}

// ------------------------------------------------------------------
// Gesture helper: evaluate map gesture on finger UP
// ------------------------------------------------------------------
static void handle_map_gesture(unsigned long now) {
    int dx = (int)_touch_current_x - (int)_touch_start_x;
    int dy = (int)_touch_current_y - (int)_touch_start_y;
    unsigned long duration = now - _touch_start_ms;

    if (abs(dx) > 30 && abs(dx) > abs(dy) && duration < 800) {
        // Horizontal swipe
        int direction = (dx > 0) ? 1 : -1;
        Serial.printf("[Touch] Swipe %s (dx=%d, duration=%lums)\n",
                     direction > 0 ? "right" : "left", dx, duration);
        if (_swipe_callback) {
            _swipe_callback(direction);
        }
    } else if (abs(dx) < 15 && abs(dy) < 15) {
        // Small movement = tap
        fire_map_tap(_touch_start_x, _touch_start_y);
    }
    // else: ambiguous gesture, ignore
}

// ------------------------------------------------------------------
// Gesture helper: handle finger DOWN
// ------------------------------------------------------------------
static void handle_touch_down(uint16_t x, uint16_t y, unsigned long now) {
    _gesture_active = true;
    _touch_start_x = x;
    _touch_start_y = y;
    _touch_current_x = x;
    _touch_current_y = y;
    _touch_start_ms = now;

    const int MAP_AREA_HEIGHT = 580;

    // Determine zone based on position and current view
    if (y >= MAP_AREA_HEIGHT) {
        _touch_start_zone = ZONE_STATUS_BAR;
    } else if (_ui_state) {
        ViewMode mode = _ui_state->get_view_mode();
        if (mode == VIEW_MENU || mode == VIEW_FAVORITES) _touch_start_zone = ZONE_MENU;
        else if (mode == VIEW_VOLUME) _touch_start_zone = ZONE_VOLUME;
        else _touch_start_zone = ZONE_MAP;
    } else {
        _touch_start_zone = ZONE_MAP;
    }

    // No immediate action for volume - wait for tap (UP event)
}

// ------------------------------------------------------------------
// Gesture helper: handle finger CONTACT (held/moving)
// ------------------------------------------------------------------
static void handle_touch_contact(uint16_t x, uint16_t y) {
    if (!_gesture_active) return;
    _touch_current_x = x;
    _touch_current_y = y;

    // Volume is tap-based, no live drag updates
}

// ------------------------------------------------------------------
// Gesture helper: handle finger UP
// ------------------------------------------------------------------
static void handle_touch_up(unsigned long now) {
    if (!_gesture_active) return;
    _gesture_active = false;

    switch (_touch_start_zone) {
        case ZONE_MAP:
            handle_map_gesture(now);
            break;

        case ZONE_MENU:
            if (_menu_touch_callback) {
                Serial.printf("[Touch] Menu tap: (%d, %d)\n", _touch_start_x, _touch_start_y);
                _menu_touch_callback(_touch_start_x, _touch_start_y);
            }
            break;

        case ZONE_VOLUME:
            // Tap-based volume: use DOWN position (more reliable than UP coordinates)
            if (_volume_change_callback && _touch_start_y >= 70 && _touch_start_y <= 560) {
                int vol = map(_touch_start_y, 560, 70, 0, 100);
                vol = constrain(vol, 0, 100);
                Serial.printf("[Touch] Volume tap: y=%d -> %d%%\n", _touch_start_y, vol);
                _volume_change_callback(vol);
            }
            break;

        case ZONE_STATUS_BAR:
            if (_ui_button_callback) {
                if (_touch_start_x < 90) {
                    Serial.println("[Touch] Status bar: LEFT button");
                    _ui_button_callback(0);
                } else {
                    Serial.println("[Touch] Status bar: RIGHT button");
                    _ui_button_callback(1);
                }
            }
            break;
    }
}

// ------------------------------------------------------------------
// Main touch task
// ------------------------------------------------------------------
void builtin_touch_task() {
    if (!_initialized) return;

    unsigned long now = millis();

    // Timeout: if gesture active but no touch data for 200ms, treat as UP
    if (_gesture_active && (now - _last_touch_ms > 200)) {
        handle_touch_up(now);
    }

    // Check for touch interrupt
    if (!_touch_interrupt) {
        // Serial simulation (for testing)
        if (Serial.available() && Serial.peek() == 'T') {
            String line = Serial.readStringUntil('\n');
            line.trim();

            if (line.startsWith("T:")) {
                int comma = line.indexOf(',', 2);
                if (comma > 0) {
                    int map_x = line.substring(2, comma).toInt();
                    int map_y = line.substring(comma + 1).toInt();
                    Serial.printf("[Touch] Serial simulation: Map (%d, %d)\n", map_x, map_y);

                    if (_map_touch_callback) {
                        _map_touch_callback(map_x, map_y);
                    }
                }
            }
        }
        return;
    }

    // Clear interrupt flag
    _touch_interrupt = false;

    // Debounce
    if (now - _last_touch_ms < 20) {
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

    // Parse touch data (AXS15231B protocol)
    uint8_t fingers_number = temp_buf[1];
    uint8_t touch_event = temp_buf[2] >> 6;  // Upper 2 bits: 0=DOWN, 1=UP, 2=CONTACT

    // No fingers = finger lifted
    if (fingers_number == 0) {
        if (_gesture_active) {
            handle_touch_up(now);
        }
        return;
    }

    if (fingers_number != 1) return;

    // Extract raw touch coordinates (unchanged - byte mapping matches hardware orientation)
    uint16_t touch_x = ((uint16_t)(temp_buf[4] & 0x0F) << 8) | (uint16_t)temp_buf[5];
    uint16_t touch_y = LCD_HEIGHT - (((uint16_t)(temp_buf[2] & 0x0F) << 8) | (uint16_t)temp_buf[3]);

    // Handle based on event type
    // Note: Some AXS15231B firmware repeats DOWN (0) instead of sending
    // CONTACT (2) while finger is held. If already tracking, treat as CONTACT.
    switch (touch_event) {
        case 0: // DOWN - finger placed (or repeated while held)
            if (_gesture_active) {
                handle_touch_contact(touch_x, touch_y);
            } else {
                handle_touch_down(touch_x, touch_y, now);
            }
            break;

        case 2: // CONTACT - finger held/moving
            if (!_gesture_active) {
                handle_touch_down(touch_x, touch_y, now);
            } else {
                handle_touch_contact(touch_x, touch_y);
            }
            break;

        case 1: // UP - finger lifted
            handle_touch_up(now);
            break;
    }
}
