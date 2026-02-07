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
static int _current_station_index = 0;
static int _total_stations = 0;

// Cache of station IDs for current place (for "next" functionality)
static const int MAX_CACHED_STATIONS = 20;
static String _cached_station_ids[MAX_CACHED_STATIONS];
static String _cached_station_titles[MAX_CACHED_STATIONS];

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

void radio_client_init() {
    memset(&_current_station, 0, sizeof(_current_station));
    _current_place_id = "";
    _current_station_index = 0;
    _total_stations = 0;
}

bool radio_play_at_location(float lat, float lon) {
    // Find nearest place
    const Place* place = places_db_find_nearest(lat, lon);
    if (!place) {
        return false;
    }

    Serial.printf("[Radio] %s, %s\n", place->name, place->country);

    // Store place info
    _current_place_id = String(place->id);
    strncpy(_current_station.place, place->name, sizeof(_current_station.place) - 1);
    strncpy(_current_station.country, place->country, sizeof(_current_station.country) - 1);

    // Fetch stations for this place
    String path = "/api/ara/content/page/" + _current_place_id + "/channels";
    String response = https_get(path.c_str());

    if (response.length() == 0) {
        Serial.println("[Radio] Failed to fetch stations");
        return false;
    }

    // Parse JSON response
    // Response format: {"data":{"content":[{"items":[{"page":{"title":"...","url":"/listen/xxx/channel.mp3"}}]}]}}
    DynamicJsonDocument doc(16384);  // 16KB should be enough for station list
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
                // Extract station ID from URL
                // Format: "/listen/{slug}/{id}" - we need the ID (second part)
                String urlStr = String(url);
                int listenIdx = urlStr.indexOf("/listen/");
                if (listenIdx >= 0) {
                    int slugStart = listenIdx + 8;
                    int idStart = urlStr.indexOf("/", slugStart);
                    if (idStart > slugStart) {
                        idStart++;  // Skip the slash
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

bool radio_play_next() {
    if (_total_stations == 0) {
        Serial.println("[Radio] No stations loaded");
        return false;
    }

    // If only 1 station, no point in "next"
    if (_total_stations == 1) {
        Serial.println("[Radio] Only 1 station available");
    }

    String station_id = _cached_station_ids[_current_station_index];
    String station_title = _cached_station_titles[_current_station_index];

    Serial.printf("[Radio] Playing: %s (%d/%d)\n",
                  station_title.c_str(), _current_station_index + 1, _total_stations);

    String stream_url = radio_get_stream_url(station_id.c_str());
    if (stream_url.length() == 0) {
        _current_station_index = (_current_station_index + 1) % _total_stations;
        return false;
    }

    // Update current station info
    strncpy(_current_station.id, station_id.c_str(), sizeof(_current_station.id) - 1);
    strncpy(_current_station.title, station_title.c_str(), sizeof(_current_station.title) - 1);
    _current_station.valid = true;

    // Play via LinkPlay
    bool success = linkplay_play(stream_url.c_str());

    // Advance to next station for next time
    _current_station_index = (_current_station_index + 1) % _total_stations;

    return success;
}

void radio_stop() {
    linkplay_stop();
    _current_station.valid = false;
}

const StationInfo* radio_get_current() {
    return _current_station.valid ? &_current_station : nullptr;
}

String radio_get_stream_url(const char* station_id) {
    String path = "/api/ara/content/listen/" + String(station_id) + "/channel.mp3";
    String redirect_url = get_redirect_url(path.c_str());

    if (redirect_url.length() > 0) {
        Serial.printf("[Radio] Stream URL: %s\n", redirect_url.c_str());
    }

    return redirect_url;
}
