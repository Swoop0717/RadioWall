/**
 * Settings system implementation for RadioWall.
 *
 * Handles WiiM device discovery via mDNS, device selection,
 * and persistent settings storage in LittleFS JSON.
 */

#include "settings.h"
#include "config.h"
#include "theme.h"
#include "display.h"
#include "Arduino_GFX_Library.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include "esp_sleep.h"

extern WiFiManager wm;  // Defined in main.cpp

static const char* SETTINGS_FILE = "/settings.json";

// Layout constants
static const int TITLE_HEIGHT          = 40;
static const int CURRENT_SECTION_HEIGHT = 50;
static const int DEVICE_ROW_HEIGHT     = 60;
static const int RESCAN_ROW_HEIGHT     = 60;
static const int SETTINGS_AREA_BOTTOM  = 580;
static const int MENU_ITEM_HEIGHT      = 80;  // Same as main menu

// State
static DiscoveredDevice _devices[MAX_DISCOVERED_DEVICES];
static int _device_count = 0;
static char _saved_ip[16] = "";
static char _saved_name[48] = "";
static bool _scanning = false;
static int _saved_zoom = 1;  // 1, 2, or 3

// Callbacks
static DeviceSelectedCallback _device_cb = nullptr;
static GroupChangedCallback _group_cb = nullptr;

// Persistent group IPs (loaded from settings.json)
static char _group_ips[MAX_GROUP_DEVICES][16];
static int _group_count = 0;

// Two-zone layout (matching favorites.cpp play/delete split)
static const int SELECT_ZONE_W = 120;  // Left: select primary (0-119)

// ------------------------------------------------------------------
// LittleFS persistence
// ------------------------------------------------------------------

static bool save_to_file() {
    File f = LittleFS.open(SETTINGS_FILE, "w");
    if (!f) {
        Serial.println("[Settings] Failed to open file for writing");
        return false;
    }

    DynamicJsonDocument doc(512);
    doc["ip"] = _saved_ip;
    doc["n"] = _saved_name;
    doc["zoom"] = _saved_zoom;

    if (_group_count > 0) {
        JsonArray grp = doc.createNestedArray("grp");
        for (int i = 0; i < _group_count; i++) {
            grp.add(_group_ips[i]);
        }
    }

    serializeJson(doc, f);
    f.close();
    Serial.printf("[Settings] Saved: %s (%s) + %d grouped, zoom=%dx\n",
                  _saved_name, _saved_ip, _group_count, _saved_zoom);
    return true;
}

