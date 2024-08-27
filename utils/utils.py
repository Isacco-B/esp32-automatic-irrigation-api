from machine import Pin
import network
import uasyncio as asyncio
import time
import re
from secrets import WLAN_SSID, WLAN_PASSWORD

# Constants
WIFI_RETRY_INTERVAL = 2

# PinOut
led_wifi = Pin(12, Pin.OUT)


# Wifi
def connect_to_wifi():
    """Connect to the specified WiFi network."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        led_wifi.on()
        print('wifi connection...')
        wlan.connect(WLAN_SSID, WLAN_PASSWORD)
        while not wlan.isconnected():
            led_wifi.on()
            time.sleep(WIFI_RETRY_INTERVAL)
            print('Retrying WiFi connection...')
    led_wifi.off()
    print('Connected to:', WLAN_SSID)
    print('Connection details:', wlan.ifconfig())
    print("------------------------------------")

def is_wifi_connected():
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected()


# Data Validation
def validate_program_data(data):
    valid_actions = {"create", "edit", "delete"}
    if "action" not in data or data["action"] not in valid_actions:
        return False, "Invalid action."

    if data["action"] == "delete":
        if "id" not in data:
            return False, "Missing id."
        return True, "Validation successful."

    if "program" not in data:
        return False, "Missing program data."

    program = data["program"]

    if data["action"] == "edit":
        if "id" not in data:
            return False, "Missing id."

        if "zone" in program and program["zone"] not in {
            f"zone_{i}" for i in range(1, 9)
        }:
            return False, "Invalid or missing zone."

        if "active_day" in program and not re.match(
            r"^[0-6](-[0-6])*$", program["active_day"]
        ):
            return False, "Invalid active_day format."

        if "start_time" in program and not re.match(
            r"^(?:[01]\d|2[0-3]):[0-5]\d$", program["start_time"]
        ):
            return False, "Invalid start_time format."

        if (
            "duration" in program
            and not isinstance(program["duration"], int)
            and not (0 <= program["duration"] <= 3600)
        ):
            return False, "Invalid or missing duration."

        if "is_active" in program and not isinstance(program["is_active"], bool):
            return False, "Invalid or missing is_active."

        if "is_running" in program and not isinstance(program["is_running"], bool):
            return False, "Invalid or missing is_running."

        return True, "Validation successful."

    if "name" not in program:
        return False, "Invalid or missing name."

    if "zone" not in program or program["zone"] not in {
        f"zone_{i}" for i in range(1, 9)
    }:
        return False, "Invalid or missing zone."

    if "active_day" not in program or not re.match(
        r"^[0-6](-[0-6])*$", program["active_day"]
    ):
        return False, "Invalid active_day format."

    if "start_time" not in program or not re.match(
        r"^(?:[01]\d|2[0-3]):[0-5]\d$", program["start_time"]
    ):
        return False, "Invalid start_time format."

    if (
        "duration" not in program
        or not isinstance(program["duration"], int)
        or not (0 <= program["duration"] <= 3600)
    ):
        return False, "Invalid or missing duration."

    if "is_active" not in program or not isinstance(program["is_active"], bool):
        return False, "Invalid or missing is_active."

    if "is_running" not in program or not isinstance(program["is_running"], bool):
        return False, "Invalid or missing is_running."

    return True, "Validation successful."
