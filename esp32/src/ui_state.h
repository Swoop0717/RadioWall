/**
 * UI State Management for RadioWall
 *
 * Manages vertical map slices, current slice selection, and playback state.
 */

#ifndef UI_STATE_H
#define UI_STATE_H

#include <Arduino.h>

// View mode (which screen is displayed)
enum ViewMode {
    VIEW_MAP,
    VIEW_MENU,
    VIEW_VOLUME,
    VIEW_FAVORITES
};

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
    char status_text[32];
    ViewMode _view_mode;
    int _volume;
    bool _paused;
    int _sleep_timer_minutes;  // 0 = off
    float _marker_lat, _marker_lon;
    bool _has_marker;

public:
    UIState();

    // Slice navigation
    void cycle_slice();
    void cycle_slice_reverse();
    MapSlice& get_current_slice();
    int get_current_slice_index() const;

    // Playback state
    void set_playing(const char* station, const char* location);
    void set_stopped();
    bool get_is_playing() const;
    const char* get_station_name() const;
    const char* get_location() const;

    // Temporary status text (shown on status bar line 2, cleared by set_playing/set_stopped)
    void set_status_text(const char* text);
    const char* get_status_text() const;

    // View mode
    ViewMode get_view_mode() const;
    void set_view_mode(ViewMode mode);
    bool is_menu_active() const;

    // Volume
    void set_volume(int vol);
    int get_volume() const;

    // Pause
    void set_paused(bool paused);
    bool is_paused() const;

    // Sleep timer
    void set_sleep_timer(int minutes);
    int get_sleep_timer() const;

    // Map marker (for favorites and play-from-map)
    void set_marker(float lat, float lon);
    void clear_marker();
    bool has_marker() const;
    float get_marker_lat() const;
    float get_marker_lon() const;

    // Slice helpers
    int slice_index_for_lon(float lon) const;
    void set_slice_index(int idx);
};

#endif // UI_STATE_H
