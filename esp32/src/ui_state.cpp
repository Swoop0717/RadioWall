/**
 * UI State Management Implementation
 */

#include "ui_state.h"
#include "world_map.h"  // For bitmap data pointers

UIState::UIState() {
    // Initialize 4 vertical longitude slices
    // Slice 0: Americas
    slices[0] = {
        "Americas",
        "-150° to -30°",
        -150.0f,  // lon_min
        -30.0f,   // lon_max
        map_slice_americas,
        map_slice_americas_size
    };

    // Slice 1: Europe/Africa (DEFAULT - most stations)
    slices[1] = {
        "Europe/Africa",
        "-30° to 60°",
        -30.0f,
        60.0f,
        map_slice_europe_africa,
        map_slice_europe_africa_size
    };

    // Slice 2: Asia
    slices[2] = {
        "Asia",
        "60° to 150°",
        60.0f,
        150.0f,
        map_slice_asia,
        map_slice_asia_size
    };

    // Slice 3: Pacific
    slices[3] = {
        "Pacific",
        "150° to -150°",
        150.0f,
        -150.0f,  // Wraps around
        map_slice_pacific,
        map_slice_pacific_size
    };

    // Start with Europe/Africa slice (index 1)
    current_slice_index = 1;

    // Initial playback state
    is_playing = false;
    station_name[0] = '\0';
    location[0] = '\0';
    status_text[0] = '\0';
    _view_mode = VIEW_MAP;
    _volume = 50;
    _paused = false;
    _sleep_timer_minutes = 0;
}

void UIState::cycle_slice() {
    current_slice_index = (current_slice_index + 1) % 4;
    Serial.printf("[UIState] Cycled to slice %d: %s\n",
                  current_slice_index,
                  slices[current_slice_index].name);
}

void UIState::cycle_slice_reverse() {
    current_slice_index = (current_slice_index + 3) % 4;  // +3 mod 4 = -1
    Serial.printf("[UIState] Cycled to slice %d: %s\n",
                  current_slice_index,
                  slices[current_slice_index].name);
}

MapSlice& UIState::get_current_slice() {
    return slices[current_slice_index];
}

int UIState::get_current_slice_index() const {
    return current_slice_index;
}

void UIState::set_playing(const char* station, const char* loc) {
    is_playing = true;
    _paused = false;
    status_text[0] = '\0';
    strncpy(station_name, station, sizeof(station_name) - 1);
    station_name[sizeof(station_name) - 1] = '\0';

    strncpy(location, loc, sizeof(location) - 1);
    location[sizeof(location) - 1] = '\0';

    Serial.printf("[UIState] Now playing: %s - %s\n", station_name, location);
}

void UIState::set_stopped() {
    is_playing = false;
    _paused = false;
    status_text[0] = '\0';
    Serial.println("[UIState] Playback stopped");
}

bool UIState::get_is_playing() const {
    return is_playing;
}

const char* UIState::get_station_name() const {
    return station_name;
}

const char* UIState::get_location() const {
    return location;
}

void UIState::set_status_text(const char* text) {
    strncpy(status_text, text, sizeof(status_text) - 1);
    status_text[sizeof(status_text) - 1] = '\0';
}

const char* UIState::get_status_text() const {
    return status_text;
}

ViewMode UIState::get_view_mode() const {
    return _view_mode;
}

void UIState::set_view_mode(ViewMode mode) {
    _view_mode = mode;
    const char* name = "MAP";
    if (mode == VIEW_MENU) name = "MENU";
    else if (mode == VIEW_VOLUME) name = "VOLUME";
    Serial.printf("[UIState] View mode: %s\n", name);
}

bool UIState::is_menu_active() const {
    return _view_mode == VIEW_MENU || _view_mode == VIEW_VOLUME;
}

void UIState::set_volume(int vol) {
    _volume = constrain(vol, 0, 100);
}

int UIState::get_volume() const {
    return _volume;
}

void UIState::set_paused(bool paused) {
    _paused = paused;
    Serial.printf("[UIState] %s\n", paused ? "Paused" : "Resumed");
}

bool UIState::is_paused() const {
    return _paused;
}

void UIState::set_sleep_timer(int minutes) {
    _sleep_timer_minutes = minutes;
    if (minutes > 0) {
        Serial.printf("[UIState] Sleep timer: %d min\n", minutes);
    } else {
        Serial.println("[UIState] Sleep timer: off");
    }
}

int UIState::get_sleep_timer() const {
    return _sleep_timer_minutes;
}
