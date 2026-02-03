/**
 * Radio.garden places database for RadioWall.
 *
 * Loads pre-compiled places.bin from LittleFS and provides
 * nearest-place lookup for touch coordinates.
 */

#include "places_db.h"
#include <LittleFS.h>
#include <Arduino.h>
#include <esp_partition.h>

// Database state
static Place* _places = nullptr;      // In-memory array (PSRAM if available)
static uint32_t _place_count = 0;
static bool _loaded = false;
static File _db_file;                 // For on-demand reading if no PSRAM

// For on-demand mode: temp buffer for current place
static Place _current_place;

// Use PSRAM if available (ESP32-S3 typically has 8MB)
static bool _use_psram = false;

bool places_db_init() {
    Serial.println("[PlacesDB] Initializing...");

    // Debug: Print partition info
    const esp_partition_t* partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");

    if (partition) {
        Serial.printf("[PlacesDB] Found partition: offset=0x%x, size=%d KB\n",
                      partition->address, partition->size / 1024);
    } else {
        Serial.println("[PlacesDB] WARNING: 'spiffs' partition not found in partition table!");
        Serial.println("[PlacesDB] Available partitions:");
        esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, NULL);
        while (it) {
            const esp_partition_t* p = esp_partition_get(it);
            Serial.printf("[PlacesDB]   - %s: type=%d, subtype=%d, offset=0x%x, size=%dKB\n",
                          p->label, p->type, p->subtype, p->address, p->size/1024);
            it = esp_partition_next(it);
        }
    }

    // Mount LittleFS
    if (!LittleFS.begin(false)) {
        Serial.println("[PlacesDB] ERROR: Failed to mount LittleFS");
        Serial.println("[PlacesDB] Trying to format...");
        if (LittleFS.format() && LittleFS.begin(false)) {
            Serial.println("[PlacesDB] Formatted successfully, but places.bin is now gone!");
            Serial.println("[PlacesDB] Run 'pio run -t uploadfs' to re-upload places.bin");
        } else {
            Serial.println("[PlacesDB] Format failed - partition table may be wrong");
        }
        return false;
    }

    // Open database file
    _db_file = LittleFS.open("/places.bin", "r");
    if (!_db_file) {
        Serial.println("[PlacesDB] ERROR: places.bin not found");
        return false;
    }

    // Read and validate header
    uint8_t header[PLACES_HEADER_SIZE];
    if (_db_file.read(header, PLACES_HEADER_SIZE) != PLACES_HEADER_SIZE) {
        Serial.println("[PlacesDB] ERROR: Failed to read header");
        _db_file.close();
        return false;
    }

    // Check magic
    if (memcmp(header, PLACES_DB_MAGIC, 4) != 0) {
        Serial.println("[PlacesDB] ERROR: Invalid magic (not a places database)");
        _db_file.close();
        return false;
    }

    // Check version
    uint16_t version = header[4] | (header[5] << 8);
    if (version != PLACES_DB_VERSION) {
        Serial.printf("[PlacesDB] ERROR: Version mismatch (file=%d, expected=%d)\n",
                      version, PLACES_DB_VERSION);
        _db_file.close();
        return false;
    }

    // Get place count
    _place_count = header[6] | (header[7] << 8) | (header[8] << 16) | (header[9] << 24);
    Serial.printf("[PlacesDB] Found %lu places in database\n", _place_count);

    // Calculate required memory
    size_t db_size = _place_count * sizeof(Place);
    Serial.printf("[PlacesDB] Database size: %.1f KB\n", db_size / 1024.0f);

    // Try to allocate in PSRAM first
    #ifdef BOARD_HAS_PSRAM
    if (psramFound()) {
        _places = (Place*)ps_malloc(db_size);
        if (_places) {
            _use_psram = true;
            Serial.println("[PlacesDB] Allocated in PSRAM");
        }
    }
    #endif

    // Fall back to regular malloc if no PSRAM
    if (!_places) {
        _places = (Place*)malloc(db_size);
        if (_places) {
            Serial.println("[PlacesDB] Allocated in SRAM (no PSRAM)");
        }
    }

    // Load into memory if allocation succeeded
    if (_places) {
        size_t bytes_read = _db_file.read((uint8_t*)_places, db_size);
        if (bytes_read != db_size) {
            Serial.printf("[PlacesDB] ERROR: Read %zu bytes, expected %zu\n", bytes_read, db_size);
            free(_places);
            _places = nullptr;
            _db_file.close();
            return false;
        }
        _db_file.close();
        Serial.println("[PlacesDB] Loaded full database into memory");
    } else {
        // Keep file open for on-demand reading
        Serial.println("[PlacesDB] WARNING: Using on-demand file reading (slow)");
    }

    _loaded = true;

    // Print a sample place for verification
    if (_place_count > 0) {
        const Place* sample = places_db_find_nearest(48.21f, 16.37f);  // Vienna
        if (sample) {
            Serial.printf("[PlacesDB] Sample lookup (Vienna): %s, %s (%.2f, %.2f)\n",
                          sample->name, sample->country,
                          sample->lat_x100 / 100.0f, sample->lon_x100 / 100.0f);
        }
    }

    return true;
}