static bool load_from_file() {
    if (!LittleFS.exists(SETTINGS_FILE)) {
        Serial.println("[Settings] No settings file found");
        return true;  // Not an error, just use defaults
    }

    File f = LittleFS.open(SETTINGS_FILE, "r");
    if (!f) {
        Serial.println("[Settings] Failed to open settings file");
        return false;
    }

    DynamicJsonDocument doc(512);
    DeserializationError error = deserializeJson(doc, f);
    f.close();

    if (error) {
        Serial.printf("[Settings] JSON parse error: %s\n", error.c_str());
        return false;
    }

    strncpy(_saved_ip, doc["ip"] | "", sizeof(_saved_ip) - 1);
    _saved_ip[sizeof(_saved_ip) - 1] = '\0';
    strncpy(_saved_name, doc["n"] | "", sizeof(_saved_name) - 1);
    _saved_name[sizeof(_saved_name) - 1] = '\0';
    _saved_zoom = doc["zoom"] | 1;
    if (_saved_zoom < 1 || _saved_zoom > 5) _saved_zoom = 1;

    // Load group IPs
    _group_count = 0;
    if (doc.containsKey("grp")) {
        JsonArray grp = doc["grp"].as<JsonArray>();
        for (JsonVariant v : grp) {
            if (_group_count >= MAX_GROUP_DEVICES) break;
            strncpy(_group_ips[_group_count], v.as<const char*>(), 15);
            _group_ips[_group_count][15] = '\0';
            _group_count++;
        }
    }

    if (_saved_ip[0] != '\0') {
        Serial.printf("[Settings] Loaded: %s (%s) + %d grouped\n",
                      _saved_name, _saved_ip, _group_count);
    }
    return true;
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

void settings_init() {
    _device_count = 0;
    _saved_ip[0] = '\0';
    _saved_name[0] = '\0';
    load_from_file();
}

const char* settings_get_wiim_ip() {
    if (_saved_ip[0] != '\0') return _saved_ip;
    #ifdef WIIM_IP
        return WIIM_IP;
    #else
        return "";
    #endif
}

void settings_start_scan() {
    _scanning = true;
    _device_count = 0;

    Serial.println("[Settings] Scanning for LinkPlay devices...");

    int n = MDNS.queryService("linkplay", "tcp");

    for (int i = 0; i < n && _device_count < MAX_DISCOVERED_DEVICES; i++) {
        String ip_str = MDNS.IP(i).toString();
        String hostname = MDNS.hostname(i);

        // Flag devices with unresolved IP (mDNS resolution failure)
        bool has_ip = (ip_str != "0.0.0.0" && ip_str.length() > 0);
        _devices[_device_count].valid = has_ip;

        strncpy(_devices[_device_count].ip, ip_str.c_str(), sizeof(_devices[0].ip) - 1);
        _devices[_device_count].ip[sizeof(_devices[0].ip) - 1] = '\0';

        if (hostname.length() > 0) {
            strncpy(_devices[_device_count].name, hostname.c_str(), sizeof(_devices[0].name) - 1);
        } else {
            strncpy(_devices[_device_count].name, ip_str.c_str(), sizeof(_devices[0].name) - 1);
        }
        _devices[_device_count].name[sizeof(_devices[0].name) - 1] = '\0';

        Serial.printf("[Settings]   %s (%s)\n",
                      _devices[_device_count].name, _devices[_device_count].ip);
        _device_count++;
    }

    _scanning = false;
    Serial.printf("[Settings] Found %d LinkPlay device(s)\n", _device_count);

    // Sync grouped flags with persisted group IPs
    for (int d = 0; d < _device_count; d++) {
        _devices[d].grouped = false;
        if (!_devices[d].valid) continue;
        if (strcmp(_devices[d].ip, _saved_ip) == 0) continue;
        for (int g = 0; g < _group_count; g++) {
            if (strcmp(_devices[d].ip, _group_ips[g]) == 0) {
                _devices[d].grouped = true;
                break;
            }
        }
    }
}

// ------------------------------------------------------------------
// Group helpers
// ------------------------------------------------------------------

static bool add_group_ip(const char* ip) {
    for (int i = 0; i < _group_count; i++) {
        if (strcmp(_group_ips[i], ip) == 0) return false;  // Already in group
    }
    if (_group_count >= MAX_GROUP_DEVICES) return false;
    strncpy(_group_ips[_group_count], ip, 15);
    _group_ips[_group_count][15] = '\0';
    _group_count++;
    return true;
}

static bool remove_group_ip(const char* ip) {
    for (int i = 0; i < _group_count; i++) {
        if (strcmp(_group_ips[i], ip) == 0) {
            for (int j = i; j < _group_count - 1; j++) {
                strcpy(_group_ips[j], _group_ips[j + 1]);
            }
            _group_count--;
            return true;
        }
    }
    return false;
}

static void sync_grouped_flags() {
    for (int d = 0; d < _device_count; d++) {
        _devices[d].grouped = false;
        if (!_devices[d].valid) continue;
        if (strcmp(_devices[d].ip, _saved_ip) == 0) continue;
        for (int g = 0; g < _group_count; g++) {
            if (strcmp(_devices[d].ip, _group_ips[g]) == 0) {
                _devices[d].grouped = true;
                break;
            }
        }
    }
}

void settings_set_device_callback(DeviceSelectedCallback cb) {
    _device_cb = cb;
}

void settings_set_group_callback(GroupChangedCallback cb) {
    _group_cb = cb;
}

int settings_get_group_ips(char ips[][16], int max_count) {
    int count = min(_group_count, max_count);
    for (int i = 0; i < count; i++) {
        strncpy(ips[i], _group_ips[i], 15);
        ips[i][15] = '\0';
    }
    return count;
}

// ------------------------------------------------------------------
// Rendering: Settings sub-menu (2 items: WiFi, Devices)
// ------------------------------------------------------------------

static void draw_settings_item(Arduino_GFX* gfx, int index, const char* label,
                                const uint8_t* icon, uint16_t icon_color) {
    int y_top = TITLE_HEIGHT + index * MENU_ITEM_HEIGHT;
    int card_y = y_top + 4;
    int card_h = MENU_ITEM_HEIGHT - 8;

    gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                        TH_CORNER_R, TH_CARD);

    int icon_y = card_y + (card_h - 16) / 2;
    gfx->drawBitmap(14, icon_y, icon, 16, 16, icon_color);

    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT);
    gfx->setCursor(38, card_y + card_h / 2 + FONT_SANS_ASCENT / 2 - 1);
    gfx->print(label);
    gfx->setFont((const GFXfont*)nullptr);
}

