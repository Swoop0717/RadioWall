/**
 * Settings system for RadioWall.
 *
 * Manages device discovery (mDNS), device selection, and persistent
 * settings storage in LittleFS JSON.
 */

#ifndef SETTINGS_H
#define SETTINGS_H

#include <Arduino.h>

// Forward declaration
class Arduino_GFX;

#define MAX_DISCOVERED_DEVICES 8
#define MAX_GROUP_DEVICES 7  // max 8 devices minus 1 primary

struct DiscoveredDevice {
    char name[48];   // mDNS hostname / friendly name
    char ip[16];     // IP address string
    bool valid;      // false if IP couldn't be resolved (0.0.0.0)
    bool grouped;    // true if in multiroom group
};

// Callback when a device is selected as primary
typedef void (*DeviceSelectedCallback)(const char* ip, const char* name);

// Callback when a device's group status changes
typedef void (*GroupChangedCallback)(const char* slave_ip, bool joined);

// Initialize (load saved settings from LittleFS)
void settings_init();

// Get the saved WiiM IP (returns WIIM_IP from config.h if no saved setting)
const char* settings_get_wiim_ip();

// Start mDNS scan for LinkPlay devices (blocking, ~2s)
void settings_start_scan();

// Rendering
void settings_render(Arduino_GFX* gfx);

// Touch handling (returns true if handled)
bool settings_handle_touch(int x, int y, Arduino_GFX* gfx);

// Callbacks
void settings_set_device_callback(DeviceSelectedCallback cb);
void settings_set_group_callback(GroupChangedCallback cb);

// Get list of grouped device IPs (for boot rejoin)
int settings_get_group_ips(char ips[][16], int max_count);

#endif // SETTINGS_H
