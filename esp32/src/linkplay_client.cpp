/**
 * LinkPlay HTTP API Client for WiiM devices
 *
 * Uses simple HTTP GET requests to control playback.
 * API documentation: https://github.com/nicholaswa/linkplay-api-spec
 */

#include "linkplay_client.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>

static String _wiim_ip = "";
static bool _initialized = false;

void linkplay_init(const char* wiim_ip) {
    if (wiim_ip && strlen(wiim_ip) > 0) {
        _wiim_ip = String(wiim_ip);
        _initialized = true;
    }
}

void linkplay_set_ip(const char* wiim_ip) {
    _wiim_ip = String(wiim_ip);
    _initialized = true;
    Serial.printf("[LinkPlay] IP: %s\n", wiim_ip);
}

static String make_request(const char* command, int retries = 2) {
    if (!_initialized || _wiim_ip.length() == 0) {
        return "";
    }

    String path = "/httpapi.asp?command=" + String(command);
    IPAddress ip;
    if (!ip.fromString(_wiim_ip)) {
        return "";
    }

    for (int attempt = 0; attempt <= retries; attempt++) {
        if (attempt > 0) delay(1000);

        WiFiClientSecure client;
        client.setInsecure();

        if (!client.connect(ip, 443)) {
            delay(100);
            continue;
        }

        String request = "GET " + path + " HTTP/1.1\r\n";
        request += "Host: " + _wiim_ip + "\r\n";
        request += "Connection: close\r\n\r\n";
        client.print(request);

        unsigned long timeout = millis() + 5000;
        while (client.connected() && !client.available()) {
            if (millis() > timeout) {
                client.stop();
                continue;
            }
            delay(10);
        }

        String response = "";
        bool headers_done = false;
        while (client.available()) {
            String line = client.readStringUntil('\n');
            if (!headers_done) {
                if (line == "\r" || line.length() == 0) headers_done = true;
            } else {
                response += line;
            }
        }
        client.stop();

        response.trim();
        if (response.length() > 0) return response;
    }

    return "";
}

bool linkplay_play(const char* stream_url) {
    // URL encode the stream URL for the setPlayerCmd parameter
    String encoded_url = stream_url;
    encoded_url.replace(":", "%3A");
    encoded_url.replace("/", "%2F");
    encoded_url.replace("?", "%3F");
    encoded_url.replace("&", "%26");
    encoded_url.replace("=", "%3D");

    String command = "setPlayerCmd:play:" + encoded_url;
    String response = make_request(command.c_str());
    return response == "OK";
}

bool linkplay_stop() {
    String response = make_request("setPlayerCmd:stop");
    return response == "OK";
}

bool linkplay_pause() {
    String response = make_request("setPlayerCmd:pause");
    return response == "OK";
}

bool linkplay_resume() {
    String response = make_request("setPlayerCmd:resume");
    return response == "OK";
}

bool linkplay_set_sleep_timer(int minutes) {
    String command = "setSleepTimer:" + String(minutes * 60);
    String response = make_request(command.c_str());
    return response == "OK";
}

int linkplay_get_volume() {
    String status = make_request("getPlayerStatus", 1);
    if (status.length() == 0) return -1;

    // Parse "vol" from JSON response: {"vol":"50",...} or {"vol":50,...}
    int idx = status.indexOf("\"vol\"");
    if (idx < 0) return -1;

    idx = status.indexOf(':', idx);
    if (idx < 0) return -1;
    idx++;

    // Skip whitespace and quotes
    while (idx < (int)status.length() && (status[idx] == ' ' || status[idx] == '"')) idx++;

    int vol = status.substring(idx).toInt();
    return constrain(vol, 0, 100);
}

bool linkplay_set_volume(int volume) {
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;

    String command = "setPlayerCmd:vol:" + String(volume);
    String response = make_request(command.c_str());
    return response == "OK";
}

String linkplay_get_status() {
    return make_request("getPlayerStatus");
}

void linkplay_serial_task() {
    // Check for LinkPlay serial commands
    // W:ip - Set WiiM IP
    // P:url - Play URL
    // S - Stop
    // V:vol - Set volume
    // ? - Get status

    if (!Serial.available()) return;

    char cmd = Serial.peek();

    // Only handle our commands
    if (cmd != 'W' && cmd != 'P' && cmd != 'S' && cmd != 'V' && cmd != '?') {
        return;
    }

    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.startsWith("W:")) {
        // Set WiiM IP
        String ip = line.substring(2);
        linkplay_set_ip(ip.c_str());
    }
    else if (line.startsWith("P:")) {
        // Play URL
        String url = line.substring(2);
        if (linkplay_play(url.c_str())) {
            Serial.println("[LinkPlay] Play command sent");
        } else {
            Serial.println("[LinkPlay] Play command failed");
        }
    }
    else if (line == "S") {
        // Stop
        if (linkplay_stop()) {
            Serial.println("[LinkPlay] Stop command sent");
        } else {
            Serial.println("[LinkPlay] Stop command failed");
        }
    }
    else if (line.startsWith("V:")) {
        // Set volume
        int vol = line.substring(2).toInt();
        if (linkplay_set_volume(vol)) {
            Serial.printf("[LinkPlay] Volume set to %d\n", vol);
        } else {
            Serial.println("[LinkPlay] Volume command failed");
        }
    }
    else if (line == "?") {
        // Get status
        String status = linkplay_get_status();
        if (status.length() > 0) {
            Serial.println("[LinkPlay] Status: " + status);
        }
    }
}
