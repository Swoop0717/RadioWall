#ifndef UDP_LOG_H
#define UDP_LOG_H

#include <Arduino.h>

// Initialize WiFi UDP logger (call after WiFi is connected)
// Broadcasts log messages on the specified UDP port
void udp_log_init(uint16_t port = 9999);

// Printf-style logging over UDP broadcast
void udp_logf(const char* fmt, ...);

// Simple string logging over UDP broadcast
void udp_log(const char* msg);

// Check if UDP logging is available
bool udp_log_ready();

#endif // UDP_LOG_H
