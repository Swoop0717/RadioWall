/**
 * Physical Button Handler for RadioWall
 *
 * Single button (GPIO 0) with multi-action support:
 * - Short press: Cycle map region
 * - Long press (>800ms): STOP playback
 * - Double-tap (<400ms): NEXT station
 *
 * Note: Button 2 (GPIO 21) disabled - conflicts with display data line
 */

#ifndef BUTTON_HANDLER_H
#define BUTTON_HANDLER_H

#include <Arduino.h>

// Button callback types
typedef void (*ButtonCallback)();

// Initialize button GPIO
void button_init();

// Set callbacks for each action
void button_set_band_cycle_callback(ButtonCallback cb);  // Short press
void button_set_stop_callback(ButtonCallback cb);         // Long press
void button_set_next_callback(ButtonCallback cb);         // Double-tap

// Call in main loop
void button_task();

#endif // BUTTON_HANDLER_H
