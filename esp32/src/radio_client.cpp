/**
 * Radio.garden API Client for ESP32 standalone mode
 */

#include "radio_client.h"
#include "places_db.h"
#include "linkplay_client.h"
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// Radio.garden API host
static const char* RADIO_GARDEN_HOST = "radio.garden";

// Current state
static StationInfo _current_station;
static String _current_place_id;
static int _current_station_index = 0;   // Next station to play (0-based)
static int _playing_station_index = -1;  // Currently playing station (0-based, -1 = none)
static int _total_stations = 0;

// Cache of station IDs for current place (for "next" functionality)
static const int MAX_CACHED_STATIONS = 100;
static String _cached_station_ids[MAX_CACHED_STATIONS];
static String _cached_station_titles[MAX_CACHED_STATIONS];

// Next-city hopping state
static float _touch_origin_lat = 0;
static float _touch_origin_lon = 0;
static const int MAX_VISITED_CITIES = 20;
static String _visited_place_ids[MAX_VISITED_CITIES];
static int _num_visited = 0;

// Make HTTPS request to radio.garden
static String https_get(const char* path) {
    WiFiClientSecure client;
    client.setInsecure();  // Radio.garden uses valid cert, but skip verification for simplicity

    Serial.printf("[Radio] GET https://%s%s\n", RADIO_GARDEN_HOST, path);

    if (!client.connect(RADIO_GARDEN_HOST, 443, 10000)) {
        Serial.println("[Radio] Connection failed");
        return "";
    }

    // Send request - use HTTP/1.0 to avoid chunked encoding
    client.printf("GET %s HTTP/1.0\r\n", path);
    client.printf("Host: %s\r\n", RADIO_GARDEN_HOST);
    client.println("User-Agent: RadioWall/1.0");
    client.println("Accept: application/json");
    client.println("Connection: close");
    client.println();

    // Wait for response
    unsigned long timeout = millis() + 10000;
    while (client.connected() && !client.available()) {
        if (millis() > timeout) {
            Serial.println("[Radio] Response timeout");
            client.stop();
            return "";
        }
        delay(10);
    }

    // Skip HTTP headers, check for chunked encoding
    bool chunked = false;
    while (client.available()) {
        String line = client.readStringUntil('\n');
        if (line.indexOf("Transfer-Encoding: chunked") >= 0) {
            chunked = true;
        }
        if (line == "\r" || line.length() == 0) {
            break;  // End of headers
        }
    }

    // Read body
    String body = "";
    if (chunked) {
        // Handle chunked transfer encoding
        while (client.connected() || client.available()) {
            // Read chunk size (hex)
            String chunkSizeLine = client.readStringUntil('\n');
            chunkSizeLine.trim();
            int chunkSize = strtol(chunkSizeLine.c_str(), NULL, 16);
            if (chunkSize == 0) break;  // End of chunks

            // Read chunk data
            while (chunkSize > 0 && (client.connected() || client.available())) {
                if (client.available()) {
                    body += (char)client.read();
                    chunkSize--;
                }
            }
            // Skip trailing \r\n after chunk
            client.readStringUntil('\n');
        }
    } else {
        // Regular body
        while (client.connected() || client.available()) {
            if (client.available()) {
                body += (char)client.read();
            }
        }
    }
    client.stop();
    return body;
}

// Get redirect URL for stream (follows Location header)
static String get_redirect_url(const char* path) {
    WiFiClientSecure client;
    client.setInsecure();

    if (!client.connect(RADIO_GARDEN_HOST, 443, 10000)) {
        return "";
    }

    client.printf("GET %s HTTP/1.0\r\n", path);
    client.printf("Host: %s\r\n", RADIO_GARDEN_HOST);
    client.println("User-Agent: RadioWall/1.0");
    client.println("Connection: close");
    client.println();

    unsigned long timeout = millis() + 10000;
    while (client.connected() && !client.available()) {
        if (millis() > timeout) {
            client.stop();
            return "";
        }
        delay(10);
    }

    // Read headers, look for Location
    String location = "";
    while (client.available()) {
        String line = client.readStringUntil('\n');
        line.trim();
        if (line.startsWith("Location: ") || line.startsWith("location: ")) {
            location = line.substring(10);
        }
        if (line.length() == 0) break;
    }
    client.stop();
    return location;
}

// Forward declaration
static bool fetch_and_play_place(const Place* place);

void radio_client_init() {
    memset(&_current_station, 0, sizeof(_current_station));
    _current_place_id = "";
    _current_station_index = 0;
    _playing_station_index = -1;
    _total_stations = 0;
    _num_visited = 0;
}

/**
 * Fetch stations for a Place and play the first one.
 * Used by both radio_play_at_location and radio_play_next_city.
 */
