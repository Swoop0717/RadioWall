/**
 * Radio.garden API Client for ESP32 standalone mode
 *
 * Handles fetching stations and stream URLs directly from Radio.garden,
 * without requiring a server intermediary.
 */

#ifndef RADIO_CLIENT_H
#define RADIO_CLIENT_H

#include <Arduino.h>

// Station info returned from lookup
struct StationInfo {
    char id[16];        // Station ID for stream URL
    char title[64];     // Station name
    char place[32];     // City name
    char country[32];   // Country name
    bool valid;         // True if station was found
};

// Initialize the radio client
void radio_client_init();

// Play radio from a location (lat/lon)
// Returns true if playback started successfully
bool radio_play_at_location(float lat, float lon);

// Play the next station at the current location
// Returns true if there's another station to play
bool radio_play_next();

// Stop playback
void radio_stop();

// Get current station info
const StationInfo* radio_get_current();

// Get the stream URL for a station ID
// Returns empty string on failure
String radio_get_stream_url(const char* station_id);

#endif // RADIO_CLIENT_H
