/**
 * Menu screen implementation for RadioWall.
 */

#include "menu.h"
#include "theme.h"
#include "Arduino_GFX_Library.h"

// Layout constants
static const int TITLE_HEIGHT   = 40;
static const int ITEM_HEIGHT    = 80;
static const int ITEMS_START_Y  = TITLE_HEIGHT;  // 40
static const int MENU_AREA_BOTTOM = 580;
static const int ICON_SIZE      = 16;

// Static menu items
static MenuItem _items[MENU_ITEM_COUNT] = {
    { MENU_VOLUME,       "Volume",          true },
    { MENU_PAUSE_RESUME, "Pause / Resume",  true },
    { MENU_FAVORITES,    "Favorites",       true },
    { MENU_HISTORY,      "History",         true },
    { MENU_SLEEP_TIMER,  "Sleep Timer",     true },
    { MENU_SETTINGS,     "Settings",        true },
};

// Icon pointers (same order as MenuItemId)
static const uint8_t* const _icons[] = {
    ICON_VOLUME, ICON_PLAY_PAUSE, ICON_HEART,
    ICON_CLOCK, ICON_MOON, ICON_GEAR
};

static MenuItemCallback _item_callback = nullptr;

void menu_init() {
    Serial.println("[Menu] Initialized (6 items)");
}

void menu_set_item_callback(MenuItemCallback cb) {
    _item_callback = cb;
}

// Draw a single menu item card
static void draw_item(Arduino_GFX* gfx, int index) {
    int y_top = ITEMS_START_Y + index * ITEM_HEIGHT;
    int card_y = y_top + 4;          // 4px top gap
    int card_h = ITEM_HEIGHT - 8;    // 8px total vertical gap

    uint16_t text_color = _items[index].enabled ? TH_TEXT : TH_TEXT_DIM;
    uint16_t icon_color = _items[index].enabled ? TH_ACCENT : TH_TEXT_DIM;

    // Card background
    gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                        TH_CORNER_R, TH_CARD);

    // Icon (centered vertically in card)
    int icon_y = card_y + (card_h - ICON_SIZE) / 2;
    if (index < MENU_ITEM_COUNT) {
        gfx->drawBitmap(14, icon_y, _icons[index], ICON_SIZE, ICON_SIZE, icon_color);
    }

    // Label text (FreeSansBold, baseline-positioned)
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(text_color);
    gfx->setCursor(38, card_y + card_h / 2 + FONT_SANS_ASCENT / 2 - 1);
    gfx->print(_items[index].label);
    gfx->setFont(NULL);
}

void menu_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    // Clear menu area
    gfx->fillRect(0, 0, TH_DISPLAY_W, MENU_AREA_BOTTOM, TH_BG);

    // Title (FreeSansBold, centered)
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(56, FONT_SANS_ASCENT + 8);
    gfx->print("MENU");
    gfx->setFont(NULL);

    // Divider under title
    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

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
        int card_y = y_top + 4;
        int card_h = ITEM_HEIGHT - 8;

        // Highlight card
        gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                            TH_CORNER_R, TH_CARD_HI);

        // Redraw icon
        int icon_y = card_y + (card_h - ICON_SIZE) / 2;
        gfx->drawBitmap(14, icon_y, _icons[idx], ICON_SIZE, ICON_SIZE, TH_ACCENT);

        // Redraw label
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(38, card_y + card_h / 2 + FONT_SANS_ASCENT / 2 - 1);
        gfx->print(_items[idx].label);
        gfx->setFont(NULL);

        delay(80);

        // Restore normal appearance
        gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                            TH_CORNER_R, TH_BG);
        draw_item(gfx, idx);
    }

    if (_item_callback) {
        _item_callback(_items[idx].id);
    }

    return true;
}
