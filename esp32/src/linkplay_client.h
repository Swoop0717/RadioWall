/**
 * LinkPlay HTTP API Client for WiiM devices
 *
 * Simple HTTP-based control for WiiM speakers using the LinkPlay API.
 * No UPnP/DLNA complexity - just HTTP GET requests.
 */

#ifndef LINKPLAY_CLIENT_H
#define LINKPLAY_CLIENT_H

#include <Arduino.h>

// Initialize LinkPlay client with WiiM IP address
void linkplay_init(const char* wiim_ip);

// Set/change WiiM IP address at runtime
void linkplay_set_ip(const char* wiim_ip);

// Play a stream URL
bool linkplay_play(const char* stream_url);

// Stop playback
bool linkplay_stop();

// Pause playback
bool linkplay_pause();

// Resume playback
bool linkplay_resume();

// Set volume (0-100)
bool linkplay_set_volume(int volume);

// Get current volume (returns 0-100, or -1 on failure)
int linkplay_get_volume();

// Set sleep timer (0 = cancel, >0 = minutes)
bool linkplay_set_sleep_timer(int minutes);

// Get current status (returns JSON string)
String linkplay_get_status();

// Process serial commands for testing (W:ip, P:url, S, V:vol, ?)
void linkplay_serial_task();

// Send a command to an arbitrary device IP (for multiroom slave commands)
String linkplay_request_to(const char* ip, const char* command, int retries = 2);

// Multiroom: join a slave to the current master
bool linkplay_multiroom_join(const char* slave_ip);

// Multiroom: kick a slave from the current master
bool linkplay_multiroom_kick(const char* slave_ip);

// Multiroom: ungroup all slaves from the current master
bool linkplay_multiroom_ungroup();

#endif // LINKPLAY_CLIENT_H
