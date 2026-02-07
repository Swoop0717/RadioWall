/**
 * Playback history for RadioWall.
 *
 * Automatically records the last 20 stations played.
 * Stored as JSON on LittleFS, newest first.
 */

#ifndef HISTORY_H
#define HISTORY_H

#include <Arduino.h>

// Forward declaration
class Arduino_GFX;

#define MAX_HISTORY 20
#define HISTORY_PER_PAGE 6

struct HistoryEntry {
    char station_id[16];
    char title[64];
    char place[32];
    char country[4];
    float lat;
    float lon;
};

// Callback when a history entry is tapped to replay
typedef void (*HistoryPlayCallback)(int index);

// Initialize (load from LittleFS)
void history_init();

// Record a station (adds to front, deduplicates, auto-saves)
void history_record(const HistoryEntry& entry);

// Data access
int history_count();
const HistoryEntry* history_get(int index);
void history_clear();

// Pagination
int history_get_page();
int history_total_pages();
void history_set_page(int page);
void history_next_page();

// Rendering + touch
void history_render(Arduino_GFX* gfx, int page);
bool history_handle_touch(int x, int y, Arduino_GFX* gfx);

// Callbacks
void history_set_play_callback(HistoryPlayCallback cb);

#endif // HISTORY_H
