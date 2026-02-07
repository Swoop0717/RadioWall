/**
 * Menu screen implementation for RadioWall.
 */

#include "menu.h"
#include "Arduino_GFX_Library.h"

// Layout constants
static const int TITLE_HEIGHT   = 40;
static const int ITEM_HEIGHT    = 80;
static const int ITEMS_START_Y  = TITLE_HEIGHT;  // 40
static const int DISPLAY_WIDTH  = 180;
static const int MENU_AREA_BOTTOM = 580;

// Colors
static const uint16_t COLOR_BG        = 0x0000;  // BLACK
static const uint16_t COLOR_TITLE     = 0x07FF;  // CYAN
static const uint16_t COLOR_ITEM_TEXT = 0xFFFF;  // WHITE
static const uint16_t COLOR_DIVIDER   = 0x4208;  // Dark gray
static const uint16_t COLOR_HIGHLIGHT = 0x0228;  // Dark teal
static const uint16_t COLOR_DISABLED  = 0x8410;  // Mid gray

// Static menu items
static MenuItem _items[MENU_ITEM_COUNT] = {
    { MENU_VOLUME,       "Volume",          true },
    { MENU_PAUSE_RESUME, "Pause / Resume",  true },
    { MENU_FAVORITES,    "Favorites",       true },
    { MENU_SLEEP_TIMER,  "Sleep Timer",     true },
    { MENU_EQUALIZER,    "Equalizer",       true },
    { MENU_SETTINGS,     "Settings",        true },
};

static MenuItemCallback _item_callback = nullptr;

void menu_init() {
    Serial.println("[Menu] Initialized (6 items)");
}

void menu_set_item_callback(MenuItemCallback cb) {
    _item_callback = cb;
}

// Draw a single menu item row
static void draw_item(Arduino_GFX* gfx, int index) {
    int y_top = ITEMS_START_Y + index * ITEM_HEIGHT;

    uint16_t text_color = _items[index].enabled ? COLOR_ITEM_TEXT : COLOR_DISABLED;

    gfx->setTextSize(2);
    gfx->setTextColor(text_color);
    gfx->setCursor(12, y_top + 30);
    gfx->print(_items[index].label);

    // Divider line at bottom of item
    gfx->drawFastHLine(5, y_top + ITEM_HEIGHT - 1, DISPLAY_WIDTH - 10, COLOR_DIVIDER);
}

void menu_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    // Clear menu area
    gfx->fillRect(0, 0, DISPLAY_WIDTH, MENU_AREA_BOTTOM, COLOR_BG);

    // Title
    gfx->setTextSize(2);
    gfx->setTextColor(COLOR_TITLE);
    gfx->setCursor(50, 12);
    gfx->print("MENU");

    // Divider under title
    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, DISPLAY_WIDTH - 10, COLOR_DIVIDER);

    // Draw each item
    for (int i = 0; i < MENU_ITEM_COUNT; i++) {
        draw_item(gfx, i);
    }
}

bool menu_handle_touch(int portrait_x, int portrait_y, Arduino_GFX* gfx) {
    // Ignore touches in the title bar
    if (portrait_y < ITEMS_START_Y) return false;

    int idx = (portrait_y - ITEMS_START_Y) / ITEM_HEIGHT;
    if (idx < 0 || idx >= MENU_ITEM_COUNT) return false;
    if (!_items[idx].enabled) return false;

    Serial.printf("[Menu] Tapped: %s\n", _items[idx].label);

    // Brief highlight feedback
    if (gfx) {
        int y_top = ITEMS_START_Y + idx * ITEM_HEIGHT;
        gfx->fillRect(0, y_top, DISPLAY_WIDTH, ITEM_HEIGHT, COLOR_HIGHLIGHT);

        gfx->setTextSize(2);
        gfx->setTextColor(COLOR_ITEM_TEXT);
        gfx->setCursor(12, y_top + 30);
        gfx->print(_items[idx].label);

        delay(80);

        // Restore normal appearance
        gfx->fillRect(0, y_top, DISPLAY_WIDTH, ITEM_HEIGHT, COLOR_BG);
        draw_item(gfx, idx);
    }

    if (_item_callback) {
        _item_callback(_items[idx].id);
    }

    return true;
}
