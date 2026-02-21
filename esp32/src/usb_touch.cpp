/**
 * USB Host HID touch panel driver for RadioWall Prototype 2.
 *
 * Reads touch coordinates from a USB capacitive touch panel connected
 * via USB-C OTG adapter. The panel reports as a standard HID digitizer.
 *
 * Report format (52 bytes):
 *   Byte 0:    0x15 (report ID)
 *   Byte 1:    0x40 = finger down, 0x00 = finger up (bit 6)
 *   Byte 2-3:  X coordinate (uint16 little-endian, 0-1023)
 *   Byte 4-5:  Y coordinate (uint16 little-endian, 0-599)
 *   Byte 6-50: Additional touch points (zeros for single touch)
 *   Byte 51:   Contact count (0x01)
 *
 * The touch panel sits over the physical map, so coordinates map directly
 * to the 1024x600 equirectangular world projection.
 */

#include "usb_touch.h"
#include "udp_log.h"
#include "ui_state.h"
#include "config.h"
#include <Wire.h>

// ESP-IDF USB Host (bundled with Arduino-ESP32)
#include "usb/usb_host.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// Touch panel coordinate range
#define TOUCH_PANEL_MAX_X 1023
#define TOUCH_PANEL_MAX_Y 599

// Debounce: ignore rapid re-triggers
#define USB_TOUCH_DEBOUNCE_MS 300

// Double-tap detection
#define DOUBLE_TAP_WINDOW_MS 400
#define SINGLE_TAP_DEFER_MS 500

// ---------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------
static MapTouchCallback _map_cb = nullptr;
static UIButtonCallback _ui_btn_cb = nullptr;
static MenuTouchCallback _menu_cb = nullptr;
static SwipeCallback _swipe_cb = nullptr;
static VolumeChangeCallback _vol_cb = nullptr;
static MapDoubleTapCallback _dbl_tap_cb = nullptr;
static UIState* _ui_state = nullptr;

// ---------------------------------------------------------------
// PMU (SY6970) — enable OTG 5V output
// ---------------------------------------------------------------
static bool pmu_write(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(0x6A);
    Wire.write(reg);
    Wire.write(val);
    return (Wire.endTransmission() == 0);
}

static uint8_t pmu_read(uint8_t reg) {
    Wire.beginTransmission(0x6A);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)0x6A, (uint8_t)1);
    return Wire.available() ? Wire.read() : 0;
}

static void pmu_enable_otg() {
    Wire.begin(15, 10);  // SDA=15, SCL=10

    // Disable watchdog (REG07 bits [5:4] = 00) — prevents 40s auto-reset
    uint8_t reg07 = pmu_read(0x07);
    reg07 &= ~0x30;
    pmu_write(0x07, reg07);

    // REG03: OTG_CONFIG=1 (bit5), CHG_CONFIG=0 (bit4)
    uint8_t reg03 = pmu_read(0x03);
    reg03 = (reg03 & ~0x30) | 0x20;
    pmu_write(0x03, reg03);

    // REG0A: Boost voltage 5.15V
    uint8_t reg0a = pmu_read(0x0A);
    reg0a = (reg0a & 0x0F) | 0x80;
    pmu_write(0x0A, reg0a);

    // REG00: Disable ILIM, max input current
    pmu_write(0x00, 0x3F);

    uint8_t verify = pmu_read(0x03);
    if (verify & 0x20) {
        udp_log("[USBTouch] PMU: OTG enabled (5V out)");
    } else {
        udp_log("[USBTouch] PMU: OTG bit NOT set!");
    }
}

// ---------------------------------------------------------------
// USB Host state
// ---------------------------------------------------------------
static usb_host_client_handle_t _client = nullptr;
static volatile uint8_t _new_dev_addr = 0;
static volatile bool _dev_gone = false;
static usb_device_handle_t _dev_hdl = nullptr;
static usb_transfer_t *_xfer = nullptr;
static bool _reading_reports = false;
static bool _usb_initialized = false;

// ---------------------------------------------------------------
// Touch state
// ---------------------------------------------------------------
static bool _finger_down = false;
static uint16_t _down_x = 0, _down_y = 0;
static unsigned long _down_time = 0;
static unsigned long _last_fire_ms = 0;

// Double-tap detection
static bool _pending_tap = false;
static uint16_t _pending_x = 0, _pending_y = 0;
static unsigned long _pending_time = 0;

// ---------------------------------------------------------------
// USB Host callbacks
// ---------------------------------------------------------------

static void client_event_cb(const usb_host_client_event_msg_t *event_msg, void *arg) {
    switch (event_msg->event) {
        case USB_HOST_CLIENT_EVENT_NEW_DEV:
            _new_dev_addr = event_msg->new_dev.address;
            break;
        case USB_HOST_CLIENT_EVENT_DEV_GONE:
            _dev_gone = true;
            break;
    }
}

