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
    wiim_title[0] = '\0';
    wiim_artist[0] = '\0';
    _view_mode = VIEW_MAP;
    _volume = 50;
    _paused = false;
    _sleep_timer_minutes = 0;
    _marker_lat = 0;
    _marker_lon = 0;
    _has_marker = false;
    _zoom_level = 1;
    _zoom_col = 0;
    _zoom_row = 0;
}

void UIState::cycle_slice() {
    current_slice_index = (current_slice_index + 1) % 4;
    _zoom_col = 0;
    _zoom_row = 0;
    Serial.printf("[UIState] Cycled to slice %d: %s\n",
                  current_slice_index,
                  slices[current_slice_index].name);
}

void UIState::cycle_slice_reverse() {
    current_slice_index = (current_slice_index + 3) % 4;  // +3 mod 4 = -1
    _zoom_col = 0;
    _zoom_row = 0;
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
    wiim_title[0] = '\0';
    wiim_artist[0] = '\0';
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
    wiim_title[0] = '\0';
    wiim_artist[0] = '\0';
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
    else if (mode == VIEW_FAVORITES) name = "FAVORITES";
    else if (mode == VIEW_SETTINGS) name = "SETTINGS";
    Serial.printf("[UIState] View mode: %s\n", name);
}

bool UIState::is_menu_active() const {
    return _view_mode == VIEW_MENU || _view_mode == VIEW_VOLUME || _view_mode == VIEW_FAVORITES || _view_mode == VIEW_HISTORY || _view_mode == VIEW_SETTINGS;
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

void UIState::set_marker(float lat, float lon) {
    _marker_lat = lat;
    _marker_lon = lon;
    _has_marker = true;
}

void UIState::clear_marker() {
    _has_marker = false;
}

bool UIState::has_marker() const {
    return _has_marker;
}

float UIState::get_marker_lat() const {
    return _marker_lat;
}

float UIState::get_marker_lon() const {
    return _marker_lon;
}

void UIState::set_wiim_metadata(const char* title, const char* artist) {
    strncpy(wiim_title, title, sizeof(wiim_title) - 1);
    wiim_title[sizeof(wiim_title) - 1] = '\0';
    strncpy(wiim_artist, artist, sizeof(wiim_artist) - 1);
    wiim_artist[sizeof(wiim_artist) - 1] = '\0';
}

const char* UIState::get_wiim_title() const {
    return wiim_title;
}

const char* UIState::get_wiim_artist() const {
    return wiim_artist;
}

int UIState::slice_index_for_lon(float lon) const {
    if (lon >= -150 && lon < -30) return 0;   // Americas
    if (lon >= -30 && lon < 60) return 1;     // Europe/Africa
    if (lon >= 60 && lon < 150) return 2;     // Asia
    return 3;                                  // Pacific
}

void UIState::set_slice_index(int idx) {
    if (idx >= 0 && idx < 4) {
        current_slice_index = idx;
        _zoom_col = 0;
        _zoom_row = 0;
        Serial.printf("[UIState] Slice set to %d: %s\n",
                      current_slice_index, slices[current_slice_index].name);
    }
}

// ------------------------------------------------------------------
// Zoom
// ------------------------------------------------------------------

void UIState::set_zoom_level(int level) {
    if (level < 1) level = 1;
    if (level > 5) level = 5;
    _zoom_level = level;
    _zoom_col = 0;
    _zoom_row = 0;
    Serial.printf("[UIState] Zoom: %dx\n", _zoom_level);
}

void UIState::set_zoom_centered(int new_level, float lat, float lon) {
    if (new_level < 1) new_level = 1;
    if (new_level > 5) new_level = 5;

    // Pick the slice containing this longitude
    current_slice_index = slice_index_for_lon(lon);

    if (new_level == 1) {
        _zoom_level = 1;
        _zoom_col = 0;
        _zoom_row = 0;
        Serial.printf("[UIState] Zoom 1x, slice=%d\n", current_slice_index);
        return;
    }

    _zoom_level = new_level;

    // Find column: where does lon fall within the slice's longitude range?
    const MapSlice& s = slices[current_slice_index];
    float range = s.lon_max - s.lon_min;
    if (range < 0) range += 360.0f;  // Pacific wrapping
    float lon_offset = lon - s.lon_min;
    if (lon_offset < 0) lon_offset += 360.0f;
    _zoom_col = constrain((int)(lon_offset / range * new_level), 0, new_level - 1);

    // Find row: lat mapped to rows (90° at top, -90° at bottom)
    float norm_lat = (90.0f - lat) / 180.0f;  // 0.0 = north pole, 1.0 = south pole
    _zoom_row = constrain((int)(norm_lat * new_level), 0, new_level - 1);

    Serial.printf("[UIState] Zoom %dx centered on (%.1f, %.1f) -> slice=%d col=%d row=%d\n",
                  _zoom_level, lat, lon, current_slice_index, _zoom_col, _zoom_row);
}

int UIState::get_zoom_level() const { return _zoom_level; }
int UIState::get_zoom_col() const { return _zoom_col; }
int UIState::get_zoom_row() const { return _zoom_row; }

bool UIState::zoom_move_left() {
    if (_zoom_level <= 1) return false;
    if (_zoom_col > 0) {
        _zoom_col--;
    } else {
        // At left edge: move to previous slice, rightmost column
        current_slice_index = (current_slice_index + 3) % 4;
        _zoom_col = _zoom_level - 1;
        _zoom_row = 0;
    }
    Serial.printf("[UIState] Zoom pos: slice=%d col=%d row=%d\n",
                  current_slice_index, _zoom_col, _zoom_row);
    return true;
}

bool UIState::zoom_move_right() {
    if (_zoom_level <= 1) return false;
    if (_zoom_col < _zoom_level - 1) {
        _zoom_col++;
    } else {
        // At right edge: move to next slice, leftmost column
        current_slice_index = (current_slice_index + 1) % 4;
        _zoom_col = 0;
        _zoom_row = 0;
    }
    Serial.printf("[UIState] Zoom pos: slice=%d col=%d row=%d\n",
                  current_slice_index, _zoom_col, _zoom_row);
    return true;
}

bool UIState::zoom_move_up() {
    if (_zoom_level <= 1 || _zoom_row <= 0) return false;
    _zoom_row--;
    Serial.printf("[UIState] Zoom pos: slice=%d col=%d row=%d\n",
                  current_slice_index, _zoom_col, _zoom_row);
    return true;
}

bool UIState::zoom_move_down() {
    if (_zoom_level <= 1 || _zoom_row >= _zoom_level - 1) return false;
    _zoom_row++;
    Serial.printf("[UIState] Zoom pos: slice=%d col=%d row=%d\n",
                  current_slice_index, _zoom_col, _zoom_row);
    return true;
}

float UIState::get_view_lon_min() const {
    const MapSlice& s = slices[current_slice_index];
    if (_zoom_level <= 1) return s.lon_min;

    float range = s.lon_max - s.lon_min;
    if (range < 0) range += 360.0f;

    float sub_range = range / _zoom_level;
    float result = s.lon_min + _zoom_col * sub_range;
    if (result > 180.0f) result -= 360.0f;
    return result;
}

float UIState::get_view_lon_max() const {
    const MapSlice& s = slices[current_slice_index];
    if (_zoom_level <= 1) return s.lon_max;

    float range = s.lon_max - s.lon_min;
    if (range < 0) range += 360.0f;

    float sub_range = range / _zoom_level;
    float result = s.lon_min + (_zoom_col + 1) * sub_range;
    if (result > 180.0f) result -= 360.0f;
    return result;
}

float UIState::get_view_lat_max() const {
    if (_zoom_level <= 1) return 90.0f;
    float lat_range = 180.0f / _zoom_level;
    return 90.0f - _zoom_row * lat_range;
}

float UIState::get_view_lat_min() const {
    if (_zoom_level <= 1) return -90.0f;
    float lat_range = 180.0f / _zoom_level;
    return 90.0f - (_zoom_row + 1) * lat_range;
}