void settings_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    gfx->fillRect(0, 0, TH_DISPLAY_W, SETTINGS_AREA_BOTTOM, TH_BG);

    // Title
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(36, FONT_SANS_ASCENT + 8);
    gfx->print("SETTINGS");
    gfx->setFont((const GFXfont*)nullptr);

    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    // Item 0: WiFi
    // Use a simple "W" indicator for WiFi status
    draw_settings_item(gfx, 0, "WiFi", ICON_GEAR, TH_ACCENT);

    // Item 1: Devices
    draw_settings_item(gfx, 1, "Devices", ICON_VOLUME, TH_ACCENT);
}

bool settings_handle_touch(int x, int y, Arduino_GFX* gfx) {
    if (y < TITLE_HEIGHT) return false;

    int idx = (y - TITLE_HEIGHT) / MENU_ITEM_HEIGHT;
    if (idx < 0 || idx > 1) return false;

    // Highlight feedback
    if (gfx) {
        int card_y = TITLE_HEIGHT + idx * MENU_ITEM_HEIGHT + 4;
        int card_h = MENU_ITEM_HEIGHT - 8;
        gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                            TH_CORNER_R, TH_CARD_HI);
        delay(80);
    }

    // Return the index: 0=WiFi, 1=Devices
    // The callback routing happens in main.cpp via the touch handler
    Serial.printf("[Settings] Tapped: %s\n", idx == 0 ? "WiFi" : "Devices");
    return true;  // Caller checks which item via coordinates
}

// ------------------------------------------------------------------
// Rendering: WiFi info page
// ------------------------------------------------------------------

// WiFi icon (16x16): signal bars
static const uint8_t ICON_WIFI[] PROGMEM = {
    0x00, 0x00, 0x03, 0xC0, 0x0F, 0xF0, 0x1C, 0x38,
    0x30, 0x0C, 0x67, 0xE6, 0x0F, 0xF0, 0x18, 0x18,
    0x03, 0xC0, 0x07, 0xE0, 0x01, 0x80, 0x01, 0x80,
    0x03, 0xC0, 0x01, 0x80, 0x00, 0x00, 0x00, 0x00
};

