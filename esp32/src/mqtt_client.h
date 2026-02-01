#ifndef MQTT_CLIENT_H
#define MQTT_CLIENT_H

#include <Arduino.h>

// Callback for now-playing updates from server
typedef void (*NowPlayingCallback)(const char* station, const char* location, const char* country);

// Callback for status updates from server
typedef void (*StatusCallback)(const char* state, const char* msg);

void mqtt_init();
void mqtt_loop();
bool mqtt_is_connected();
void mqtt_publish_touch(int x, int y);
void mqtt_publish_command(const char* cmd);
void mqtt_set_nowplaying_callback(NowPlayingCallback cb);
void mqtt_set_status_callback(StatusCallback cb);

#endif // MQTT_CLIENT_H
