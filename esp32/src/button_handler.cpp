/**
 * Button Handler Implementation
 */

#include "button_handler.h"
#include "pins_config.h"

// Button pins
#define BUTTON_BAND_CYCLE PIN_BUTTON_1  // GPIO 0
#define BUTTON_STOP       PIN_BUTTON_2  // GPIO 21 (may conflict with TFT_QSPI_D2)

// Debounce timing
#define DEBOUNCE_MS 200

// Button state
static ButtonCallback _band_cycle_callback = nullptr;
static ButtonCallback _stop_callback = nullptr;

static bool _button1_last_state = HIGH;
static bool _button2_last_state = HIGH;
static unsigned long _button1_last_change = 0;
static unsigned long _button2_last_change = 0;

void button_init() {
    Serial.println("[Button] Initializing physical buttons...");

    // Configure GPIO pins as INPUT_PULLUP
    pinMode(BUTTON_BAND_CYCLE, INPUT_PULLUP);

    // GPIO 21 DISABLED - conflicts with TFT_QSPI_D2 and causes crashes
    // Use touch-based STOP button in status bar instead
    // pinMode(BUTTON_STOP, INPUT_PULLUP);

    Serial.printf("[Button] Band cycle: GPIO %d (active)\n", BUTTON_BAND_CYCLE);
    Serial.println("[Button] Stop button (GPIO 21) DISABLED - use touch instead");
}

void button_set_band_cycle_callback(ButtonCallback cb) {
    _band_cycle_callback = cb;
}

void button_set_stop_callback(ButtonCallback cb) {
    _stop_callback = cb;
}

void button_task() {
    unsigned long now = millis();

    // Button 1: Band Cycle
    bool button1_state = digitalRead(BUTTON_BAND_CYCLE);
    if (button1_state != _button1_last_state) {
        _button1_last_change = now;
        _button1_last_state = button1_state;
    }

    // Trigger on button release after debounce period
    if (button1_state == HIGH && _button1_last_state == HIGH) {
        if ((now - _button1_last_change) > DEBOUNCE_MS) {
            if (_button1_last_state != button1_state) {
                // Button was pressed and released
                if (_band_cycle_callback) {
                    Serial.println("[Button] Band cycle button pressed");
                    _band_cycle_callback();
                }
                _button1_last_state = button1_state;
            }
        }
    }

    // Actually, let me simplify this - just detect LOW state with debounce
    static bool button1_triggered = false;
    if (button1_state == LOW) {
        if (!button1_triggered && (now - _button1_last_change) > DEBOUNCE_MS) {
            if (_band_cycle_callback) {
                Serial.println("[Button] Band cycle button pressed");
                _band_cycle_callback();
            }
            button1_triggered = true;
            _button1_last_change = now;
        }
    } else {
        button1_triggered = false;
    }

    // Button 2: Stop - DISABLED due to GPIO 21 conflict with TFT_QSPI_D2
    // Use touch-based stop button in status bar instead
    /*
    bool button2_state = digitalRead(BUTTON_STOP);
    static bool button2_triggered = false;
    static unsigned long button2_last_press = 0;

    if (button2_state == LOW) {
        if (!button2_triggered && (now - button2_last_press) > DEBOUNCE_MS) {
            if (_stop_callback) {
                Serial.println("[Button] Stop button pressed");
                _stop_callback();
            }
            button2_triggered = true;
            button2_last_press = now;
        }
    } else {
        button2_triggered = false;
    }
    */
}