static void usb_lib_task(void *arg) {
    while (true) {
        uint32_t event_flags;
        usb_host_lib_handle_events(portMAX_DELAY, &event_flags);
        if (event_flags & USB_HOST_LIB_EVENT_FLAGS_NO_CLIENTS) break;
    }
    vTaskDelete(NULL);
}

// ---------------------------------------------------------------
// Touch event processing
// ---------------------------------------------------------------

static void fire_tap(uint16_t x, uint16_t y) {
    unsigned long now = millis();
    if (now - _last_fire_ms < USB_TOUCH_DEBOUNCE_MS) return;
    _last_fire_ms = now;

    udp_logf("[USBTouch] Tap at (%d, %d)", x, y);

    // The USB touch panel covers the physical map.
    // Coordinates are already in ~1024x600 equirectangular space.
    if (_map_cb) {
        _map_cb(x, y);
    }
}

static void fire_double_tap(uint16_t x, uint16_t y) {
    udp_logf("[USBTouch] Double-tap at (%d, %d)", x, y);
    _last_fire_ms = millis();

    // TODO: Double-tap zoom not meaningful on physical map (no display zoom).
    // Reserved for future use. For now, treat as regular tap.
    if (_map_cb) {
        _map_cb(x, y);
    }
}

static void process_touch(bool down, uint16_t x, uint16_t y) {
    if (down && !_finger_down) {
        // Finger just touched
        _finger_down = true;
        _down_x = x;
        _down_y = y;
        _down_time = millis();
    } else if (!down && _finger_down) {
        // Finger lifted — fire tap
        _finger_down = false;

        // Check for double-tap
        unsigned long now = millis();
        if (_pending_tap && (now - _pending_time < DOUBLE_TAP_WINDOW_MS)) {
            // Double-tap detected
            _pending_tap = false;
            fire_double_tap(_down_x, _down_y);
        } else {
            // Defer single tap (wait to see if double-tap follows)
            _pending_tap = true;
            _pending_x = _down_x;
            _pending_y = _down_y;
            _pending_time = now;
        }
    }
}

// ---------------------------------------------------------------
// HID report callback (called from USB interrupt context)
// ---------------------------------------------------------------

static void xfer_callback(usb_transfer_t *transfer) {
    if (transfer->status == USB_TRANSFER_STATUS_COMPLETED && transfer->actual_num_bytes >= 6) {
        uint8_t *d = transfer->data_buffer;

        // Parse report: byte 1 bit 6 = touch state, bytes 2-5 = X,Y (LE uint16)
        bool down = (d[1] & 0x40) != 0;
        uint16_t x = d[2] | (d[3] << 8);
        uint16_t y = d[4] | (d[5] << 8);

        process_touch(down, x, y);
    }

    // Resubmit to keep reading
    if (_reading_reports && _dev_hdl) {
        usb_host_transfer_submit(transfer);
    }
}

// ---------------------------------------------------------------
// USB device enumeration
// ---------------------------------------------------------------

static bool setup_hid_endpoint(const usb_config_desc_t *config_desc) {
    int offset = 0;
    const uint8_t *p = (const uint8_t *)config_desc;
    int total_len = config_desc->wTotalLength;
    bool in_hid = false;

    while (offset < total_len) {
        uint8_t desc_len = p[offset];
        uint8_t desc_type = p[offset + 1];
        if (desc_len == 0) break;

        if (desc_type == USB_B_DESCRIPTOR_TYPE_INTERFACE) {
            uint8_t iface_class = p[offset + 5];
            uint8_t iface_num = p[offset + 2];
            in_hid = (iface_class == 0x03);

            if (in_hid) {
                esp_err_t err = usb_host_interface_claim(_client, _dev_hdl, iface_num, 0);
                if (err != ESP_OK) {
                    udp_logf("[USBTouch] Claim iface #%d failed: %d", iface_num, err);
                    in_hid = false;
                } else {
                    udp_logf("[USBTouch] HID iface #%d claimed", iface_num);
                }
            }
        }

        if (desc_type == USB_B_DESCRIPTOR_TYPE_ENDPOINT && in_hid) {
            uint8_t ep_addr = p[offset + 2];
            uint8_t ep_attr = p[offset + 3];
            uint16_t ep_mps = p[offset + 4] | (p[offset + 5] << 8);

            if ((ep_addr & 0x80) && (ep_attr & 0x03) == 0x03) {
                udp_logf("[USBTouch] INT IN EP 0x%02X mps=%d", ep_addr, ep_mps);

                usb_host_transfer_alloc(ep_mps + 1, 0, &_xfer);
                if (_xfer) {
                    _xfer->device_handle = _dev_hdl;
                    _xfer->bEndpointAddress = ep_addr;
                    _xfer->callback = xfer_callback;
                    _xfer->context = NULL;
                    _xfer->num_bytes = ep_mps;
                    return true;
                }
            }
        }

        offset += desc_len;
    }
    return false;
}

