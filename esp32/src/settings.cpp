/**
 * Settings system implementation for RadioWall.
 *
 * Handles WiiM device discovery via mDNS, device selection,
 * and persistent settings storage in LittleFS JSON.
 */

#include "settings.h"
#include "config.h"
#include "theme.h"
#include "Arduino_GFX_Library.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <ESPmDNS.h>

static const char* SETTINGS_FILE = "/settings.json";

// Layout constants
static const int TITLE_HEIGHT          = 40;
static const int CURRENT_SECTION_HEIGHT = 50;
static const int DEVICE_ROW_HEIGHT     = 60;
static const int RESCAN_ROW_HEIGHT     = 60;
static const int SETTINGS_AREA_BOTTOM  = 580;

// Zoom row
static const int ZOOM_ROW_HEIGHT = 40;

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
    if (_saved_zoom < 1 || _saved_zoom > 3) _saved_zoom = 1;

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
// Rendering
// ------------------------------------------------------------------

static void draw_device_row(Arduino_GFX* gfx, int index, int y_top) {
    bool is_primary = _devices[index].valid &&
                      (strcmp(_devices[index].ip, _saved_ip) == 0);
    bool is_grouped = _devices[index].grouped;

    int card_y = y_top + 2;
    int card_h = DEVICE_ROW_HEIGHT - 4;

    // Card background
    gfx->fillRoundRect(TH_CARD_MARGIN, card_y, TH_CARD_W, card_h,
                        TH_CORNER_R, TH_CARD);

    // --- Left zone: device name + primary indicator ---
    gfx->setTextSize(1);
    if (!_devices[index].valid) {
        gfx->setTextColor(TH_DIVIDER);
    } else if (is_primary) {
        gfx->setTextColor(TH_PLAYING);  // GREEN
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

    // IP address below name
    gfx->setTextColor(_devices[index].valid ? TH_TEXT_SEC : TH_DIVIDER);
    gfx->setCursor(10, card_y + 38);
    if (_devices[index].valid) {
        gfx->print(_devices[index].ip);
    } else {
        gfx->print("(no IP)");
    }

    // --- Right zone: group toggle indicator ---
    if (_devices[index].valid && !is_primary) {
        gfx->setFont(&FreeSansBold10pt7b);
        gfx->setTextSize(1);
        gfx->setTextColor(is_grouped ? TH_ACCENT : TH_DIVIDER);
        gfx->setCursor(146, card_y + card_h / 2 + 5);
        gfx->print("G");
        gfx->setFont(NULL);

        // Vertical divider between zones
        gfx->drawFastVLine(SELECT_ZONE_W, card_y + 6, card_h - 12, TH_DIVIDER);
    }
}

void settings_render(Arduino_GFX* gfx) {
    if (!gfx) return;

    // Clear main area
    gfx->fillRect(0, 0, TH_DISPLAY_W, SETTINGS_AREA_BOTTOM, TH_BG);

    // Title (FreeSansBold)
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(36, FONT_SANS_ASCENT + 8);
    gfx->print("SETTINGS");
    gfx->setFont(NULL);

    // Divider under title
    gfx->drawFastHLine(5, TITLE_HEIGHT - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    // Zoom row card
    int zoom_card_y = TITLE_HEIGHT + 2;
    int zoom_card_h = ZOOM_ROW_HEIGHT - 4;
    gfx->fillRoundRect(TH_CARD_MARGIN, zoom_card_y, TH_CARD_W, zoom_card_h,
                        TH_CORNER_R, TH_CARD);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT);
    gfx->setCursor(10, zoom_card_y + 16);
    gfx->printf("Zoom: %dx", _saved_zoom);

    // Current device section (shifted down by zoom row)
    int dev_section_y = TITLE_HEIGHT + ZOOM_ROW_HEIGHT;
    gfx->setTextSize(1);
    gfx->setTextColor(TH_TEXT_SEC);
    gfx->setCursor(5, dev_section_y + 5);
    gfx->print("Current device:");

    gfx->setTextColor(TH_PLAYING);
    gfx->setCursor(5, dev_section_y + 18);
    if (_saved_name[0] != '\0') {
        char trunc[28];
        strncpy(trunc, _saved_name, 27);
        trunc[27] = '\0';
        gfx->print(trunc);
    } else {
        const char* ip = settings_get_wiim_ip();
        if (ip[0] != '\0') {
            gfx->print(ip);
        } else {
            gfx->print("(none)");
        }
    }

    // Group member count
    if (_group_count > 0) {
        gfx->setTextColor(TH_ACCENT);
        gfx->setCursor(5, dev_section_y + 38);
        gfx->printf("+ %d grouped", _group_count);
    }

    // Divider under current device
    int devices_start_y = dev_section_y + CURRENT_SECTION_HEIGHT;
    gfx->drawFastHLine(5, devices_start_y - 1, TH_DISPLAY_W - 10, TH_DIVIDER);

    // Scanning state
    if (_scanning) {
        gfx->setTextSize(1);
        gfx->setTextColor(TH_WARNING);
        gfx->setCursor(50, 250);
        gfx->print("Scanning...");
        return;
    }

    // Rescan button position
    int rescan_y = SETTINGS_AREA_BOTTOM - RESCAN_ROW_HEIGHT;

    // Max devices that fit between current section and rescan button
    int max_visible = (rescan_y - devices_start_y) / DEVICE_ROW_HEIGHT;

    if (_device_count == 0) {
        // No devices found
        gfx->setTextSize(1);
        gfx->setTextColor(TH_TEXT_DIM);
        gfx->setCursor(15, devices_start_y + 40);
        gfx->print("No devices found");
        gfx->setCursor(15, devices_start_y + 65);
        gfx->print("Serial cmd: W:<ip>");
    } else {
        // Draw discovered devices
        int visible = min(_device_count, max_visible);
        for (int i = 0; i < visible; i++) {
            draw_device_row(gfx, i, devices_start_y + i * DEVICE_ROW_HEIGHT);
        }
    }

    // Rescan button (card style)
    gfx->fillRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                        RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_CARD);
    gfx->drawRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                        RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_ACCENT);
    gfx->setFont(&FreeSansBold10pt7b);
    gfx->setTextSize(1);
    gfx->setTextColor(TH_ACCENT);
    gfx->setCursor(48, rescan_y + RESCAN_ROW_HEIGHT / 2 + 3);
    gfx->print("RESCAN");
    gfx->setFont(NULL);
}

