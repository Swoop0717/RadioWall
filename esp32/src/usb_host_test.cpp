/**
 * USB Host Diagnostic Test for RadioWall
 *
 * Minimal firmware to test if an external USB touch panel works
 * with the ESP32-S3 in USB Host mode.
 *
 * Usage:
 *   1. pio run -e usb-host-test -t upload
 *   2. Unplug USB cable
 *   3. Power on via battery
 *   4. Plug touch panel via USB-C OTG adapter
 *   5. Watch the AMOLED display for results
 *
 * All output goes to the AMOLED display since the USB port
 * is occupied by the touch panel in host mode.
 */

#ifdef USB_HOST_TEST

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "config.h"
#include "pins_config.h"
#include "Arduino_GFX_Library.h"

// UDP streaming — reports sent to broadcast on this port
#define UDP_PORT 9999
static WiFiUDP _udp;
static IPAddress _broadcast;
static bool _wifi_ok = false;
static uint32_t _report_num = 0;

// Display setup (same as display.cpp)
#define LCD_CS    TFT_QSPI_CS
#define LCD_SCLK  TFT_QSPI_SCK
#define LCD_SDIO0 TFT_QSPI_D0
#define LCD_SDIO1 TFT_QSPI_D1
#define LCD_SDIO2 TFT_QSPI_D2
#define LCD_SDIO3 TFT_QSPI_D3
#define LCD_RST   TFT_QSPI_RST
#define LCD_WIDTH  180
#define LCD_HEIGHT 640

// USB Host includes (from ESP-IDF, bundled with Arduino-ESP32)
#include "usb/usb_host.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

// ---------------------------------------------------------------
// Display globals
// ---------------------------------------------------------------
static Arduino_DataBus *bus = nullptr;
static Arduino_GFX *gfx = nullptr;

static int _log_y = 10;
static const int LINE_H = 12;
static const int LOG_X = 4;

static void display_setup() {
    pinMode(TFT_BL, OUTPUT);
    ledcAttachPin(TFT_BL, 1);
    ledcSetup(1, 2000, 8);
    ledcWrite(1, 0);

    bus = new Arduino_ESP32QSPI(
        LCD_CS, LCD_SCLK, LCD_SDIO0, LCD_SDIO1, LCD_SDIO2, LCD_SDIO3);
    gfx = new Arduino_AXS15231(bus, LCD_RST, 0, false, LCD_WIDTH, LCD_HEIGHT);
    gfx->begin();
    gfx->fillScreen(BLACK);

    for (int i = 0; i <= 255; i++) {
        ledcWrite(1, i);
        delay(2);
    }
}

// Print a line on the AMOLED, auto-scroll when full
static void dlog(const char* msg, uint16_t color = WHITE) {
    if (!gfx) return;
    if (_log_y > LCD_HEIGHT - LINE_H) {
        // Scroll: clear and restart
        gfx->fillScreen(BLACK);
        _log_y = 10;
    }
    gfx->setTextSize(1);
    gfx->setTextColor(color);
    gfx->setCursor(LOG_X, _log_y);
    gfx->print(msg);
    _log_y += LINE_H;
}

static void dlogf(uint16_t color, const char* fmt, ...) {
    char buf[64];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    dlog(buf, color);
}

// ---------------------------------------------------------------
// WiFi + UDP streaming
// ---------------------------------------------------------------
static void wifi_setup() {
    dlog("WiFi connecting...", YELLOW);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 40) {
        delay(250);
        tries++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        _wifi_ok = true;
        // Calculate broadcast address from IP + subnet
        IPAddress ip = WiFi.localIP();
        IPAddress subnet = WiFi.subnetMask();
        _broadcast = IPAddress(
            ip[0] | ~subnet[0],
            ip[1] | ~subnet[1],
            ip[2] | ~subnet[2],
            ip[3] | ~subnet[3]
        );
        _udp.begin(UDP_PORT);
        dlogf(GREEN, "WiFi: %s", ip.toString().c_str());
        dlogf(GREEN, "UDP port %d", UDP_PORT);
    } else {
        dlog("WiFi: FAILED", RED);
        dlog("Display-only mode", YELLOW);
    }
}