const Place* places_db_find_nearest(float lat, float lon) {
    if (!_loaded || _place_count == 0) {
        return nullptr;
    }

    // Convert target to scaled integers for faster comparison
    int16_t target_lat = (int16_t)(lat * 100);
    int16_t target_lon = (int16_t)(lon * 100);

    const Place* nearest = nullptr;
    int32_t min_dist_sq = INT32_MAX;

    if (_places) {
        // Fast path: in-memory search
        for (uint32_t i = 0; i < _place_count; i++) {
            int32_t dlat = _places[i].lat_x100 - target_lat;
            int32_t dlon = _places[i].lon_x100 - target_lon;

            // Handle longitude wraparound (-180 to 180)
            if (dlon > 18000) dlon -= 36000;
            if (dlon < -18000) dlon += 36000;

            // Squared distance (no sqrt needed for comparison)
            int32_t dist_sq = dlat * dlat + dlon * dlon;

            if (dist_sq < min_dist_sq) {
                min_dist_sq = dist_sq;
                nearest = &_places[i];
            }
        }
    } else {
        // Slow path: read from file
        _db_file.seek(PLACES_HEADER_SIZE);
        uint32_t nearest_idx = 0;

        for (uint32_t i = 0; i < _place_count; i++) {
            Place temp;
            if (_db_file.read((uint8_t*)&temp, sizeof(Place)) != sizeof(Place)) {
                break;
            }

            int32_t dlat = temp.lat_x100 - target_lat;
            int32_t dlon = temp.lon_x100 - target_lon;

            if (dlon > 18000) dlon -= 36000;
            if (dlon < -18000) dlon += 36000;

            int32_t dist_sq = dlat * dlat + dlon * dlon;

            if (dist_sq < min_dist_sq) {
                min_dist_sq = dist_sq;
                nearest_idx = i;
                memcpy(&_current_place, &temp, sizeof(Place));
            }
        }
        nearest = &_current_place;
    }

    return nearest;
}

uint32_t places_db_count() {
    return _place_count;
}

bool places_db_loaded() {
    return _loaded;
}

void places_db_serial_task() {
    if (!Serial.available()) return;

    String line = Serial.readStringUntil('\n');
    line.trim();

    // L:lat,lon - Find nearest place
    if (line.startsWith("L:")) {
        int comma = line.indexOf(',', 2);
        if (comma > 0) {
            float lat = line.substring(2, comma).toFloat();
            float lon = line.substring(comma + 1).toFloat();

            Serial.printf("[PlacesDB] Looking up (%.2f, %.2f)...\n", lat, lon);

            unsigned long start = micros();
            const Place* place = places_db_find_nearest(lat, lon);
            unsigned long elapsed = micros() - start;

            if (place) {
                float place_lat = place->lat_x100 / 100.0f;
                float place_lon = place->lon_x100 / 100.0f;

                // Calculate approximate distance in km
                float dlat = lat - place_lat;
                float dlon = lon - place_lon;
                if (dlon > 180) dlon -= 360;
                if (dlon < -180) dlon += 360;
                float dist_km = sqrtf(dlat * dlat + dlon * dlon) * 111.0f;  // ~111km per degree

                Serial.printf("[PlacesDB] Found: %s, %s\n", place->name, place->country);
                Serial.printf("[PlacesDB]   ID: %s\n", place->id);
                Serial.printf("[PlacesDB]   Location: (%.2f, %.2f)\n", place_lat, place_lon);
                Serial.printf("[PlacesDB]   Distance: ~%.0f km\n", dist_km);
                Serial.printf("[PlacesDB]   Search time: %lu us\n", elapsed);
            } else {
                Serial.println("[PlacesDB] No place found");
            }
        } else {
            Serial.println("[PlacesDB] Usage: L:lat,lon (e.g., L:48.21,16.37)");
        }
    }
    // P:count - Print first N places
    else if (line.startsWith("P:")) {
        int count = line.substring(2).toInt();
        if (count <= 0) count = 5;
        if (count > 20) count = 20;

        Serial.printf("[PlacesDB] First %d places:\n", count);
        if (_places) {
            for (int i = 0; i < count && i < (int)_place_count; i++) {
                Serial.printf("  %d. %s, %s (%.2f, %.2f) [%s]\n",
                              i + 1,
                              _places[i].name,
                              _places[i].country,
                              _places[i].lat_x100 / 100.0f,
                              _places[i].lon_x100 / 100.0f,
                              _places[i].id);
            }
        } else {
            Serial.println("  (on-demand mode - not available)");
        }
    }
}
