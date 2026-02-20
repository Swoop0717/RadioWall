/**
 * Playback history implementation for RadioWall.
 *
 * Ring buffer of last 20 stations played. Auto-records on play,
 * deduplicates (moves repeated station to top). Persists to LittleFS.
 */

#include "history.h"
#include "theme.h"
#include "Arduino_GFX_Library.h"
#include <LittleFS.h>
#include <ArduinoJson.h>

static const char* HISTORY_FILE = "/history.json";

// Helper: truncate UTF-8 string to max N bytes with "..." without splitting multi-byte chars
static void utf8_truncate(char* buf, size_t max_bytes) {
    if (strlen(buf) <= max_bytes) return;
    int i = max_bytes - 3;
    while (i > 0 && (buf[i] & 0xC0) == 0x80) i--;
    buf[i++] = '.';
    buf[i++] = '.';
    buf[i++] = '.';
    buf[i] = '\0';
}

// Layout constants
static const int TITLE_HEIGHT   = 40;
static const int ITEM_HEIGHT    = 80;
static const int ITEMS_START_Y  = TITLE_HEIGHT;
static const int PAGE_INDICATOR_Y = 530;
static const int HIST_AREA_BOTTOM = 520;

// In-memory storage (newest at index 0)
static HistoryEntry _entries[MAX_HISTORY];
static int _count = 0;
static int _current_page = 0;

// Callbacks
static HistoryPlayCallback _play_cb = nullptr;

// ------------------------------------------------------------------
// LittleFS persistence
// ------------------------------------------------------------------

static bool save_to_file() {
    File f = LittleFS.open(HISTORY_FILE, "w");
    if (!f) {
        Serial.println("[History] Failed to open file for writing");
        return false;
    }

    DynamicJsonDocument doc(4096);
    JsonArray arr = doc.to<JsonArray>();

    for (int i = 0; i < _count; i++) {
        JsonObject obj = arr.createNestedObject();
        obj["i"] = _entries[i].station_id;
        obj["t"] = _entries[i].title;
        obj["p"] = _entries[i].place;
        obj["c"] = _entries[i].country;
        obj["a"] = _entries[i].lat;
        obj["o"] = _entries[i].lon;
    }

    serializeJson(doc, f);
    f.close();
    Serial.printf("[History] Saved %d entries\n", _count);
    return true;
}

static bool load_from_file() {
    if (!LittleFS.exists(HISTORY_FILE)) {
        Serial.println("[History] No history file found");
        return true;
    }

    File f = LittleFS.open(HISTORY_FILE, "r");
    if (!f) {
        Serial.println("[History] Failed to open history file");
        return false;
    }

    DynamicJsonDocument doc(4096);
    DeserializationError error = deserializeJson(doc, f);
    f.close();

    if (error) {
        Serial.printf("[History] JSON parse error: %s\n", error.c_str());
        return false;
    }

    _count = 0;
    JsonArray arr = doc.as<JsonArray>();
    for (JsonObject obj : arr) {
        if (_count >= MAX_HISTORY) break;

        HistoryEntry& e = _entries[_count];
        strncpy(e.station_id, obj["i"] | "", sizeof(e.station_id) - 1);
        e.station_id[sizeof(e.station_id) - 1] = '\0';
        strncpy(e.title, obj["t"] | "", sizeof(e.title) - 1);
        e.title[sizeof(e.title) - 1] = '\0';
        strncpy(e.place, obj["p"] | "", sizeof(e.place) - 1);
        e.place[sizeof(e.place) - 1] = '\0';
        strncpy(e.country, obj["c"] | "", sizeof(e.country) - 1);
        e.country[sizeof(e.country) - 1] = '\0';
        e.lat = obj["a"] | 0.0f;
        e.lon = obj["o"] | 0.0f;

        _count++;
    }

    Serial.printf("[History] Loaded %d entries\n", _count);
    return true;
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

void history_init() {
    _count = 0;
    _current_page = 0;
    load_from_file();
}

void history_record(const HistoryEntry& entry) {
    if (entry.station_id[0] == '\0') return;

    // Deduplicate: remove existing entry with same station_id
    for (int i = 0; i < _count; i++) {
        if (strcmp(_entries[i].station_id, entry.station_id) == 0) {
            // Shift everything from 0..i-1 down by one
            for (int j = i; j > 0; j--) {
                _entries[j] = _entries[j - 1];
            }
            _entries[0] = entry;
            save_to_file();
            Serial.printf("[History] Moved to top: %s\n", entry.title);
            return;
        }
    }

    // New entry: shift everything down, insert at front
    int new_count = (_count < MAX_HISTORY) ? _count + 1 : MAX_HISTORY;
    for (int i = new_count - 1; i > 0; i--) {
        _entries[i] = _entries[i - 1];
    }
    _entries[0] = entry;
    _count = new_count;

    save_to_file();
    Serial.printf("[History] Recorded: %s (%s)\n", entry.title, entry.place);
}

int history_count() {
    return _count;
}

const HistoryEntry* history_get(int index) {
    if (index < 0 || index >= _count) return nullptr;
    return &_entries[index];
}

void history_clear() {
    _count = 0;
    _current_page = 0;
    if (LittleFS.exists(HISTORY_FILE)) {
        LittleFS.remove(HISTORY_FILE);
    }
    Serial.println("[History] Cleared");
}

// ------------------------------------------------------------------
// Pagination
// ------------------------------------------------------------------

int history_get_page() {
    return _current_page;
}

int history_total_pages() {
    if (_count == 0) return 1;
    return (_count + HISTORY_PER_PAGE - 1) / HISTORY_PER_PAGE;
}

void history_set_page(int page) {
    int total = history_total_pages();
    _current_page = constrain(page, 0, total - 1);
}

void history_next_page() {
    int total = history_total_pages();
    _current_page = (_current_page + 1) % total;
    Serial.printf("[History] Page %d/%d\n", _current_page + 1, total);
}

// ------------------------------------------------------------------
// Rendering
// ------------------------------------------------------------------

static void draw_item(Arduino_GFX* gfx, int slot, const HistoryEntry& e) {
    int y_top = ITEMS_START_Y + slot * ITEM_HEIGHT;
    int card_y = y_top + 3;
    int card_h = ITEM_HEIGHT - 6;

    // Card background
    gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                        TH_CORNER_R, TH_CARD);

    // Station title (Unicode font for CJK/Cyrillic support)
    gfx->setFont(u8g2_font_cubic11_h_cjk);
    gfx->setUTF8Print(true);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT);
    gfx->setCursor(10, card_y + 18);

    char trunc_title[48];
    strncpy(trunc_title, e.title, 47);
    trunc_title[47] = '\0';
    utf8_truncate(trunc_title, 26);
    gfx->print(trunc_title);

    // Place + country below title
    gfx->setTextColor(TH_TEXT_SEC);
    gfx->setCursor(10, card_y + 38);
    char place_str[48];
    snprintf(place_str, sizeof(place_str), "%s, %s", e.place, e.country);
    utf8_truncate(place_str, 26);
    gfx->print(place_str);

    // Clear Unicode font
    gfx->setFont((const uint8_t*)nullptr);
    gfx->setUTF8Print(false);
}

