/**
 * RadioWall ESP32 Configuration
 * 
 * Copy to config.h and adjust for your setup
 */

#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
// WiFi Settings
// =============================================================================
// WiFi credentials are now OPTIONAL — WiFiManager captive portal handles setup.
// On first boot, ESP32 creates "RadioWall" AP. Connect and configure via browser.
// Uncomment below only if you want hardcoded fallback (e.g., for mqtt_client).
// #define WIFI_SSID "your_wifi_ssid"
// #define WIFI_PASSWORD "your_wifi_password"

// WiFi connection timeout (milliseconds)
#define WIFI_CONNECT_TIMEOUT 10000

// =============================================================================
// MQTT Settings
// =============================================================================
#define MQTT_SERVER "192.168.1.100"  // Your server IP
#define MQTT_PORT 1883
// #define MQTT_USER ""              // Uncomment if authentication required
// #define MQTT_PASSWORD ""

// MQTT Topics
#define MQTT_TOPIC_TOUCH "radiowall/touch"
#define MQTT_TOPIC_NOWPLAYING "radiowall/nowplaying"
#define MQTT_TOPIC_STATUS "radiowall/status"
#define MQTT_TOPIC_COMMAND "radiowall/command"

// Client ID (should be unique)
#define MQTT_CLIENT_ID "radiowall-esp32"

// =============================================================================
// Touch Panel Settings
// =============================================================================
// Touch coordinate range (adjust based on your panel)
#define TOUCH_MIN_X 0
#define TOUCH_MAX_X 1024
#define TOUCH_MIN_Y 0
#define TOUCH_MAX_Y 600

// Debounce time (milliseconds) - prevent multiple triggers
#define TOUCH_DEBOUNCE_MS 500

// =============================================================================
// Touch Mode Settings
// =============================================================================
// Use built-in touchscreen (1) or external USB touch panel (0)
#define USE_BUILTIN_TOUCH 1

// Touch mapping mode (only used for legacy stretch/fit mapping)
#define TOUCH_MAP_MODE_FIT 1
#define TOUCH_MAP_MODE_STRETCH 0
#define TOUCH_MAP_MODE TOUCH_MAP_MODE_STRETCH  // Zone-based mapping ignores this

// Draw touch feedback marker on the map
#define TOUCH_VISUAL_FEEDBACK 1

// =============================================================================
// WiiM / LinkPlay Settings (ESP32-only mode)
// =============================================================================
// WiiM device IP address (find in WiiM app or router)
#define WIIM_IP "192.168.1.50"

// =============================================================================
// Display Settings
// =============================================================================
// Display timeout - dim after this many seconds of inactivity
#define DISPLAY_TIMEOUT_SECONDS 60

// Brightness levels (0-255)
#define DISPLAY_BRIGHTNESS_NORMAL 200
#define DISPLAY_BRIGHTNESS_DIM 50

// =============================================================================
// Pin Definitions (T-Display-S3-Long specific)
// =============================================================================
// These are typically fixed for the board, don't change unless you know what you're doing

// Display pins (directly connected on T-Display-S3-Long)
// Defined in TFT_eSPI User_Setup

// Battery voltage ADC pin
#define BAT_ADC_PIN 4

// Power control
#define LCD_POWER_PIN 15  // Set HIGH to enable display power

#endif // CONFIG_H
