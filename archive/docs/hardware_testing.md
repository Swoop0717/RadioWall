# Hardware Testing Guide

This guide helps you verify each piece of hardware works before integrating them.

## Phase 0: Test Everything Individually

### 1. Test Touch Panel on Desktop PC

**What you need:**
- Touch panel (9" capacitive)
- USB controller board
- FPC ribbon cable
- USB cable

**Steps:**

1. Connect the FPC ribbon cable from the touch panel to the USB controller board
   - Make sure the blue side of the FPC faces up (usually)
   - Gently push the cable into the ZIF connector and lock it

2. Connect the USB cable to the controller board

3. Plug into your PC's USB port

4. **Windows:** 
   - Open Device Manager → Look for "HID-compliant touch screen" under Human Interface Devices
   - Touch the panel → your mouse cursor should move!
   
5. **Linux:**
   ```bash
   # Check if device is recognized
   lsusb
   # Look for something like "Goodix" or "Touch"
   
   # List input devices
   cat /proc/bus/input/devices
   
   # Test touch events (install evtest if needed)
   sudo apt install evtest
   sudo evtest
   # Select the touch device, then touch the panel to see events
   ```

6. **Note the coordinate range** - you'll need this for calibration
   ```
   Example output:
   Event: type 3 (EV_ABS), code 0 (ABS_X), value 512
   Event: type 3 (EV_ABS), code 1 (ABS_Y), value 300
   ```

**Expected result:** Touch on panel = cursor/coordinate response ✓

---

### 2. Test Touch Panel on Raspberry Pi 3B+

**What you need:**
- Raspberry Pi 3B+ with Raspberry Pi OS
- Touch panel assembled (from step 1)
- Power supply for Pi
- MicroSD card with OS

**Steps:**

1. Flash Raspberry Pi OS Lite (no desktop needed):
   ```bash
   # Use Raspberry Pi Imager: https://www.raspberrypi.com/software/
   # Choose: Raspberry Pi OS Lite (64-bit)
   # Enable SSH in settings
   ```

2. Boot the Pi and SSH in

3. Connect the touch panel via USB

4. Test touch input:
   ```bash
   # Install evtest
   sudo apt update
   sudo apt install evtest
   
   # List input devices
   sudo evtest
   # Select touch device
   # Touch the panel - you should see events!
   ```

5. (Optional) Test with Python:
   ```bash
   sudo apt install python3-evdev
   ```
   
   ```python
   # test_touch.py
   from evdev import InputDevice, categorize, ecodes
   
   # Find your device (check /dev/input/)
   dev = InputDevice('/dev/input/event0')  # Adjust number
   
   print(f"Device: {dev.name}")
   print("Touch the panel...")
   
   for event in dev.read_loop():
       if event.type == ecodes.EV_ABS:
           if event.code == ecodes.ABS_X:
               print(f"X: {event.value}")
           elif event.code == ecodes.ABS_Y:
               print(f"Y: {event.value}")
   ```

**Expected result:** Touch events visible on Pi ✓

---

### 3. Test Raspberry Pi Audio → WiiM Amp

**What you need:**
- Raspberry Pi on same network as WiiM
- WiiM Amp Pro connected to WiFi

**Steps:**

1. Find your WiiM on the network:
   ```bash
   # Install UPnP tools
   sudo apt install gupnp-tools
   
   # Scan for devices
   gssdp-discover -i eth0 --timeout=5
   # or
   gssdp-discover -i wlan0 --timeout=5
   
   # Look for WiiM in the output
   ```

2. Test with a simple stream:
   ```bash
   # Install gmrender (UPnP renderer test)
   sudo apt install gmediarender
   
   # Or test with Python
   pip install async-upnp-client
   ```

   ```python
   # test_upnp.py
   import asyncio
   from async_upnp_client.search import async_search
   
   async def find_devices():
       devices = await async_search(timeout=5)
       for device in devices:
           print(f"Found: {device}")
   
   asyncio.run(find_devices())
   ```

**Expected result:** WiiM discovered on network ✓

---

### 4. Test T-Display-S3-Long (Basic)

**What you need:**
- T-Display-S3-Long
- USB-C cable (for programming)
- Arduino IDE or PlatformIO

**Steps:**

1. Install Arduino IDE and ESP32 board support:
   - Add to Board Manager URLs: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Install "esp32" boards package

2. Select board: "LilyGo T-Display-S3" (or ESP32-S3 Dev Module)

3. Flash factory test or simple example:
   ```cpp
   // test_display.cpp
   void setup() {
     Serial.begin(115200);
     Serial.println("T-Display-S3-Long Test");
     
     // Turn on display power (required for battery operation)
     pinMode(15, OUTPUT);
     digitalWrite(15, HIGH);
   }
   
   void loop() {
     Serial.println("Running...");
     delay(1000);
   }
   ```

4. Check serial monitor - should see output

**Expected result:** ESP32 boots and communicates ✓

---

### 5. Test T-Display-S3-Long USB Host Mode (Once adapters arrive)

**What you need:**
- T-Display-S3-Long
- USB-C OTG adapter
- USB-C breakout board (for power)
- Touch panel with USB controller
- 5V power supply

**Wiring:**
```
USB Touch Controller ──► USB-C OTG Adapter ──► ESP32 USB-C Port

5V Power Supply
  ├── 5V (red) ──► ESP32 5V Pin
  └── GND (black) ──► ESP32 GND Pin
```

**Steps:**

1. Connect power via 5V pin FIRST (before connecting USB)

2. Connect touch panel via OTG adapter

3. Flash USB Host test firmware:
   ```cpp
   // This is a simplified example - full implementation needed
   #include "USB.h"
   #include "USBHIDMouse.h"
   
   void setup() {
     Serial.begin(115200);
     USB.begin();
     // USB Host initialization...
   }
   
   void loop() {
     // Read HID reports from touch panel
   }
   ```

4. Touch the panel and check serial output for coordinates

**Expected result:** ESP32 reads touch coordinates via USB Host ✓

---

## Troubleshooting

### Touch panel not recognized
- Check FPC cable orientation (usually blue side up)
- Try different USB port
- Check USB cable (data cables, not charge-only)

### No touch response
- Panel might need more pressure (unlikely for capacitive)
- Check if panel is designed for finger touch (not stylus-only)

### ESP32 won't boot when powered via 5V pin
- Make sure to disable USB CDC in firmware settings
- Check polarity of power connection
- Verify 5V is regulated (not directly from LiPo!)

### WiiM not discoverable
- Check same network/VLAN
- WiiM might need firmware update
- Try WiiM app first to verify it's working

---

## Next Steps

Once all hardware is verified:
1. ✅ Touch panel works → Note coordinate range
2. ✅ Pi sees touch → Ready for server development
3. ✅ WiiM reachable → Ready for UPnP integration
4. ✅ ESP32 boots → Ready for firmware development
5. ⏳ ESP32 USB Host → Ready for final integration

Then proceed to **Phase 1: Server Application** in the main README.
