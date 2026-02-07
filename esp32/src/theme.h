/**
 * UI Theme for RadioWall.
 *
 * Centralized color palette, font includes, menu icons, and layout constants.
 * Include this instead of defining per-file COLOR_* constants.
 */

#ifndef THEME_H
#define THEME_H

#include <Arduino.h>
#include "gfxfont.h"

// =====================================================================
// Fonts (Adafruit GFXfont format)
// =====================================================================
// Usage:
//   gfx->setFont(&FreeSansBold10pt7b);   // custom font (baseline cursor)
//   gfx->setFont(NULL);                   // revert to default 5x7
//
// IMPORTANT: GFXfont setCursor sets the BASELINE, not top-left.
//   FreeSansBold10pt7b ascent = 14px, yAdvance = 24px
//   FreeSerifBoldItalic12pt7b ascent = 17px, yAdvance = 28px

#include "FreeSansBold10pt7b.h"
#include "FreeSerifBoldItalic12pt7b.h"

// Font metric helpers
#define FONT_SANS_ASCENT   14
#define FONT_SANS_HEIGHT   24
#define FONT_SERIF_ASCENT  17
#define FONT_SERIF_HEIGHT  28

// =====================================================================
// Color Palette (RGB565)
// =====================================================================

// --- Surface colors (layered depth) ---
#define TH_BG           0x0000  // Pure black (AMOLED efficient)
#define TH_CARD         0x18E3  // Dark gray card background
#define TH_CARD_HI      0x2945  // Card highlight on tap

// --- Text colors ---
#define TH_TEXT         0xFFFF  // Primary text (white)
#define TH_TEXT_SEC     0xB5B6  // Secondary text (light gray)
#define TH_TEXT_DIM     0x7BCF  // Dimmed text / placeholders

// --- Accent colors ---
#define TH_ACCENT       0x07FF  // Primary accent (cyan)
#define TH_ACCENT_MUTE  0x0228  // Dark teal (subtle highlight)
#define TH_PLAYING      0x07E0  // Playing state (green)
#define TH_WARNING      0xFDA0  // Orange / yellow action
#define TH_DANGER       0xF800  // Red (delete, clear, stop)

// --- Structural ---
#define TH_DIVIDER      0x3186  // Subtle dividers
#define TH_BTN          0x2124  // Button surface
#define TH_BTN_BORDER   0x4228  // Button border (optional)

// =====================================================================
// Layout Constants
// =====================================================================

#define TH_CORNER_R     6       // Rounded corner radius
#define TH_CARD_MARGIN  4       // Horizontal margin for cards
#define TH_CARD_W       172     // Card width (180 - 2*margin)
#define TH_DISPLAY_W    180     // Display width

// =====================================================================
// Menu Icons (16x16 monochrome bitmaps, PROGMEM)
// =====================================================================
// Drawn with: gfx->drawBitmap(x, y, icon, 16, 16, color)

// Volume: speaker with sound waves
static const uint8_t ICON_VOLUME[] PROGMEM = {
    0x00, 0x00, 0x00, 0x80, 0x01, 0x80, 0x03, 0x90,
    0x07, 0xA8, 0x7F, 0xA4, 0x7F, 0xA2, 0x7F, 0xA2,
    0x7F, 0xA2, 0x7F, 0xA2, 0x7F, 0xA4, 0x07, 0xA8,
    0x03, 0x90, 0x01, 0x80, 0x00, 0x80, 0x00, 0x00
};

// Pause/Resume: play triangle + pause bars
static const uint8_t ICON_PLAY_PAUSE[] PROGMEM = {
    0x00, 0x00, 0x0C, 0x00, 0x0E, 0x00, 0x0F, 0x00,
    0x0F, 0x80, 0x0F, 0xC0, 0x0F, 0xE0, 0x0F, 0xF0,
    0x0F, 0xF0, 0x0F, 0xE0, 0x0F, 0xC0, 0x0F, 0x80,
    0x0F, 0x00, 0x0E, 0x00, 0x0C, 0x00, 0x00, 0x00
};

// Favorites: heart
static const uint8_t ICON_HEART[] PROGMEM = {
    0x00, 0x00, 0x00, 0x00, 0x1C, 0x70, 0x3E, 0xF8,
    0x7F, 0xFC, 0x7F, 0xFC, 0xFF, 0xFE, 0xFF, 0xFE,
    0xFF, 0xFE, 0x7F, 0xFC, 0x3F, 0xF8, 0x1F, 0xF0,
    0x0F, 0xE0, 0x07, 0xC0, 0x03, 0x80, 0x00, 0x00
};

// History: clock face
static const uint8_t ICON_CLOCK[] PROGMEM = {
    0x00, 0x00, 0x07, 0xC0, 0x1F, 0xF0, 0x38, 0x38,
    0x31, 0x18, 0x61, 0x0C, 0x61, 0x0C, 0x61, 0x0C,
    0x61, 0xFC, 0x61, 0xFC, 0x60, 0x0C, 0x30, 0x18,
    0x38, 0x38, 0x1F, 0xF0, 0x07, 0xC0, 0x00, 0x00
};

// Sleep Timer: crescent moon
static const uint8_t ICON_MOON[] PROGMEM = {
    0x00, 0x00, 0x03, 0xC0, 0x0F, 0x80, 0x1F, 0x00,
    0x3E, 0x00, 0x3C, 0x00, 0x7C, 0x00, 0x7C, 0x00,
    0x7C, 0x00, 0x7C, 0x00, 0x3C, 0x00, 0x3E, 0x00,
    0x1F, 0x00, 0x0F, 0x80, 0x03, 0xC0, 0x00, 0x00
};

// Settings: gear
static const uint8_t ICON_GEAR[] PROGMEM = {
    0x00, 0x00, 0x03, 0x80, 0x03, 0x80, 0x1F, 0xF0,
    0x3F, 0xF8, 0x38, 0x38, 0x78, 0x3C, 0x70, 0x1C,
    0x70, 0x1C, 0x78, 0x3C, 0x38, 0x38, 0x3F, 0xF8,
    0x1F, 0xF0, 0x03, 0x80, 0x03, 0x80, 0x00, 0x00
};

// Icon array indexed by MenuItemId (0-5)
static const uint8_t* const MENU_ICONS[] PROGMEM = {
    ICON_VOLUME, ICON_PLAY_PAUSE, ICON_HEART,
    ICON_CLOCK, ICON_MOON, ICON_GEAR
};

#endif // THEME_H
