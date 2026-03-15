import re
import time
from secrets import WLAN_PASSWORD, WLAN_SSID

import network
from machine import Pin

from utils.timezone import sync_ntp

WIFI_RETRY_INTERVAL = 1

led_wifi = Pin(12, Pin.OUT)
led_wifi.off()


def connect_to_wifi(timeout: int = 30) -> bool:
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        led_wifi.off()
        print(f"Already connected to: {WLAN_SSID}")
        print(f"Connection details: {wlan.ifconfig()}")
        return True

    led_wifi.on()
    print(f"Connecting to WiFi: {WLAN_SSID}")
    wlan.connect(WLAN_SSID, WLAN_PASSWORD)

    start_time = time.time()
    while not wlan.isconnected():
        if time.time() - start_time > timeout:
            led_wifi.on()
            print(f"WiFi connection timeout after {timeout}s")
            return False
        led_wifi.value(not led_wifi.value())
        time.sleep(WIFI_RETRY_INTERVAL)
        print(f"Connecting... ({int(time.time() - start_time)}s)")

    led_wifi.off()
    print(f"Connected to: {WLAN_SSID}")
    print(f"Connection details: {wlan.ifconfig()}")

    ntp_ok = sync_ntp()
    if not ntp_ok:
        print("Time synchronization failed")

    return True


def is_wifi_connected() -> bool:
    wlan = network.WLAN(network.STA_IF)
    connected = wlan.isconnected()
    led_wifi.off() if connected else led_wifi.on()
    return connected


def validate_program_data(data: dict) -> tuple:
    """Validate a complete program payload (create)."""
    if not isinstance(data, dict):
        return False, "Dati programma non validi"

    if not data.get("name"):
        return False, "Nome programma mancante"

    if data.get("zone") not in {f"zone_{i}" for i in range(1, 9)}:
        return False, "Zona non valida (zone_1 - zone_8)"

    active_days = data.get("active_days")
    if not isinstance(active_days, list) or not active_days:
        return False, "Giorni attivi non validi"
    if not all(isinstance(d, int) and 0 <= d <= 6 for d in active_days):
        return False, "Giorni attivi non validi (valori 0-6, 0=Lunedì)"

    start_time = data.get("start_time")
    if not start_time or not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", start_time):
        return False, "Formato orario non valido (HH:MM)"

    duration = data.get("duration")
    if not isinstance(duration, int) or duration <= 0:
        return False, "Durata non valida (intero positivo in secondi)"

    if "is_active" in data and not isinstance(data["is_active"], bool):
        return False, "Valore is_active non valido"

    return True, "OK"


def validate_program_updates(data: dict) -> tuple:
    """Validate a partial program payload (edit)."""
    if not isinstance(data, dict) or not data:
        return False, "Dati aggiornamento non validi"

    if "zone" in data and data["zone"] not in {f"zone_{i}" for i in range(1, 9)}:
        return False, "Zona non valida (zone_1 - zone_8)"

    if "active_days" in data:
        active_days = data["active_days"]
        if not isinstance(active_days, list) or not active_days:
            return False, "Giorni attivi non validi"
        if not all(isinstance(d, int) and 0 <= d <= 6 for d in active_days):
            return False, "Giorni attivi non validi (valori 0-6, 0=Lunedì)"

    if "start_time" in data:
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", data["start_time"]):
            return False, "Formato orario non valido (HH:MM)"

    if "duration" in data:
        if not isinstance(data["duration"], int) or data["duration"] <= 0:
            return False, "Durata non valida (intero positivo in secondi)"

    if "is_active" in data and not isinstance(data["is_active"], bool):
        return False, "Valore is_active non valido"

    return True, "OK"