// Send a line of text over UDP broadcast
static void udp_send(const char* msg) {
    if (!_wifi_ok) return;
    _udp.beginPacket(_broadcast, UDP_PORT);
    _udp.print(msg);
    _udp.endPacket();
}

// ---------------------------------------------------------------
// PMU (SY6970) — enable OTG for 5V output on USB-C
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
    Wire.begin(15, 10);  // SDA=15, SCL=10 (same I2C bus as touch)

    // Dump key registers before changes
    dlogf(WHITE, "REG01: 0x%02X", pmu_read(0x01));
    dlogf(WHITE, "REG03: 0x%02X", pmu_read(0x03));
    dlogf(WHITE, "REG07: 0x%02X", pmu_read(0x07));
    dlogf(WHITE, "REG0A: 0x%02X", pmu_read(0x0A));

    // 1. Disable watchdog timer (REG07 bits [5:4] = 00)
    //    Without this, SY6970 resets all registers after ~40s
    uint8_t reg07 = pmu_read(0x07);
    reg07 &= ~0x30;  // Clear WATCHDOG bits [5:4]
    pmu_write(0x07, reg07);

    // 2. REG03: Set OTG_CONFIG=1 (bit5), clear CHG_CONFIG (bit4)
    //    OTG boost and charging are mutually exclusive
    uint8_t reg03 = pmu_read(0x03);
    reg03 = (reg03 & ~0x30) | 0x20;  // Set bit5 (OTG), clear bit4 (CHG)
    pmu_write(0x03, reg03);

    // 3. REG0A: Set boost voltage to 5.15V (bits [7:4])
    //    Default is 5.126V (0x73), keep boost current limit
    uint8_t reg0a = pmu_read(0x0A);
    reg0a = (reg0a & 0x0F) | 0x80;  // BOOSTV = 5.15V
    pmu_write(0x0A, reg0a);

    // 4. REG00: Disable ILIM pin, max input current
    pmu_write(0x00, 0x3F);

    // Verify all registers after changes
    dlog("", WHITE);
    dlogf(GREEN, "REG03: 0x%02X", pmu_read(0x03));
    dlogf(GREEN, "REG07: 0x%02X", pmu_read(0x07));
    dlogf(GREEN, "REG0A: 0x%02X", pmu_read(0x0A));

    // Check if OTG bit actually stuck
    uint8_t verify = pmu_read(0x03);
    if (verify & 0x20) {
        dlog("PMU: OTG enabled (5V out)", GREEN);
    } else {
        dlog("PMU: OTG bit NOT set!", RED);
        dlog("Try powered USB hub", YELLOW);
    }
}

// ---------------------------------------------------------------
// USB Host
// ---------------------------------------------------------------

static usb_host_client_handle_t _client = nullptr;
static volatile uint8_t _new_dev_addr = 0;
static volatile bool _dev_gone = false;
static usb_device_handle_t _dev_hdl = nullptr;

// Endpoint for interrupt IN transfers (HID reports)
static usb_transfer_t *_xfer = nullptr;
static uint8_t _ep_addr = 0;
static bool _reading_reports = false;

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

// USB Host library daemon task
static void usb_lib_task(void *arg) {
    while (true) {
        uint32_t event_flags;
        usb_host_lib_handle_events(portMAX_DELAY, &event_flags);
        if (event_flags & USB_HOST_LIB_EVENT_FLAGS_NO_CLIENTS) {
            break;
        }
    }
    vTaskDelete(NULL);
}