void settings_wifi_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    gfx->fillRect(0, 0, TH_DISPLAY_W, SETTINGS_AREA_BOTTOM, TH_BG);

    // Title
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(60, FONT_SANS_ASCENT + 8);
    gfx->print("WIFI");
    gfx->setFont((const GFXfont*)nullptr);

    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    bool connected = (WiFi.status() == WL_CONNECTED);
    int row_y = TITLE_HEIGHT + 10;

    // Status indicator
    gfx->setTextSize(1);
    gfx->setTextColor(connected ? TH_PLAYING : TH_DANGER);
    gfx->setCursor(10, row_y);
    gfx->print(connected ? "Connected" : "Disconnected");
    row_y += 24;

    if (connected) {
        // SSID
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(10, row_y);
        gfx->print("SSID:");
        row_y += 14;
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, row_y);
        char ssid_buf[24];
        strncpy(ssid_buf, WiFi.SSID().c_str(), 23);
        ssid_buf[23] = '\0';
        gfx->print(ssid_buf);
        row_y += 22;

        // Device IP
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(10, row_y);
        gfx->print("IP:");
        row_y += 14;
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, row_y);
        gfx->print(WiFi.localIP().toString().c_str());
        row_y += 22;

        // Gateway
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(10, row_y);
        gfx->print("Gateway:");
        row_y += 14;
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, row_y);
        gfx->print(WiFi.gatewayIP().toString().c_str());
        row_y += 22;

        // Signal strength
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(10, row_y);
        gfx->print("Signal:");
        row_y += 14;
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, row_y);
        int rssi = WiFi.RSSI();
        gfx->printf("%d dBm", rssi);
        row_y += 22;

        // MAC
        gfx->setTextColor(TH_TEXT_SEC);
        gfx->setCursor(10, row_y);
        gfx->print("MAC:");
        row_y += 14;
        gfx->setTextColor(TH_TEXT);
        gfx->setCursor(10, row_y);
        gfx->print(WiFi.macAddress().c_str());
        row_y += 30;
    }

    // Divider before buttons
    gfx->drawFastHLine(5, row_y, TH_DISPLAY_W - 10, TH_DIVIDER);
    row_y += 10;

    // "Start AP Setup" button
    int btn_h = 44;
    gfx->fillRoundRect(TH_CARD_MARGIN, row_y, TH_CARD_W, btn_h,
                        TH_CORNER_R, TH_CARD);
    gfx->drawRoundRect(TH_CARD_MARGIN, row_y, TH_CARD_W, btn_h,
                        TH_CORNER_R, TH_WARNING);
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_WARNING);
    gfx->setCursor(18, row_y + btn_h / 2 + FONT_SANS_ASCENT / 2 - 1);
    gfx->print("AP Setup");
    gfx->setFont((const GFXfont*)nullptr);

    row_y += btn_h + 10;

    // "Reset WiFi" button
    gfx->fillRoundRect(TH_CARD_MARGIN, row_y, TH_CARD_W, btn_h,
                        TH_CORNER_R, TH_CARD);
    gfx->drawRoundRect(TH_CARD_MARGIN, row_y, TH_CARD_W, btn_h,
                        TH_CORNER_R, TH_DANGER);
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_DANGER);
    gfx->setCursor(18, row_y + btn_h / 2 + FONT_SANS_ASCENT / 2 - 1);
    gfx->print("Reset WiFi");
    gfx->setFont((const GFXfont*)nullptr);
}

// Compute button Y positions (must match render)
static int wifi_buttons_y() {
    bool connected = (WiFi.status() == WL_CONNECTED);
    int row_y = TITLE_HEIGHT + 10;
    row_y += 24;  // status line
    if (connected) {
        row_y += 14 + 22;  // SSID
        row_y += 14 + 22;  // IP
        row_y += 14 + 22;  // Gateway
        row_y += 14 + 22;  // Signal
        row_y += 14 + 30;  // MAC
    }
    row_y += 10;  // divider gap
    return row_y;
}

bool settings_wifi_handle_touch(int x, int y, Arduino_GFX* gfx) {
    int btn_start = wifi_buttons_y();
    int btn_h = 44;

    // AP Setup button
    if (y >= btn_start && y < btn_start + btn_h) {
        Serial.println("[Settings/WiFi] AP Setup tapped");
        if (gfx) {
            gfx->fillRoundRect(TH_CARD_MARGIN, btn_start, TH_CARD_W, btn_h,
                                TH_CORNER_R, TH_CARD_HI);
            gfx->setFont(&FreeSansBold10pt7b);
            gfx->setTextColor(TH_TEXT);
            gfx->setCursor(18, btn_start + btn_h / 2 + FONT_SANS_ASCENT / 2 - 1);
            gfx->print("Starting...");
            gfx->setFont((const GFXfont*)nullptr);
        }
        delay(300);
        settings_wifi_start_portal();
        settings_wifi_render(gfx);
        return true;
    }

    // Reset WiFi button
    int reset_y = btn_start + btn_h + 10;
    if (y >= reset_y && y < reset_y + btn_h) {
        Serial.println("[Settings/WiFi] Reset tapped");
        if (gfx) {
            gfx->fillRoundRect(TH_CARD_MARGIN, reset_y, TH_CARD_W, btn_h,
                                TH_CORNER_R, TH_CARD_HI);
            gfx->setFont(&FreeSansBold10pt7b);
            gfx->setTextColor(TH_DANGER);
            gfx->setCursor(18, reset_y + btn_h / 2 + FONT_SANS_ASCENT / 2 - 1);
            gfx->print("Resetting...");
            gfx->setFont((const GFXfont*)nullptr);
        }
        delay(500);
        settings_wifi_reset();
        return true;
    }

    return false;
}