// ------------------------------------------------------------------
// Touch handling
// ------------------------------------------------------------------

bool settings_handle_touch(int x, int y, Arduino_GFX* gfx) {
    if (_scanning) return false;

    int devices_start_y = TITLE_HEIGHT + ZOOM_ROW_HEIGHT + CURRENT_SECTION_HEIGHT;
    int rescan_y = SETTINGS_AREA_BOTTOM - RESCAN_ROW_HEIGHT;

    // Rescan button
    if (y >= rescan_y && y < SETTINGS_AREA_BOTTOM) {
        Serial.println("[Settings] Rescan tapped");
        if (gfx) {
            gfx->fillRoundRect(TH_CARD_MARGIN, rescan_y + 4, TH_CARD_W,
                                RESCAN_ROW_HEIGHT - 8, TH_CORNER_R, TH_CARD_HI);
            gfx->setFont(&FreeSansBold10pt7b);
            gfx->setTextSize(1);
            gfx->setTextColor(TH_TEXT);
            gfx->setCursor(48, rescan_y + RESCAN_ROW_HEIGHT / 2 + 3);
            gfx->print("RESCAN");
            gfx->setFont(NULL);
            delay(80);
        }
        // Show scanning state, scan, then show results
        _scanning = true;
        settings_render(gfx);
        settings_start_scan();
        settings_render(gfx);
        return true;
    }

    // Device rows
    if (y >= devices_start_y && y < rescan_y && _device_count > 0) {
        int idx = (y - devices_start_y) / DEVICE_ROW_HEIGHT;
        int max_visible = (rescan_y - devices_start_y) / DEVICE_ROW_HEIGHT;
        if (idx >= 0 && idx < _device_count && idx < max_visible) {
            // Skip invalid (unresolved) devices
            if (!_devices[idx].valid) {
                Serial.printf("[Settings] %s has no IP - try rescan\n", _devices[idx].name);
                return false;
            }

            bool is_primary = (strcmp(_devices[idx].ip, _saved_ip) == 0);
            bool is_group_zone = (x >= SELECT_ZONE_W);
            int y_top = devices_start_y + idx * DEVICE_ROW_HEIGHT;
            int card_y = y_top + 2;
            int card_h = DEVICE_ROW_HEIGHT - 4;

            if (is_group_zone && !is_primary) {
                // === GROUP TOGGLE ZONE ===
                bool currently_grouped = _devices[idx].grouped;

                if (currently_grouped) {
                    Serial.printf("[Settings] Ungrouping: %s (%s)\n",
                                 _devices[idx].name, _devices[idx].ip);
                    if (gfx) {
                        gfx->fillRoundRect(SELECT_ZONE_W + 1, card_y,
                                           TH_CARD_W - SELECT_ZONE_W + TH_CARD_MARGIN,
                                           card_h, TH_CORNER_R, TH_CARD_HI);
                        gfx->setTextSize(1);
                        gfx->setTextColor(TH_TEXT);
                        gfx->setCursor(SELECT_ZONE_W + 8, card_y + 25);
                        gfx->print("Leave");
                        delay(80);
                    }
                    _devices[idx].grouped = false;
                    remove_group_ip(_devices[idx].ip);
                } else {
                    Serial.printf("[Settings] Grouping: %s (%s)\n",
                                 _devices[idx].name, _devices[idx].ip);
                    if (gfx) {
                        gfx->fillRoundRect(SELECT_ZONE_W + 1, card_y,
                                           TH_CARD_W - SELECT_ZONE_W + TH_CARD_MARGIN,
                                           card_h, TH_CORNER_R, TH_CARD_HI);
                        gfx->setTextSize(1);
                        gfx->setTextColor(TH_TEXT);
                        gfx->setCursor(SELECT_ZONE_W + 10, card_y + 25);
                        gfx->print("Join");
                        delay(80);
                    }
                    _devices[idx].grouped = true;
                    add_group_ip(_devices[idx].ip);
                }

                save_to_file();
                if (_group_cb) {
                    _group_cb(_devices[idx].ip, !currently_grouped);
                }
                settings_render(gfx);
                return true;

            } else {
                // === SELECT PRIMARY ZONE ===
                Serial.printf("[Settings] Selected: %s (%s)\n",
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

                // If primary is actually changing, remove new primary from group
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

                settings_render(gfx);
                return true;
            }
        }
    }

    // Zoom row (between title and current device section)
    int zoom_y = TITLE_HEIGHT;
    if (y >= zoom_y && y < zoom_y + ZOOM_ROW_HEIGHT) {
        // Cycle zoom: 1 -> 2 -> 3 -> 1
        int new_zoom = (_saved_zoom % 3) + 1;

        // Validate zoom files exist before allowing 2x/3x
        if (new_zoom > 1) {
            char path[24];
            snprintf(path, sizeof(path), "/maps/zoom%d.bin", new_zoom);
            if (!LittleFS.exists(path)) {
                Serial.printf("[Settings] Zoom %dx file missing: %s\n", new_zoom, path);
                new_zoom = (new_zoom % 3) + 1;
                if (new_zoom > 1) {
                    snprintf(path, sizeof(path), "/maps/zoom%d.bin", new_zoom);
                    if (!LittleFS.exists(path)) new_zoom = 1;
                }
            }
        }

        _saved_zoom = new_zoom;
        save_to_file();
        Serial.printf("[Settings] Zoom set to %dx\n", _saved_zoom);

        if (gfx) {
            int zoom_card_y = TITLE_HEIGHT + 2;
            int zoom_card_h = ZOOM_ROW_HEIGHT - 4;
            gfx->fillRoundRect(TH_CARD_MARGIN, zoom_card_y, TH_CARD_W, zoom_card_h,
                                TH_CORNER_R, TH_CARD_HI);
            gfx->setTextSize(1);
            gfx->setTextColor(TH_TEXT);
            gfx->setCursor(10, zoom_card_y + 16);
            gfx->printf("Zoom: %dx", _saved_zoom);
            delay(80);
        }

        settings_render(gfx);
        return true;
    }

    return false;
}

// ------------------------------------------------------------------
// Zoom API
// ------------------------------------------------------------------

int settings_get_zoom() {
    return _saved_zoom;
}

void settings_set_zoom(int level, Arduino_GFX* gfx) {
    if (level < 1) level = 1;
    if (level > 3) level = 3;
    _saved_zoom = level;
    save_to_file();
    if (gfx) settings_render(gfx);
}
