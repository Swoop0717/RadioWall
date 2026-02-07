/**
 * Radio.garden places database for RadioWall.
 *
 * Loads pre-compiled places.bin from LittleFS and provides
 * nearest-place lookup for touch coordinates.
 */

#ifndef PLACES_DB_H
#define PLACES_DB_H

#include "places_info.h"

// Initialize the places database (loads from LittleFS)
// Returns true on success, false if file not found or corrupt
bool places_db_init();

// Find the nearest place to given coordinates
// Returns pointer to Place struct (valid until next call), or nullptr if DB not loaded
const Place* places_db_find_nearest(float lat, float lon);

// Get place count (0 if not loaded)
uint32_t places_db_count();

// Check if database is loaded
bool places_db_loaded();

// Process serial commands for testing (call from loop)
// Supports: L:lat,lon - find nearest place
void places_db_serial_task();

#endif // PLACES_DB_H