// ------------------------------------------------------------------
// Rendering: Devices page
// ------------------------------------------------------------------

static void draw_device_row(Arduino_GFX* gfx, int index, int y_top) {
    bool is_primary = _devices[index].valid &&
                      (strcmp(_devices[index].ip, _saved_ip) == 0);
    bool is_grouped = _devices[index].grouped;

    int card_y = y_top + 2;
    int card_h = DEVICE_ROW_HEIGHT - 4;

    gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                        TH_CORNER_R, TH_CARD);

    // Left zone: device name + primary indicator
    gfx->setTextSize(1);
    if (!_devices[index].valid) {
        gfx->setTextColor(TH_DIVIDER);
    } else if (is_primary) {
        gfx->setTextColor(TH_PLAYING);
    } else {
        gfx->setTextColor(TH_TEXT);
    }
    gfx->setCursor(10, card_y + 10);

    char trunc_name[19];
    if (is_primary) {
        trunc_name[0] = '*';
        strncpy(trunc_name + 1, _devices[index].name, 17);
        trunc_name[18] = '\0';
    } else {
        strncpy(trunc_name, _devices[index].name, 18);
        trunc_name[18] = '\0';
    }
    gfx->print(trunc_name);

    gfx->setTextColor(_devices[index].valid ? TH_TEXT_SEC : TH_DIVIDER);
    gfx->setCursor(10, card_y + 38);
    gfx->print(_devices[index].valid ? _devices[index].ip : "(no IP)");

    // Right zone: group toggle
    if (_devices[index].valid && !is_primary) {
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(is_grouped ? TH_ACCENT : TH_DIVIDER);
        gfx->setCursor(146, card_y + card_h / 2 + 5);
        gfx->print("G");
        gfx->setFont((const GFXfont*)nullptr);

        gfx->drawFastVLine(SELECT_ZONE_W, card_y + 6, card_h - 12, TH_DIVIDER);
    }
}

