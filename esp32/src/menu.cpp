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

// 3-way split boundaries (Play/Pause | Stop | Power Off)
static const int SPLIT_X1       = 62;   // First divider
static const int SPLIT_X2       = 120;  // Second divider

// Static menu items (display order — split row at bottom)
static MenuItem _items[MENU_ITEM_COUNT] = {
    { MENU_VOLUME,       "Volume",          true },
    { MENU_FAVORITES,    "Favorites",       true },
    { MENU_HISTORY,      "History",         true },
    { MENU_SLEEP_TIMER,  "Sleep Timer",     true },
    { MENU_SETTINGS,     "Settings",        true },
    { MENU_PAUSE_RESUME, "",                true },  // Split row (icons only)
};

// Icon pointers (same display order as _items, index 0-4)
static const uint8_t* const _icons[] = {
    ICON_VOLUME, ICON_HEART, ICON_CLOCK,
    ICON_MOON, ICON_GEAR
};

static const int SPLIT_ROW_INDEX = 5;  // Last item = split row

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

    if (index == SPLIT_ROW_INDEX) {
        // --- 3-way split: Play/Pause | Stop | Power Off — icons only ---
        int icon_y = card_y + (card_h - ICON_SIZE) / 2;

        // Zone centers for icon placement
        int cx1 = (TH_CARD_MARGIN + SPLIT_X1) / 2;   // Center of left zone
        int cx2 = (SPLIT_X1 + SPLIT_X2) / 2;          // Center of middle zone
        int cx3 = (SPLIT_X2 + TH_CARD_MARGIN + TH_CARD_W) / 2;  // Center of right zone

        // Left: Play/Pause icon
        gfx->drawBitmap(cx1 - ICON_SIZE / 2, icon_y, ICON_PLAY_PAUSE, ICON_SIZE, ICON_SIZE, icon_color);

        // First divider
        gfx->drawFastVLine(SPLIT_X1, card_y + 6, card_h - 12, TH_DIVIDER);

        // Middle: Stop icon
        gfx->drawBitmap(cx2 - ICON_SIZE / 2, icon_y, ICON_STOP, ICON_SIZE, ICON_SIZE, icon_color);

        // Second divider
        gfx->drawFastVLine(SPLIT_X2, card_y + 6, card_h - 12, TH_DIVIDER);

        // Right: Power Off icon
        gfx->drawBitmap(cx3 - ICON_SIZE / 2, icon_y, ICON_POWER, ICON_SIZE, ICON_SIZE, TH_DANGER);
    } else {
        // --- Normal full-width row ---
        int icon_y = card_y + (card_h - ICON_SIZE) / 2;
        if (index < 5) {
            gfx->drawBitmap(14, icon_y, _icons[index], ICON_SIZE, ICON_SIZE, icon_color);
        }

        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(text_color);
        gfx->setCursor(38, card_y + card_h / 2 + FONT_SANS_ASCENT / 2 - 1);
        gfx->print(_items[index].label);
        gfx->setFont((const GFXfont*)nullptr);
    }
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
    gfx->setFont((const GFXfont*)nullptr);

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

    // 3-way split row: left = Play/Pause, middle = Stop, right = Power Off
    MenuItemId action_id = _items[idx].id;
    if (idx == SPLIT_ROW_INDEX) {
        if (portrait_x >= SPLIT_X2) {
            action_id = MENU_POWER_OFF;
            Serial.println("[Menu] Tapped: Power Off");
        } else if (portrait_x >= SPLIT_X1) {
            action_id = MENU_STOP;
            Serial.println("[Menu] Tapped: Stop");
        } else {
            Serial.println("[Menu] Tapped: Play/Pause");
        }
    } else {
        Serial.printf("[Menu] Tapped: %s\n", _items[idx].label);
    }

    // Brief highlight feedback
    if (gfx) {
        int y_top = ITEMS_START_Y + idx * ITEM_HEIGHT;
        int card_y = y_top + 4;
        int card_h = ITEM_HEIGHT - 8;

        if (idx == SPLIT_ROW_INDEX) {
            // Highlight only the tapped third
            int icon_y = card_y + (card_h - ICON_SIZE) / 2;
            int cx1 = (TH_CARD_MARGIN + SPLIT_X1) / 2;
            int cx2 = (SPLIT_X1 + SPLIT_X2) / 2;
            int cx3 = (SPLIT_X2 + TH_CARD_MARGIN + TH_CARD_W) / 2;

            if (portrait_x < SPLIT_X1) {
                gfx->fillRoundRect(TH_CARD_MARGIN, card_y, SPLIT_X1 - TH_CARD_MARGIN,
                                    card_h, TH_CORNER_R, TH_CARD_HI);
                gfx->drawBitmap(cx1 - ICON_SIZE / 2, icon_y, ICON_PLAY_PAUSE, ICON_SIZE, ICON_SIZE, TH_ACCENT);
            } else if (portrait_x < SPLIT_X2) {
                gfx->fillRoundRect(SPLIT_X1, card_y, SPLIT_X2 - SPLIT_X1,
                                    card_h, TH_CORNER_R, TH_CARD_HI);
                gfx->drawBitmap(cx2 - ICON_SIZE / 2, icon_y, ICON_STOP, ICON_SIZE, ICON_SIZE, TH_ACCENT);
            } else {
                gfx->fillRoundRect(SPLIT_X2, card_y, TH_CARD_W + TH_CARD_MARGIN - SPLIT_X2,
                                    card_h, TH_CORNER_R, TH_CARD_HI);
                gfx->drawBitmap(cx3 - ICON_SIZE / 2, icon_y, ICON_POWER, ICON_SIZE, ICON_SIZE, TH_DANGER);
            }
            delay(80);
            draw_item(gfx, idx);
        } else {
            // Normal full-width highlight
            gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                                TH_CORNER_R, TH_CARD_HI);

            int icon_y = card_y + (card_h - ICON_SIZE) / 2;
            if (idx < 5) {
                gfx->drawBitmap(14, icon_y, _icons[idx], ICON_SIZE, ICON_SIZE, TH_ACCENT);
            }

            gfx->setFont(&FreeSansBold10pt7b);
            gfx->setTextSize(1);
            gfx->setTextColor(TH_TEXT);
            gfx->setCursor(38, card_y + card_h / 2 + FONT_SANS_ASCENT / 2 - 1);
            gfx->print(_items[idx].label);
            gfx->setFont((const GFXfont*)nullptr);

            delay(80);

            gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                                TH_CORNER_R, TH_BG);
            draw_item(gfx, idx);
        }
    }

    if (_item_callback) {
        _item_callback(action_id);
    }

    return true;
}
