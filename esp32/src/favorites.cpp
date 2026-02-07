/**
 * Favorites system implementation for RadioWall.
 *
 * Stores favorites as JSON on LittleFS. Renders the favorites list
 * screen and handles touch input (play zone + delete zone per item).
 */

#include "favorites.h"
#include "Arduino_GFX_Library.h"
#include <LittleFS.h>
#include <ArduinoJson.h>

static const char* FAVORITES_FILE = "/favorites.json";

// Layout constants (matching menu.cpp style)
static const int TITLE_HEIGHT   = 40;
static const int ITEM_HEIGHT    = 80;
static const int ITEMS_START_Y  = TITLE_HEIGHT;
static const int DISPLAY_WIDTH  = 180;
static const int PLAY_ZONE_W    = 120;  // Left side: tap to play
// Delete zone: 120-179 (60px wide)

static const int PAGE_INDICATOR_Y = 530;
static const int FAV_AREA_BOTTOM  = 520;

// Colors
static const uint16_t COLOR_BG        = 0x0000;  // BLACK
static const uint16_t COLOR_TITLE     = 0x07FF;  // CYAN
static const uint16_t COLOR_ITEM_TEXT = 0xFFFF;  // WHITE
static const uint16_t COLOR_PLACE     = 0x8410;  // Mid gray
static const uint16_t COLOR_DIVIDER   = 0x4208;  // Dark gray
static const uint16_t COLOR_DELETE    = 0x8410;  // Gray for "x"
static const uint16_t COLOR_DEL_BG    = 0x8000;  // Dark red highlight
static const uint16_t COLOR_HIGHLIGHT = 0x0228;  // Dark teal

// In-memory storage
static FavoriteStation _favs[MAX_FAVORITES];
static int _fav_count = 0;
static int _current_page = 0;

// Callbacks
static FavoritePlayCallback _play_cb = nullptr;
static FavoriteDeleteCallback _delete_cb = nullptr;

// ------------------------------------------------------------------
// LittleFS persistence
// ------------------------------------------------------------------

static bool save_to_file() {
    File f = LittleFS.open(FAVORITES_FILE, "w");
    if (!f) {
        Serial.println("[Favs] Failed to open file for writing");
        return false;
    }

    DynamicJsonDocument doc(4096);
    JsonArray arr = doc.to<JsonArray>();

    for (int i = 0; i < _fav_count; i++) {
        JsonObject obj = arr.createNestedObject();
        obj["i"] = _favs[i].station_id;
        obj["t"] = _favs[i].title;
        obj["p"] = _favs[i].place;
        obj["c"] = _favs[i].country;
        obj["a"] = _favs[i].lat;
        obj["o"] = _favs[i].lon;
    }

    serializeJson(doc, f);
    f.close();
    Serial.printf("[Favs] Saved %d favorites\n", _fav_count);
    return true;
}