void settings_devices_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    gfx->fillRect(0, 0, TH_DISPLAY_W, SETTINGS_AREA_BOTTOM, TH_BG);

    // Title
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(36, FONT_SANS_ASCENT + 8);
    gfx->print("DEVICES");
    gfx->setFont((const GFXfont*)nullptr);

    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    // Current device info
    int info_y = TITLE_HEIGHT + 5;
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT_SEC);
    gfx->setCursor(10, info_y);
    gfx->print("Current device:");
    info_y += 14;

    gfx->setTextColor(TH_PLAYING);
    gfx->setCursor(10, info_y);
    if (_saved_name[0] != '\0') {
        char trunc[24];
        strncpy(trunc, _saved_name, 23);
        trunc[23] = '\0';
        gfx->print(trunc);
    } else {
        const char* ip = settings_get_wiim_ip();
        gfx->print(ip[0] != '\0' ? ip : "(none)");
    }
    info_y += 14;

    gfx->setTextColor(TH_TEXT_SEC);
    gfx->setCursor(10, info_y);
    const char* ip = settings_get_wiim_ip();
    if (ip[0] != '\0') {
        gfx->print(ip);
    }
    info_y += 14;

    if (_group_count > 0) {
        gfx->setTextColor(TH_ACCENT);
        gfx->setCursor(10, info_y);
        gfx->printf("+ %d grouped", _group_count);
    }

    // Divider
    int devices_start_y = TITLE_HEIGHT + CURRENT_SECTION_HEIGHT + 20;
    gfx->drawFastHLine(5, devices_start_y - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    // Scanning state
    if (_scanning) {
        gfx->setTextColor(TH_WARNING);
        gfx->setCursor(50, 250);
        gfx->print("Scanning...");
        return;
    }

    // Rescan button position
    int rescan_y = SETTINGS_AREA_BOTTOM - RESCAN_ROW_HEIGHT;
    int max_visible = (rescan_y - devices_start_y) / DEVICE_ROW_HEIGHT;

    if (_device_count == 0) {
        gfx->setTextColor(TH_TEXT_DIM);
        gfx->setCursor(15, devices_start_y + 40);
        gfx->print("No devices found");
        gfx->setCursor(15, devices_start_y + 65);
        gfx->print("Serial cmd: W:<ip>");
    } else {
        int visible = min(_device_count, max_visible);
        for (int i = 0; i < visible; i++) {
            draw_device_row(gfx, i, devices_start_y + i * DEVICE_ROW_HEIGHT);
        }
    }

    // Rescan button
    gfx->fillRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                        RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_CARD);
    gfx->drawRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                        RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_ACCENT);
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(48, rescan_y + RESCAN_ROW_HEIGHT / 2 + 3);
    gfx->print("RESCAN");
    gfx->setFont((const GFXfont*)nullptr);
}

bool settings_devices_handle_touch(int x, int y, Arduino_GFX* gfx) {
    if (_scanning) return false;

    int devices_start_y = TITLE_HEIGHT + CURRENT_SECTION_HEIGHT + 20;
    int rescan_y = SETTINGS_AREA_BOTTOM - RESCAN_ROW_HEIGHT;

    // Rescan button
    if (y >= rescan_y && y < SETTINGS_AREA_BOTTOM) {
        Serial.println("[Settings/Devices] Rescan tapped");
        if (gfx) {
            gfx->fillRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                                RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_CARD_HI);
            gfx->setFont(&FreeSansBold10pt7b);
            gfx->setTextColor(TH_TEXT);
            gfx->setCursor(48, rescan_y + RESCAN_ROW_HEIGHT / 2 + 3);
            gfx->print("RESCAN");
            gfx->setFont((const GFXfont*)nullptr);
            delay(80);
        }
        _scanning = true;
        settings_devices_render(gfx);
        settings_start_scan();
        settings_devices_render(gfx);
        return true;
    }

    // Device rows
    if (y >= devices_start_y && y < rescan_y && _device_count > 0) {
        int idx = (y - devices_start_y) / DEVICE_ROW_HEIGHT;
        int max_visible = (rescan_y - devices_start_y) / DEVICE_ROW_HEIGHT;
        if (idx >= 0 && idx < _device_count && idx < max_visible) {
            if (!_devices[idx].valid) {
                Serial.printf("[Settings/Devices] %s has no IP\n", _devices[idx].name);
                return false;
            }

            bool is_primary = (strcmp(_devices[idx].ip, _saved_ip) == 0);
            bool is_group_zone = (x >= SELECT_ZONE_W);
            int y_top = devices_start_y + idx * DEVICE_ROW_HEIGHT;
            int card_y = y_top + 2;
            int card_h = DEVICE_ROW_HEIGHT - 4;

            if (is_group_zone && !is_primary) {
                // Group toggle
                bool currently_grouped = _devices[idx].grouped;

                if (gfx) {
                    gfx->fillRoundRect(SELECT_ZONE_W + 1, card_y,
                                       TH_CARD_W - SELECT_ZONE_W + TH_CARD_MARGIN,
                                       card_h, TH_CORNER_R, TH_CARD_HI);
                    gfx->setTextSize(1);
                    gfx->setTextColor(TH_TEXT);
                    gfx->setCursor(SELECT_ZONE_W + 8, card_y + 25);
                    gfx->print(currently_grouped ? "Leave" : "Join");
                    delay(80);
                }

                _devices[idx].grouped = !currently_grouped;
                if (currently_grouped) {
                    remove_group_ip(_devices[idx].ip);
                } else {
                    add_group_ip(_devices[idx].ip);
                }

                save_to_file();
                if (_group_cb) {
                    _group_cb(_devices[idx].ip, !currently_grouped);
                }
                settings_devices_render(gfx);
                return true;

            } else {
                // Select primary
                Serial.printf("[Settings/Devices] Selected: %s (%s)\n",
                             _devices[idx].name, _devices[idx].ip);

                if (gfx) {
                    gfx->fillRoundRect(TH_CARD_MARGIN, card_y,
                                       SELECT_ZONE_W - TH_CARD_MARGIN,
                                       card_h, TH_CORNER_R, TH_CARD_HI);
                    gfx->setTextSize(1);
                    gfx->setTextColor(TH_TEXT);
                    gfx->setCursor(10, card_y + 10);
                    char trunc[19];
                    strncpy(trunc, _devices[idx].name, 18);
                    trunc[18] = '\0';
                    gfx->print(trunc);
                    delay(80);
                }

                if (strcmp(_saved_ip, _devices[idx].ip) != 0) {
                    remove_group_ip(_devices[idx].ip);
                }

                strncpy(_saved_ip, _devices[idx].ip, sizeof(_saved_ip) - 1);
                _saved_ip[sizeof(_saved_ip) - 1] = '\0';
                strncpy(_saved_name, _devices[idx].name, sizeof(_saved_name) - 1);
                _saved_name[sizeof(_saved_name) - 1] = '\0';
                save_to_file();
                sync_grouped_flags();

                if (_device_cb) {
                    _device_cb(_saved_ip, _saved_name);
                }

                settings_devices_render(gfx);
                return true;
            }
        }
    }

    return false;
}

