import time
import struct
import os

try:
    import smbus  # type: ignore
    HAS_SMBUS = True
except ImportError:
    HAS_SMBUS = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

import platform

IS_LINUX = platform.system() == "Linux"
IS_RPI = IS_LINUX and HAS_SMBUS  # Only True if running on Linux with smbus available
# python-for-android always sets ANDROID_ARGUMENT in the environment.
IS_ANDROID = "ANDROID_ARGUMENT" in os.environ

CW2015_ADDRESS = 0x62
CW2015_REG_VCELL = 0x02
CW2015_REG_SOC = 0x04
CW2015_REG_MODE = 0x0A
BMI160_ADDRESS = 0x69

# UPS-Lite V1.3 hat: MAX17040 fuel gauge. VCELL is a 12-bit reading at
# 1.25mV/LSB (byte-swapped, top 12 bits); SOC is byte-swapped word / 256.
# External-power presence is signalled on GPIO4 (high = powered/charging).
MAX17040_ADDRESS = 0x36
MAX17040_REG_VCELL = 0x02
MAX17040_REG_SOC = 0x04
MAX17040_REG_MODE = 0x06
UPS_LITE_POWER_GPIO = 4

class I2CUtils:
    def __init__(self):
        i2c_device_exists = os.path.exists("/dev/i2c-1")
        self.bus = smbus.SMBus(1) if IS_RPI and i2c_device_exists else None
        self.battery_addr = CW2015_ADDRESS
        self.battery_chip = None  # "max17040" (UPS-Lite) or "cw2015"
        self.bmi160_addr = BMI160_ADDRESS
        self.valid = IS_RPI and i2c_device_exists
        self.charging = False
        self.battery_percent = 0.0

        self._last_voltage = None
        self._charging_counter = 0  # For debounce
        self._gpio_ready = False

        if IS_RPI and self.bus is not None:
            self._detect_battery_chip()
            self._init_power_gpio()
            self.init_bmi160()

    def _detect_battery_chip(self):
        """Probe for a fuel gauge: UPS-Lite (MAX17040 @0x36) first, then CW2015."""
        try:
            self.bus.read_word_data(MAX17040_ADDRESS, MAX17040_REG_SOC)
            self.battery_chip = "max17040"
            self.battery_addr = MAX17040_ADDRESS
            print("[I2C] Battery gauge: MAX17040 (UPS-Lite)")
            return
        except Exception:
            pass
        try:
            self.bus.write_word_data(CW2015_ADDRESS, CW2015_REG_MODE, 0x30)
            time.sleep(1)  # Allow chip to calibrate
            self.battery_chip = "cw2015"
            self.battery_addr = CW2015_ADDRESS
            print("[I2C] Battery gauge: CW2015")
        except Exception as e:
            print(f"[I2C] No battery gauge detected: {e}")

    def _init_power_gpio(self):
        """UPS-Lite external-power sense pin (GPIO4 high = on external power)."""
        if self.battery_chip != "max17040":
            return
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(UPS_LITE_POWER_GPIO, GPIO.IN)
            self._gpio = GPIO
            self._gpio_ready = True
        except Exception as e:
            print(f"[I2C] UPS-Lite power GPIO unavailable: {e}")

    def quick_start(self):
        """Kept for compatibility: fuel-gauge init now runs in _detect_battery_chip."""
        return

    def read_voltage(self):
        """ Read battery voltage and update charging status """
        if not IS_RPI or self.battery_chip is None:
            return None
        try:
            vcell = self.bus.read_word_data(self.battery_addr, MAX17040_REG_VCELL)
            swapped = ((vcell & 0xFF) << 8) | (vcell >> 8)
            if self.battery_chip == "max17040":
                # 12-bit reading, 1.25mV per LSB
                voltage = (swapped >> 4) * 1.25 / 1000
            else:  # cw2015
                voltage = swapped * 0.305 / 1000

            # Voltage-trend charging detection (fallback when no power GPIO)
            if self._last_voltage is not None:
                if voltage > self._last_voltage + 0.002:  # Small threshold to avoid noise
                    self._charging_counter += 1
                else:
                    self._charging_counter = max(0, self._charging_counter - 1)
                # Require several consecutive increases to confirm charging
                if not self._gpio_ready:
                    self.charging = self._charging_counter >= 3
            self._last_voltage = voltage

            return voltage
        except Exception as e:
            print(f"Voltage read error: {e}")
            return None

    def read_capacity(self):
        """ Read battery capacity (%) on RPI """
        if not IS_RPI or self.battery_chip is None:
            return None
        try:
            soc = self.bus.read_word_data(self.battery_addr, MAX17040_REG_SOC)
            swapped = ((soc & 0xFF) << 8) | (soc >> 8)
            capacity = swapped / 256
            return max(0.0, min(100.0, capacity))
        except Exception as e:
            print(f"Capacity read error: {e}")
            return None

    def _read_ups_lite_charging(self):
        """UPS-Lite: GPIO4 high while on external power. None if unavailable."""
        if not self._gpio_ready:
            return None
        try:
            return bool(self._gpio.input(UPS_LITE_POWER_GPIO))
        except Exception:
            return None

    def _read_android_battery(self):
        """Battery level on Android. Returns (percent, charging) or None.

        Prefers plyer; falls back to reading the sticky ACTION_BATTERY_CHANGED
        intent directly through pyjnius when plyer is missing or broken.
        """
        try:
            from plyer import battery  # type: ignore
            status = battery.status
            percent = status.get("percentage")
            if percent is not None:
                return float(percent), bool(status.get("isCharging"))
        except Exception:
            pass

        try:
            from jnius import autoclass  # type: ignore
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            IntentFilter = autoclass("android.content.IntentFilter")
            BatteryManager = autoclass("android.os.BatteryManager")
            activity = PythonActivity.mActivity
            intent_filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
            # Sticky broadcast: registerReceiver(None, filter) returns it
            battery_status = activity.registerReceiver(None, intent_filter)
            if battery_status is None:
                return None
            level = battery_status.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            scale = battery_status.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            status = battery_status.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
            if level < 0 or scale <= 0:
                return None
            charging = status in (BatteryManager.BATTERY_STATUS_CHARGING,
                                  BatteryManager.BATTERY_STATUS_FULL)
            return level * 100.0 / scale, charging
        except Exception:
            return None

    def get_battery_info(self):
        if IS_ANDROID:
            info = self._read_android_battery()
            if info is not None:
                self.battery_percent, self.charging = info
            else:
                # Unreadable on this device -- report a full, non-charging
                # battery so the clock widget shows a neutral icon instead
                # of a permanently empty one.
                self.battery_percent = 100.0
                self.charging = False
            return self.battery_percent, self.charging
        if HAS_PSUTIL:
            battery_stats = psutil.sensors_battery()
            if battery_stats == None:
                self.battery_percent = 0.0
                self.charging = True
            elif battery_stats.power_plugged == True:
                self.battery_percent = battery_stats.percent
                self.charging = True
            else:
                self.battery_percent = battery_stats.percent
                self.charging = False
        elif IS_RPI:
            capacity = self.read_capacity()
            self.battery_percent = capacity if capacity is not None else 0.0
            self.read_voltage()  # keeps the voltage-trend charging fallback fed
            gpio_charging = self._read_ups_lite_charging()
            if gpio_charging is not None:
                self.charging = gpio_charging
        else:
            self.battery_percent = 0.0
            self.charging = False
        return self.battery_percent, self.charging

    def test_battery(self):
        """ Run continuous battery monitoring """
        if IS_RPI:
            self.quick_start()  # Initialize fuel gauge

        while True:
            voltage = self.read_voltage()
            capacity = self.read_capacity()

            print("++++++++++++++++++++")
            print(f"?? Voltage: {voltage:.2f}V" if voltage else "Voltage Read Error")
            print(f"?? Battery: {capacity:.1f}%" if capacity else "Capacity Read Error")
            print("++++++++++++++++++++")

            time.sleep(2)

    def init_bmi160(self):
        if not IS_RPI:
            return
        try:
            self.bus.write_byte_data(self.bmi160_addr, 0x7E, 0xB6)  # Reset sensor
            time.sleep(0.1)
            self.bus.write_byte_data(self.bmi160_addr, 0x40, 0x28)  # Set range
            self.bus.write_byte_data(self.bmi160_addr, 0x41, 0x03)  # Set bandwidth
            self.bus.write_byte_data(self.bmi160_addr, 0x7E, 0x11)  # Enable accelerometer
            time.sleep(0.1)
        except Exception:
            self.valid = False

    def read_accel(self):
        if not self.valid or not IS_RPI:
            return 0.0, 0.0, 1.0  # Default Z-axis down
        try:
            data = self.bus.read_i2c_block_data(self.bmi160_addr, 0x12, 6)
            x = struct.unpack('<h', bytes(data[0:2]))[0]
            y = struct.unpack('<h', bytes(data[2:4]))[0]
            z = struct.unpack('<h', bytes(data[4:6]))[0]
            factor = 16384.0
            return x / factor, y / factor, z / factor
        except Exception:
            return None, None, None