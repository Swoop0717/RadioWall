/**
 * Menu screen for RadioWall.
 *
 * Full-screen menu accessed via long press on the physical button.
 * Replaces the map view while active; status bar shows BACK + STOP.
 */

#ifndef MENU_H
#define MENU_H

#include <Arduino.h>

// Forward declaration
class Arduino_GFX;

// Menu item identifiers
enum MenuItemId {
    MENU_VOLUME = 0,
    MENU_PAUSE_RESUME,      // Left third of split row
    MENU_FAVORITES,
    MENU_HISTORY,
    MENU_SLEEP_TIMER,
    MENU_SETTINGS,
    MENU_ITEM_COUNT,        // sentinel = 6
    MENU_STOP,              // Middle third of split row
    MENU_POWER_OFF          // Right third of split row
};

// Menu item definition
struct MenuItem {
    MenuItemId id;
    const char* label;
    bool enabled;
};

// Callback for when a menu item is tapped
typedef void (*MenuItemCallback)(MenuItemId item_id);

void menu_init();
void menu_set_item_callback(MenuItemCallback cb);

// Render the full menu into the map area (y 0-579)
void menu_render(Arduino_GFX* gfx);

// Handle a touch in the menu area. Returns true if an item was hit.
bool menu_handle_touch(int portrait_x, int portrait_y, Arduino_GFX* gfx);

#endif // MENU_H
