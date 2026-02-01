/**
 * UI State Management for RadioWall
 *
 * Manages vertical map slices, current slice selection, and playback state.
 */

#ifndef UI_STATE_H
#define UI_STATE_H

#include <Arduino.h>

// Vertical map slice definition (longitude-based)
struct MapSlice {
    const char* name;       // "Americas"
    const char* label;      // "-150° to -30°"
    float lon_min;          // Minimum longitude (degrees)
    float lon_max;          // Maximum longitude (degrees)
    const uint8_t* bitmap;  // Pointer to PROGMEM bitmap data
    size_t bitmap_size;     // Size of compressed bitmap
};

// UI state manager
class UIState {
private:
    MapSlice slices[4];
    int current_slice_index;
    bool is_playing;
    char station_name[64];
    char location[64];

public:
    UIState();

    // Slice navigation
    void cycle_slice();
    MapSlice& get_current_slice();
    int get_current_slice_index() const;

    // Playback state
    void set_playing(const char* station, const char* location);
    void set_stopped();
    bool get_is_playing() const;
    const char* get_station_name() const;
    const char* get_location() const;
};

#endif // UI_STATE_H
