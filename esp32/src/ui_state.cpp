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
}

void UIState::cycle_slice() {
    current_slice_index = (current_slice_index + 1) % 4;
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
    strncpy(station_name, station, sizeof(station_name) - 1);
    station_name[sizeof(station_name) - 1] = '\0';

    strncpy(location, loc, sizeof(location) - 1);
    location[sizeof(location) - 1] = '\0';

    Serial.printf("[UIState] Now playing: %s - %s\n", station_name, location);
}

void UIState::set_stopped() {
    is_playing = false;
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