// Transfer complete callback (called when HID report arrives)
static void xfer_callback(usb_transfer_t *transfer) {
    if (transfer->status == USB_TRANSFER_STATUS_COMPLETED && transfer->actual_num_bytes > 0) {
        int len = transfer->actual_num_bytes;
        _report_num++;

        // Build hex string
        char hex[256];
        int pos = 0;
        for (int i = 0; i < len && pos < 240; i++) {
            pos += snprintf(hex + pos, sizeof(hex) - pos, "%02X ", transfer->data_buffer[i]);
        }

        // Show abbreviated version on display
        char display_line[64];
        snprintf(display_line, sizeof(display_line), "#%lu %dB: %.48s",
                 _report_num, len, hex);
        dlog(display_line, CYAN);

        // Send full report over UDP with report number and length
        char udp_line[300];
        snprintf(udp_line, sizeof(udp_line), "#%lu len=%d: %s",
                 _report_num, len, hex);
        udp_send(udp_line);
    }

    // Resubmit transfer to keep reading
    if (_reading_reports && _dev_hdl) {
        usb_host_transfer_submit(transfer);
    }
}

// Find and claim a HID interrupt IN endpoint
static bool setup_hid_endpoint(const usb_config_desc_t *config_desc) {
    int offset = 0;
    const uint8_t *p = (const uint8_t *)config_desc;
    int total_len = config_desc->wTotalLength;

    // Walk through all descriptors looking for HID interface + interrupt IN endpoint
    bool in_hid_interface = false;

    while (offset < total_len) {
        uint8_t desc_len = p[offset];
        uint8_t desc_type = p[offset + 1];

        if (desc_len == 0) break;

        if (desc_type == USB_B_DESCRIPTOR_TYPE_INTERFACE) {
            // Interface descriptor
            uint8_t iface_class = p[offset + 5];
            uint8_t iface_num = p[offset + 2];
            in_hid_interface = (iface_class == 0x03);  // HID class

            if (in_hid_interface) {
                dlogf(YELLOW, "HID iface #%d found", iface_num);

                // Claim this interface
                esp_err_t err = usb_host_interface_claim(_client, _dev_hdl, iface_num, 0);
                if (err != ESP_OK) {
                    dlogf(RED, "Claim fail: %d", err);
                    in_hid_interface = false;
                } else {
                    dlog("Interface claimed", GREEN);
                }
            }
        }

        if (desc_type == USB_B_DESCRIPTOR_TYPE_ENDPOINT && in_hid_interface) {
            // Endpoint descriptor
            uint8_t ep_addr = p[offset + 2];
            uint8_t ep_attr = p[offset + 3];
            uint16_t ep_mps = p[offset + 4] | (p[offset + 5] << 8);

            // Check for interrupt IN endpoint
            if ((ep_addr & 0x80) && (ep_attr & 0x03) == 0x03) {
                dlogf(GREEN, "INT IN EP: 0x%02X mps=%d", ep_addr, ep_mps);
                _ep_addr = ep_addr;

                // Allocate transfer
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

    dlogf(YELLOW, "Device at addr %d", addr);

    // Open device
    esp_err_t err = usb_host_device_open(_client, addr, &_dev_hdl);
    if (err != ESP_OK) {
        dlogf(RED, "Open fail: %d", err);
        return;
    }

    // Get device descriptor
    const usb_device_desc_t *dev_desc;
    usb_host_get_device_descriptor(_dev_hdl, &dev_desc);

    dlogf(WHITE, "VID:%04X PID:%04X",
          dev_desc->idVendor, dev_desc->idProduct);
    dlogf(WHITE, "Class:%02X Sub:%02X Proto:%02X",
          dev_desc->bDeviceClass, dev_desc->bDeviceSubClass,
          dev_desc->bDeviceProtocol);
    dlogf(WHITE, "Configs:%d", dev_desc->bNumConfigurations);

    // Also send device info over UDP
    char info[128];
    snprintf(info, sizeof(info), "=== DEVICE VID:%04X PID:%04X Class:%02X Sub:%02X Proto:%02X ===",
             dev_desc->idVendor, dev_desc->idProduct,
             dev_desc->bDeviceClass, dev_desc->bDeviceSubClass,
             dev_desc->bDeviceProtocol);
    udp_send(info);

    // Get active config descriptor
    const usb_config_desc_t *config_desc;
    err = usb_host_get_active_config_descriptor(_dev_hdl, &config_desc);
    if (err != ESP_OK) {
        dlogf(RED, "Config desc fail: %d", err);
        return;
    }

    dlogf(WHITE, "Interfaces: %d", config_desc->bNumInterfaces);
    dlogf(WHITE, "Config len: %d bytes", config_desc->wTotalLength);

    // Dump full config descriptor over UDP, abbreviated on display
    dlog("--- Config Desc ---", MAGENTA);
    udp_send("--- CONFIG DESCRIPTOR ---");
    const uint8_t *raw = (const uint8_t *)config_desc;
    for (int row = 0; row < config_desc->wTotalLength; row += 16) {
        char line[128];
        int pos = snprintf(line, sizeof(line), "%03X:", row);
        for (int i = 0; i < 16 && (row + i) < config_desc->wTotalLength; i++) {
            pos += snprintf(line + pos, sizeof(line) - pos, " %02X", raw[row + i]);
        }
        udp_send(line);
        // Only show first 128 bytes on display
        if (row < 128) {
            char short_line[64];
            int sp = snprintf(short_line, sizeof(short_line), "%02X:", row);
            for (int i = 0; i < 8 && (row + i) < config_desc->wTotalLength; i++) {
                sp += snprintf(short_line + sp, sizeof(short_line) - sp, " %02X", raw[row + i]);
            }
            dlog(short_line, MAGENTA);
        }
    }
    udp_send("--- END CONFIG ---");

    // Try to find and setup HID endpoint
    dlog("", WHITE);
    dlog("Looking for HID EP...", YELLOW);

    if (setup_hid_endpoint(config_desc)) {
        dlog("Starting reports...", GREEN);
        _reading_reports = true;
        err = usb_host_transfer_submit(_xfer);
        if (err != ESP_OK) {
            dlogf(RED, "Submit fail: %d", err);
            _reading_reports = false;
        } else {
            dlog("", WHITE);
            dlog("=== TOUCH THE PANEL ===", GREEN);
            dlog("Raw HID reports below:", WHITE);
        }
    } else {
        dlog("No HID INT IN found", RED);
    }
}

static void handle_device_gone() {
    _dev_gone = false;
    _reading_reports = false;
    dlog("Device disconnected", RED);

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
// Arduino setup / loop
// ---------------------------------------------------------------

void setup() {
    // Serial won't work over USB in host mode, but init anyway
    // (it goes nowhere, but prevents crashes from Serial.print calls)
    Serial.begin(115200);
    delay(500);

    // Initialize AMOLED display
    display_setup();
    dlog("=== USB Host Test ===", CYAN);
    dlog("RadioWall Prototype 2", WHITE);
    dlog("", WHITE);

    // Connect WiFi first (for UDP streaming)
    wifi_setup();
    dlog("", WHITE);

    // Enable PMU OTG mode (5V out on USB-C)
    pmu_enable_otg();
    dlog("", WHITE);

    // Install USB Host library
    usb_host_config_t host_config = {
        .skip_phy_setup = false,
        .intr_flags = ESP_INTR_FLAG_LEVEL1,
    };
    esp_err_t err = usb_host_install(&host_config);
    if (err != ESP_OK) {
        dlogf(RED, "USB Host fail: 0x%X", err);
        dlog("Check USB_MODE flags", RED);
        return;
    }
    dlog("USB Host: installed", GREEN);

    // Start USB lib daemon task
    xTaskCreatePinnedToCore(usb_lib_task, "usb_lib", 4096, NULL, 2, NULL, 0);

    // Register USB client
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
        dlogf(RED, "Client fail: 0x%X", err);
        return;
    }
    dlog("USB Client: ready", GREEN);
    dlog("", WHITE);
    dlog("Plug in touch panel", YELLOW);
    dlog("via USB-C OTG adapter", YELLOW);
}

void loop() {
    // Process USB client events (non-blocking, 100ms timeout)
    if (_client) {
        usb_host_client_handle_events(_client, 100);
    }

    // Handle new device connection
    if (_new_dev_addr != 0) {
        handle_new_device();
    }

    // Handle device disconnection
    if (_dev_gone) {
        handle_device_gone();
    }
}

#endif // USB_HOST_TEST
