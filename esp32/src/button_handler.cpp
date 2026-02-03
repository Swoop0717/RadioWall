/**
 * Button Handler Implementation
 *
 * Single button (GPIO 0) with multi-action support:
 * - Short press (<800ms): Cycle map region
 * - Long press (>800ms): STOP playback
 * - Double-tap (<400ms between presses): NEXT station
 */

#include "button_handler.h"
#include "pins_config.h"

// Button pin
#define BUTTON_PIN PIN_BUTTON_1  // GPIO 0

// Timing thresholds (milliseconds)
#define DEBOUNCE_MS       50    // Minimum press time to register
#define LONG_PRESS_MS     800   // Hold time for long press
#define DOUBLE_TAP_MS     400   // Max gap between taps for double-tap

// Callbacks
static ButtonCallback _region_cycle_callback = nullptr;  // Short press
static ButtonCallback _stop_callback = nullptr;          // Long press
static ButtonCallback _next_callback = nullptr;          // Double-tap

// Button state machine
enum ButtonState {
    BTN_IDLE,           // Waiting for press
    BTN_PRESSED,        // Button is down, timing hold duration
    BTN_WAIT_DOUBLE,    // Released after short press, waiting for possible second tap
    BTN_LONG_FIRED      // Long press already triggered, waiting for release
};

static ButtonState _state = BTN_IDLE;
static unsigned long _press_start = 0;      // When button was pressed
static unsigned long _release_time = 0;     // When button was released (for double-tap)
static bool _last_reading = HIGH;           // Previous digitalRead
static unsigned long _last_change = 0;      // For debouncing

void button_init() {
    Serial.println("[Button] Initializing...");
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    Serial.printf("[Button] GPIO %d: Short=Region, Long=STOP, Double=NEXT\n", BUTTON_PIN);
}

void button_set_band_cycle_callback(ButtonCallback cb) {
    _region_cycle_callback = cb;
}

void button_set_stop_callback(ButtonCallback cb) {
    _stop_callback = cb;
}

void button_set_next_callback(ButtonCallback cb) {
    _next_callback = cb;
}

void button_task() {
    unsigned long now = millis();
    bool reading = digitalRead(BUTTON_PIN);

    // Debounce: ignore changes within DEBOUNCE_MS
    if (reading != _last_reading) {
        _last_change = now;
        _last_reading = reading;
        return;  // Wait for stable reading
    }

    if (now - _last_change < DEBOUNCE_MS) {
        return;  // Still bouncing
    }

    bool pressed = (reading == LOW);  // Active low with pullup

    switch (_state) {
        case BTN_IDLE:
            if (pressed) {
                _press_start = now;
                _state = BTN_PRESSED;
            }
            break;

        case BTN_PRESSED:
            if (!pressed) {
                // Button released - check if it was a short press
                unsigned long hold_time = now - _press_start;
                if (hold_time < LONG_PRESS_MS) {
                    // Short press - wait for possible double-tap
                    _release_time = now;
                    _state = BTN_WAIT_DOUBLE;
                } else {
                    // Long press already fired, just go idle
                    _state = BTN_IDLE;
                }
            } else {
                // Still held - check for long press
                unsigned long hold_time = now - _press_start;
                if (hold_time >= LONG_PRESS_MS && _state != BTN_LONG_FIRED) {
                    // Long press detected!
                    Serial.println("[Button] Long press -> STOP");
                    if (_stop_callback) _stop_callback();
                    _state = BTN_LONG_FIRED;
                }
            }
            break;

        case BTN_WAIT_DOUBLE:
            if (pressed) {
                // Second press within window - it's a double-tap!
                Serial.println("[Button] Double-tap -> NEXT");
                if (_next_callback) _next_callback();
                _state = BTN_PRESSED;  // Track this press too
                _press_start = now;
            } else if (now - _release_time >= DOUBLE_TAP_MS) {
                // Timeout - it was just a single short press
                Serial.println("[Button] Short press -> Region cycle");
                if (_region_cycle_callback) _region_cycle_callback();
                _state = BTN_IDLE;
            }
            break;

        case BTN_LONG_FIRED:
            if (!pressed) {
                // Button released after long press
                _state = BTN_IDLE;
            }
            break;
    }
}
