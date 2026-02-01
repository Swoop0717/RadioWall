#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>

void display_init();
void display_loop();
void display_show_nowplaying(const char* station, const char* location, const char* country);
void display_show_status(const char* status);
void display_show_connecting();
void display_wake();

#endif // DISPLAY_H