// ------------------------------------------------------------------
// WiFi management
// ------------------------------------------------------------------

void settings_wifi_reset() {
    Serial.println("[Settings] Clearing WiFi credentials and restarting...");
    wm.resetSettings();
    delay(500);
    ESP.restart();
}

void settings_wifi_start_portal() {
    Serial.println("[Settings] Starting captive portal (button to cancel)...");
    display_show_wifi_portal(true);  // Show cancel instructions

    wm.setConfigPortalBlocking(false);
    wm.startConfigPortal("RadioWall");

    // Non-blocking loop: check portal + button cancel
    while (true) {
        wm.process();
        if (WiFi.status() == WL_CONNECTED) {
            Serial.printf("[WiFi] Connected via portal: %s\n",
                          WiFi.localIP().toString().c_str());
            break;
        }
        if (digitalRead(0) == LOW) {
            delay(300);  // Debounce
            Serial.println("[WiFi] Portal cancelled by button press");
            break;
        }
        delay(10);
    }

    wm.stopConfigPortal();
    // Caller re-renders settings screen
}

// ------------------------------------------------------------------
// Power Off (deep sleep)
// ------------------------------------------------------------------

void settings_power_off() {
    Serial.println("[Settings] Entering deep sleep (press button to wake)...");
    Serial.flush();

    // Turn off display backlight
    pinMode(1, OUTPUT);
    digitalWrite(1, LOW);

    // Configure GPIO 0 (button) as wakeup source (active LOW)
    esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, 0);

    delay(100);
    esp_deep_sleep_start();
    // Never reaches here — ESP32 resets on wake
}

// ------------------------------------------------------------------
// Zoom API
// ------------------------------------------------------------------

int settings_get_zoom() {
    return _saved_zoom;
}

void settings_set_zoom(int level, Arduino_GFX* gfx) {
    if (level < 1) level = 1;
    if (level > 5) level = 5;
    _saved_zoom = level;
    save_to_file();
    if (gfx) settings_render(gfx);
}

void settings_set_zoom_no_render(int level) {
    if (level < 1) level = 1;
    if (level > 5) level = 5;
    _saved_zoom = level;
    save_to_file();
}