static bool load_from_file() {
    if (!LittleFS.exists(FAVORITES_FILE)) {
        Serial.println("[Favs] No favorites file found");
        return true;  // Not an error, just empty
    }

    File f = LittleFS.open(FAVORITES_FILE, "r");
    if (!f) {
        Serial.println("[Favs] Failed to open favorites file");
        return false;
    }

    DynamicJsonDocument doc(4096);
    DeserializationError error = deserializeJson(doc, f);
    f.close();

    if (error) {
        Serial.printf("[Favs] JSON parse error: %s\n", error.c_str());
        return false;
    }

    _fav_count = 0;
    JsonArray arr = doc.as<JsonArray>();
    for (JsonObject obj : arr) {
        if (_fav_count >= MAX_FAVORITES) break;

        FavoriteStation& fav = _favs[_fav_count];
        strncpy(fav.station_id, obj["i"] | "", sizeof(fav.station_id) - 1);
        fav.station_id[sizeof(fav.station_id) - 1] = '\0';
        strncpy(fav.title, obj["t"] | "", sizeof(fav.title) - 1);
        fav.title[sizeof(fav.title) - 1] = '\0';
        strncpy(fav.place, obj["p"] | "", sizeof(fav.place) - 1);
        fav.place[sizeof(fav.place) - 1] = '\0';
        strncpy(fav.country, obj["c"] | "", sizeof(fav.country) - 1);
        fav.country[sizeof(fav.country) - 1] = '\0';
        fav.lat = obj["a"] | 0.0f;
        fav.lon = obj["o"] | 0.0f;

        _fav_count++;
    }

    Serial.printf("[Favs] Loaded %d favorites\n", _fav_count);
    return true;
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

void favorites_init() {
    _fav_count = 0;
    _current_page = 0;
    load_from_file();
}

int favorites_count() {
    return _fav_count;
}

const FavoriteStation* favorites_get(int index) {
    if (index < 0 || index >= _fav_count) return nullptr;
    return &_favs[index];
}

bool favorites_add(const FavoriteStation& fav) {
    if (_fav_count >= MAX_FAVORITES) return false;
    if (favorites_contains(fav.station_id)) return false;

    _favs[_fav_count] = fav;
    _fav_count++;
    save_to_file();
    Serial.printf("[Favs] Added: %s (%s)\n", fav.title, fav.place);
    return true;
}

bool favorites_remove(int index) {
    if (index < 0 || index >= _fav_count) return false;

    Serial.printf("[Favs] Removed: %s\n", _favs[index].title);

    // Shift remaining items down
    for (int i = index; i < _fav_count - 1; i++) {
        _favs[i] = _favs[i + 1];
    }
    _fav_count--;

    // Adjust page if needed
    if (_current_page >= favorites_total_pages() && _current_page > 0) {
        _current_page--;
    }

    save_to_file();
    return true;
}

bool favorites_contains(const char* station_id) {
    for (int i = 0; i < _fav_count; i++) {
        if (strcmp(_favs[i].station_id, station_id) == 0) return true;
    }
    return false;
}

// ------------------------------------------------------------------
// Pagination
// ------------------------------------------------------------------

int favorites_get_page() {
    return _current_page;
}

int favorites_total_pages() {
    if (_fav_count == 0) return 1;
    return (_fav_count + FAVORITES_PER_PAGE - 1) / FAVORITES_PER_PAGE;
}

void favorites_set_page(int page) {
    int total = favorites_total_pages();
    _current_page = constrain(page, 0, total - 1);
}

void favorites_next_page() {
    int total = favorites_total_pages();
    _current_page = (_current_page + 1) % total;
    Serial.printf("[Favs] Page %d/%d\n", _current_page + 1, total);
}

// ------------------------------------------------------------------
// Rendering
// ------------------------------------------------------------------

static void draw_item(Arduino_GFX* gfx, int slot, const FavoriteStation& fav) {
    int y_top = ITEMS_START_Y + slot * ITEM_HEIGHT;

    // Station title (truncate to ~10 chars to fit play zone)
    gfx->setTextSize(2);
    gfx->setTextColor(COLOR_ITEM_TEXT);
    gfx->setCursor(8, y_top + 15);

    // Truncate title to fit in play zone width (~10 chars at size 2)
    char trunc_title[11];
    strncpy(trunc_title, fav.title, 10);
    trunc_title[10] = '\0';
    gfx->print(trunc_title);

    // Place + country below title
    gfx->setTextSize(1);
    gfx->setTextColor(COLOR_PLACE);
    gfx->setCursor(8, y_top + 50);
    char place_str[20];
    snprintf(place_str, sizeof(place_str), "%.*s, %s",
             12, fav.place, fav.country);
    gfx->print(place_str);

    // Delete "x" on right side
    gfx->setTextSize(2);
    gfx->setTextColor(COLOR_DELETE);
    gfx->setCursor(142, y_top + 28);
    gfx->print("x");

    // Vertical divider between play and delete zones
    gfx->drawFastVLine(PLAY_ZONE_W, y_top, ITEM_HEIGHT, COLOR_DIVIDER);

    // Horizontal divider at bottom
    gfx->drawFastHLine(5, y_top + ITEM_HEIGHT - 1, DISPLAY_WIDTH - 10, COLOR_DIVIDER);
}

void favorites_render(Arduino_GFX* gfx, int page) {
    if (!gfx) return;

    // Clear main area
    gfx->fillRect(0, 0, DISPLAY_WIDTH, FAV_AREA_BOTTOM + 60, COLOR_BG);

    // Title
    gfx->setTextSize(2);
    gfx->setTextColor(COLOR_TITLE);
    gfx->setCursor(10, 12);
    if (_fav_count > 0) {
        gfx->printf("FAVS (%d)", _fav_count);
    } else {
        gfx->print("FAVS");
    }

    // Divider under title
    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, DISPLAY_WIDTH - 10, COLOR_DIVIDER);

    if (_fav_count == 0) {
        gfx->setTextSize(1);
        gfx->setTextColor(COLOR_PLACE);
        gfx->setCursor(25, 200);
        gfx->print("No favorites yet");
        gfx->setCursor(15, 230);
        gfx->print("Play a station, then");
        gfx->setCursor(25, 250);
        gfx->print("tap ADD to save it");
        return;
    }

    // Draw items for current page
    int start_idx = page * FAVORITES_PER_PAGE;
    int end_idx = min(start_idx + FAVORITES_PER_PAGE, _fav_count);

    for (int i = start_idx; i < end_idx; i++) {
        draw_item(gfx, i - start_idx, _favs[i]);
    }

    // Page indicator (only if multiple pages)
    int total_pages = favorites_total_pages();
    if (total_pages > 1) {
        gfx->setTextSize(1);
        gfx->setTextColor(COLOR_PLACE);
        gfx->setCursor(55, PAGE_INDICATOR_Y);
        gfx->printf("< %d / %d >", page + 1, total_pages);
    }
}

