/**
 * Favorites system for RadioWall.
 *
 * Stores up to 20 favorite stations in LittleFS JSON.
 * Provides rendering and touch handling for the favorites list screen.
 */

#ifndef FAVORITES_H
#define FAVORITES_H

#include <Arduino.h>

// Forward declaration
class Arduino_GFX;

#define MAX_FAVORITES 20
#define FAVORITES_PER_PAGE 6

struct FavoriteStation {
    char station_id[16];
    char title[64];
    char place[32];
    char country[4];
    float lat;
    float lon;
};

// Callbacks
typedef void (*FavoritePlayCallback)(int index);
typedef void (*FavoriteDeleteCallback)(int index);

// Initialize (load from LittleFS)
void favorites_init();

// Data access
int favorites_count();
const FavoriteStation* favorites_get(int index);
bool favorites_add(const FavoriteStation& fav);
bool favorites_remove(int index);
bool favorites_contains(const char* station_id);

// Pagination
int favorites_get_page();
int favorites_total_pages();
void favorites_set_page(int page);
void favorites_next_page();

// Rendering + touch
void favorites_render(Arduino_GFX* gfx, int page);
bool favorites_handle_touch(int x, int y, Arduino_GFX* gfx);

// Callbacks
void favorites_set_play_callback(FavoritePlayCallback cb);
void favorites_set_delete_callback(FavoriteDeleteCallback cb);

#endif // FAVORITES_H