static bool fetch_and_play_place(const Place* place) {
    Serial.printf("[Radio] %s, %s\n", place->name, place->country);

    // Store place info
    _current_place_id = String(place->id);
    strncpy(_current_station.place, place->name, sizeof(_current_station.place) - 1);
    strncpy(_current_station.country, place->country, sizeof(_current_station.country) - 1);
    _current_station.lat = place->lat_x100 / 100.0f;
    _current_station.lon = place->lon_x100 / 100.0f;

    // Fetch stations for this place
    String path = "/api/ara/content/page/" + _current_place_id + "/channels";
    String response = https_get(path.c_str());

    if (response.length() == 0) {
        Serial.println("[Radio] Failed to fetch stations");
        return false;
    }

    // Parse JSON response
    DynamicJsonDocument doc(16384);
    DeserializationError error = deserializeJson(doc, response);

    if (error) {
        Serial.printf("[Radio] JSON parse error: %s\n", error.c_str());
        return false;
    }

    // Extract stations
    _total_stations = 0;
    JsonArray content = doc["data"]["content"];
    for (JsonObject section : content) {
        JsonArray items = section["items"];
        for (JsonObject item : items) {
            if (_total_stations >= MAX_CACHED_STATIONS) break;

            const char* title = item["page"]["title"];
            const char* url = item["page"]["url"];

            if (title && url) {
                String urlStr = String(url);
                int listenIdx = urlStr.indexOf("/listen/");
                if (listenIdx >= 0) {
                    int slugStart = listenIdx + 8;
                    int idStart = urlStr.indexOf("/", slugStart);
                    if (idStart > slugStart) {
                        idStart++;
                        _cached_station_ids[_total_stations] = urlStr.substring(idStart);
                        _cached_station_titles[_total_stations] = String(title);
                        _total_stations++;
                    }
                }
            }
        }
    }

    if (_total_stations == 0) {
        return false;
    }
    Serial.printf("[Radio] %d stations available\n", _total_stations);

    // Play first station
    _current_station_index = 0;
    return radio_play_next();
}

bool radio_play_at_location(float lat, float lon) {
    // Find nearest place
    const Place* place = places_db_find_nearest(lat, lon);
    if (!place) {
        return false;
    }

    // Store touch origin for next-city hopping
    _touch_origin_lat = lat;
    _touch_origin_lon = lon;

    // Reset visited cities list
    _num_visited = 0;
    _visited_place_ids[_num_visited++] = String(place->id);

    return fetch_and_play_place(place);
}

/**
 * Hop to the next nearest city from the original touch point.
 * Excludes all previously visited cities.
 */
static bool radio_play_next_city() {
    if (_num_visited >= MAX_VISITED_CITIES) {
        Serial.println("[Radio] Max visited cities reached");
        return false;
    }

    const Place* place = places_db_find_nearest_excluding(
        _touch_origin_lat, _touch_origin_lon,
        _visited_place_ids, _num_visited);

    if (!place) {
        Serial.println("[Radio] No cities found (DB not in memory?)");
        return false;
    }

    Serial.printf("[Radio] -> Next city: %s, %s\n", place->name, place->country);
    _visited_place_ids[_num_visited++] = String(place->id);

    return fetch_and_play_place(place);
}

bool radio_play_next() {
    if (_total_stations == 0) {
        Serial.println("[Radio] No stations loaded");
        return false;
    }

    // If all stations at current city exhausted, hop to next city
    if (_current_station_index >= _total_stations) {
        return radio_play_next_city();
    }

    _playing_station_index = _current_station_index;

    String station_id = _cached_station_ids[_current_station_index];
    String station_title = _cached_station_titles[_current_station_index];

    Serial.printf("[Radio] Playing: %s (%d/%d)\n",
                  station_title.c_str(), _current_station_index + 1, _total_stations);

    String stream_url = radio_get_stream_url(station_id.c_str());
    if (stream_url.length() == 0) {
        _current_station_index++;
        return false;
    }

    // Update current station info
    strncpy(_current_station.id, station_id.c_str(), sizeof(_current_station.id) - 1);
    strncpy(_current_station.title, station_title.c_str(), sizeof(_current_station.title) - 1);
    _current_station.valid = true;

    // Play via LinkPlay
    bool success = linkplay_play(stream_url.c_str());

    // Advance index for next call
    _current_station_index++;

    return success;
}

void radio_stop() {
    linkplay_stop();
    _current_station.valid = false;
}

const StationInfo* radio_get_current() {
    return _current_station.valid ? &_current_station : nullptr;
}

bool radio_play_by_id(const char* station_id, const char* title,
                      const char* place, const char* country,
                      float lat, float lon) {
    Serial.printf("[Radio] Playing by ID: %s (%s)\n", title, place);

    String stream_url = radio_get_stream_url(station_id);
    if (stream_url.length() == 0) {
        Serial.println("[Radio] Failed to get stream URL");
        return false;
    }

    // Update current station info
    strncpy(_current_station.id, station_id, sizeof(_current_station.id) - 1);
    _current_station.id[sizeof(_current_station.id) - 1] = '\0';
    strncpy(_current_station.title, title, sizeof(_current_station.title) - 1);
    _current_station.title[sizeof(_current_station.title) - 1] = '\0';
    strncpy(_current_station.place, place, sizeof(_current_station.place) - 1);
    _current_station.place[sizeof(_current_station.place) - 1] = '\0';
    strncpy(_current_station.country, country, sizeof(_current_station.country) - 1);
    _current_station.country[sizeof(_current_station.country) - 1] = '\0';
    _current_station.lat = lat;
    _current_station.lon = lon;
    _current_station.valid = true;

    // Clear station cache (no "next" for favorites)
    _total_stations = 0;
    _current_station_index = 0;

    return linkplay_play(stream_url.c_str());
}

String radio_get_stream_url(const char* station_id) {
    String path = "/api/ara/content/listen/" + String(station_id) + "/channel.mp3";
    String redirect_url = get_redirect_url(path.c_str());

    if (redirect_url.length() > 0) {
        Serial.printf("[Radio] Stream URL: %s\n", redirect_url.c_str());
    }

    return redirect_url;
}

int radio_get_station_index() {
    if (_playing_station_index < 0) return 0;
    return _playing_station_index + 1;  // 1-based
}

int radio_get_total_stations() {
    return _total_stations;
}
