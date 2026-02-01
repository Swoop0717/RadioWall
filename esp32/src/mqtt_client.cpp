/**
 * MQTT client for RadioWall ESP32.
 *
 * Handles WiFi connection, MQTT pub/sub for touch events and now-playing updates.
 */

#include "mqtt_client.h"
#include "config.h"

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

static WiFiClient _wifi_client;
static PubSubClient _mqtt(MQTT_SERVER, MQTT_PORT, _wifi_client);

static NowPlayingCallback _nowplaying_cb = nullptr;
static StatusCallback _status_cb = nullptr;

static unsigned long _last_reconnect_attempt = 0;
static const unsigned long RECONNECT_INTERVAL_MS = 5000;

// ------------------------------------------------------------------
// WiFi
// ------------------------------------------------------------------

static void wifi_connect() {
    if (WiFi.status() == WL_CONNECTED) return;

    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_CONNECT_TIMEOUT) {
            Serial.println("\n[WiFi] Connection timeout!");
            return;
        }
        delay(500);
        Serial.print(".");
    }

    Serial.printf("\n[WiFi] Connected, IP: %s\n", WiFi.localIP().toString().c_str());
}

// ------------------------------------------------------------------
// MQTT callback
// ------------------------------------------------------------------

static void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    // Parse JSON payload
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.printf("[MQTT] JSON parse error: %s\n", err.c_str());
        return;
    }

    if (strcmp(topic, MQTT_TOPIC_NOWPLAYING) == 0) {
        const char* station = doc["station"] | "Unknown";
        const char* location = doc["location"] | "Unknown";
        const char* country = doc["country"] | "";
        Serial.printf("[MQTT] Now playing: %s (%s, %s)\n", station, location, country);
        if (_nowplaying_cb) {
            _nowplaying_cb(station, location, country);
        }
    } else if (strcmp(topic, MQTT_TOPIC_STATUS) == 0) {
        const char* state = doc["state"] | "unknown";
        const char* msg = doc["msg"] | "";
        Serial.printf("[MQTT] Status: %s %s\n", state, msg);
        if (_status_cb) {
            _status_cb(state, msg);
        }
    }
}

// ------------------------------------------------------------------
// MQTT connect/reconnect
// ------------------------------------------------------------------

static bool mqtt_reconnect() {
    Serial.println("[MQTT] Connecting...");

#if defined(MQTT_USER) && defined(MQTT_PASSWORD)
    bool ok = _mqtt.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD);
#else
    bool ok = _mqtt.connect(MQTT_CLIENT_ID);
#endif

    if (ok) {
        Serial.println("[MQTT] Connected");
        _mqtt.subscribe(MQTT_TOPIC_NOWPLAYING);
        _mqtt.subscribe(MQTT_TOPIC_STATUS);
    } else {
        Serial.printf("[MQTT] Failed, rc=%d\n", _mqtt.state());
    }
    return ok;
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

void mqtt_init() {
    wifi_connect();
    _mqtt.setCallback(mqtt_callback);
    _mqtt.setBufferSize(1024);
    mqtt_reconnect();
}

void mqtt_loop() {
    // Ensure WiFi is connected
    if (WiFi.status() != WL_CONNECTED) {
        wifi_connect();
    }

    // Ensure MQTT is connected
    if (!_mqtt.connected()) {
        unsigned long now = millis();
        if (now - _last_reconnect_attempt > RECONNECT_INTERVAL_MS) {
            _last_reconnect_attempt = now;
            mqtt_reconnect();
        }
        return;
    }

    _mqtt.loop();
}

bool mqtt_is_connected() {
    return _mqtt.connected();
}

void mqtt_publish_touch(int x, int y) {
    if (!_mqtt.connected()) return;

    StaticJsonDocument<128> doc;
    doc["x"] = x;
    doc["y"] = y;
    doc["ts"] = millis();

    char buf[128];
    serializeJson(doc, buf, sizeof(buf));
    _mqtt.publish(MQTT_TOPIC_TOUCH, buf);
    Serial.printf("[MQTT] Published touch: (%d, %d)\n", x, y);
}

void mqtt_publish_command(const char* cmd) {
    if (!_mqtt.connected()) return;

    StaticJsonDocument<64> doc;
    doc["cmd"] = cmd;

    char buf[64];
    serializeJson(doc, buf, sizeof(buf));
    _mqtt.publish(MQTT_TOPIC_COMMAND, buf);
    Serial.printf("[MQTT] Published command: %s\n", cmd);
}

void mqtt_set_nowplaying_callback(NowPlayingCallback cb) {
    _nowplaying_cb = cb;
}

void mqtt_set_status_callback(StatusCallback cb) {
    _status_cb = cb;
}
