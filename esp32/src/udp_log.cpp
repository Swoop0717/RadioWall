#include "udp_log.h"
#include <WiFi.h>
#include <WiFiUdp.h>

static WiFiUDP _udp;
static IPAddress _broadcast;
static bool _ready = false;
static uint16_t _port = 9999;

void udp_log_init(uint16_t port) {
    _port = port;

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[UDPLog] WiFi not connected, logging disabled");
        return;
    }

    IPAddress ip = WiFi.localIP();
    IPAddress subnet = WiFi.subnetMask();
    _broadcast = IPAddress(
        ip[0] | ~subnet[0],
        ip[1] | ~subnet[1],
        ip[2] | ~subnet[2],
        ip[3] | ~subnet[3]
    );
    _udp.begin(_port);
    _ready = true;

    // Also print to Serial in case it's connected
    Serial.printf("[UDPLog] Broadcasting on port %d\n", _port);
}

void udp_logf(const char* fmt, ...) {
    char buf[256];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    udp_log(buf);
}

void udp_log(const char* msg) {
    // Always try Serial (works when USB is in device mode)
    Serial.println(msg);

    // Also broadcast over UDP if available
    if (!_ready) return;
    _udp.beginPacket(_broadcast, _port);
    _udp.print(msg);
    _udp.endPacket();
}

bool udp_log_ready() {
    return _ready;
}