static void handle_new_device() {
    uint8_t addr = _new_dev_addr;
    _new_dev_addr = 0;
    if (addr == 0) return;

    esp_err_t err = usb_host_device_open(_client, addr, &_dev_hdl);
    if (err != ESP_OK) {
        udp_logf("[USBTouch] Open device failed: %d", err);
        return;
    }

    const usb_device_desc_t *dev_desc;
    usb_host_get_device_descriptor(_dev_hdl, &dev_desc);
    udp_logf("[USBTouch] Device VID:%04X PID:%04X", dev_desc->idVendor, dev_desc->idProduct);

    const usb_config_desc_t *config_desc;
    err = usb_host_get_active_config_descriptor(_dev_hdl, &config_desc);
    if (err != ESP_OK) {
        udp_logf("[USBTouch] Config desc failed: %d", err);
        return;
    }

    if (setup_hid_endpoint(config_desc)) {
        _reading_reports = true;
        err = usb_host_transfer_submit(_xfer);
        if (err != ESP_OK) {
            udp_logf("[USBTouch] Submit failed: %d", err);
            _reading_reports = false;
        } else {
            udp_log("[USBTouch] Touch panel active!");
        }
    } else {
        udp_log("[USBTouch] No HID endpoint found");
    }
}

static void handle_device_gone() {
    _dev_gone = false;
    _reading_reports = false;
    _finger_down = false;
    udp_log("[USBTouch] Device disconnected");

    if (_xfer) {
        usb_host_transfer_free(_xfer);
        _xfer = nullptr;
    }
    if (_dev_hdl) {
        usb_host_device_close(_client, _dev_hdl);
        _dev_hdl = nullptr;
    }
}

// ---------------------------------------------------------------
// Public API
// ---------------------------------------------------------------

void usb_touch_init() {
    udp_log("[USBTouch] Initializing USB Host...");

    // Enable PMU OTG for 5V USB power
    pmu_enable_otg();

    // Install USB Host library
    usb_host_config_t host_config = {
        .skip_phy_setup = false,
        .intr_flags = ESP_INTR_FLAG_LEVEL1,
    };
    esp_err_t err = usb_host_install(&host_config);
    if (err != ESP_OK) {
        udp_logf("[USBTouch] USB Host install failed: 0x%X", err);
        return;
    }

    // Daemon task on core 0
    xTaskCreatePinnedToCore(usb_lib_task, "usb_lib", 4096, NULL, 2, NULL, 0);

    // Register client
    usb_host_client_config_t client_config = {
        .is_synchronous = false,
        .max_num_event_msg = 5,
        .async = {
            .client_event_callback = client_event_cb,
            .callback_arg = NULL,
        }
    };
    err = usb_host_client_register(&client_config, &_client);
    if (err != ESP_OK) {
        udp_logf("[USBTouch] Client register failed: 0x%X", err);
        return;
    }

    _usb_initialized = true;
    udp_log("[USBTouch] Ready — plug in touch panel");
}

void usb_touch_task() {
    if (!_usb_initialized) return;

    // Process USB events
    if (_client) {
        usb_host_client_handle_events(_client, 10);
    }

    // Handle device connect/disconnect
    if (_new_dev_addr != 0) handle_new_device();
    if (_dev_gone) handle_device_gone();

    // Fire deferred single tap (if no double-tap followed)
    if (_pending_tap && (millis() - _pending_time >= SINGLE_TAP_DEFER_MS)) {
        _pending_tap = false;
        fire_tap(_pending_x, _pending_y);
    }
}

// Callback setters
void usb_touch_set_map_callback(MapTouchCallback cb) { _map_cb = cb; }
void usb_touch_set_ui_button_callback(UIButtonCallback cb) { _ui_btn_cb = cb; }
void usb_touch_set_menu_callback(MenuTouchCallback cb) { _menu_cb = cb; }
void usb_touch_set_swipe_callback(SwipeCallback cb) { _swipe_cb = cb; }
void usb_touch_set_volume_change_callback(VolumeChangeCallback cb) { _vol_cb = cb; }
void usb_touch_set_map_double_tap_callback(MapDoubleTapCallback cb) { _dbl_tap_cb = cb; }
void usb_touch_set_ui_state(UIState* state) { _ui_state = state; }