// ------------------------------------------------------------------
// Touch handling
// ------------------------------------------------------------------

void favorites_set_play_callback(FavoritePlayCallback cb) {
    _play_cb = cb;
}

void favorites_set_delete_callback(FavoriteDeleteCallback cb) {
    _delete_cb = cb;
}

bool favorites_handle_touch(int x, int y, Arduino_GFX* gfx) {
    // Ignore touches in title area
    if (y < ITEMS_START_Y) return false;

    // Ignore touches below item area
    if (y >= ITEMS_START_Y + FAVORITES_PER_PAGE * ITEM_HEIGHT) return false;

    int slot = (y - ITEMS_START_Y) / ITEM_HEIGHT;
    int global_idx = _current_page * FAVORITES_PER_PAGE + slot;

    if (global_idx < 0 || global_idx >= _fav_count) return false;

    // Determine play vs delete zone
    bool is_delete = (x >= PLAY_ZONE_W);

    if (is_delete) {
        // Delete zone — brief red highlight
        Serial.printf("[Favs] Delete tap: %s\n", _favs[global_idx].title);
        if (gfx) {
            int y_top = ITEMS_START_Y + slot * ITEM_HEIGHT;
            gfx->fillRect(PLAY_ZONE_W, y_top, DISPLAY_WIDTH - PLAY_ZONE_W, ITEM_HEIGHT, COLOR_DEL_BG);
            gfx->setTextSize(2);
            gfx->setTextColor(COLOR_ITEM_TEXT);
            gfx->setCursor(132, y_top + 28);
            gfx->print("DEL");
            delay(150);
        }
        if (_delete_cb) {
            _delete_cb(global_idx);
        }
    } else {
        // Play zone — brief highlight
        Serial.printf("[Favs] Play tap: %s\n", _favs[global_idx].title);
        if (gfx) {
            int y_top = ITEMS_START_Y + slot * ITEM_HEIGHT;
            gfx->fillRect(0, y_top, PLAY_ZONE_W, ITEM_HEIGHT, COLOR_HIGHLIGHT);
            gfx->setTextSize(2);
            gfx->setTextColor(COLOR_ITEM_TEXT);
            gfx->setCursor(8, y_top + 15);
            char trunc_title[11];
            strncpy(trunc_title, _favs[global_idx].title, 10);
            trunc_title[10] = '\0';
            gfx->print(trunc_title);
            delay(80);
        }
        if (_play_cb) {
            _play_cb(global_idx);
        }
    }

    return true;
}
