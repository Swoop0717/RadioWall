/**
 * Physical Button Handler for RadioWall
 *
 * Manages GPIO buttons with debouncing.
 * - Button 1 (GPIO 0): Cycle latitude band
 * - Button 2 (GPIO 21): Stop playback
 */

#ifndef BUTTON_HANDLER_H
#define BUTTON_HANDLER_H

#include <Arduino.h>

// Button callback types
typedef void (*ButtonCallback)();

// Initialize button GPIOs
void button_init();

// Set callbacks
void button_set_band_cycle_callback(ButtonCallback cb);
void button_set_stop_callback(ButtonCallback cb);

// Call in main loop
void button_task();

#endif // BUTTON_HANDLER_H
