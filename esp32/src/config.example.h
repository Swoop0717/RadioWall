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
#define WIFI_SSID "your_wifi_ssid"
#define WIFI_PASSWORD "your_wifi_password"

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