void history_render(Arduino_GFX* gfx, int page) {
    if (!gfx) return;

    // Clear main area
    gfx->fillRect(0, 0, TH_DISPLAY_W, HIST_AREA_BOTTOM + 60, TH_BG);

    // Title (FreeSansBold)
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(10, FONT_SANS_ASCENT + 8);
    if (_count > 0) {
        gfx->printf("HISTORY (%d)", _count);
    } else {
        gfx->print("HISTORY");
    }
    gfx->setFont((const GFXfont*)nullptr);

    // Divider under title
    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    if (_count == 0) {
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT_DIM);
        gfx->setCursor(20, 200);
        gfx->print("No history yet");
        gfx->setCursor(15, 230);
        gfx->print("Play a station and");
        gfx->setCursor(15, 250);
        gfx->print("it will appear here");
        return;
    }

    // Draw items for current page
    int start_idx = page * HISTORY_PER_PAGE;
    int end_idx = min(start_idx + HISTORY_PER_PAGE, _count);

    for (int i = start_idx; i < end_idx; i++) {
        draw_item(gfx, i - start_idx, _entries[i]);
    }

    // Page indicator (only if multiple pages)
    int total_pages = history_total_pages();
    if (total_pages > 1) {
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(55, PAGE_INDICATOR_Y);
        gfx->printf("< %d / %d >", page + 1, total_pages);
    }
}

// ------------------------------------------------------------------
// Touch handling
// ------------------------------------------------------------------

void history_set_play_callback(HistoryPlayCallback cb) {
    _play_cb = cb;
}

bool history_handle_touch(int x, int y, Arduino_GFX* gfx) {
    if (y < ITEMS_START_Y) return false;
    if (y >= ITEMS_START_Y + HISTORY_PER_PAGE * ITEM_HEIGHT) return false;

    int slot = (y - ITEMS_START_Y) / ITEM_HEIGHT;
    int global_idx = _current_page * HISTORY_PER_PAGE + slot;

    if (global_idx < 0 || global_idx >= _count) return false;

    // Play — brief highlight
    Serial.printf("[History] Play tap: %s\n", _entries[global_idx].title);
    if (gfx) {
        int y_top = ITEMS_START_Y + slot * ITEM_HEIGHT;
        int card_y = y_top + 3;
        int card_h = ITEM_HEIGHT - 6;
        gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                            TH_CORNER_R, TH_CARD_HI);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, card_y + 16);
        char trunc_title[28];
        strncpy(trunc_title, _entries[global_idx].title, 27);
        trunc_title[27] = '\0';
        gfx->print(trunc_title);
        delay(80);
    }
    if (_play_cb) {
        _play_cb(global_idx);
    }

    return true;
}
