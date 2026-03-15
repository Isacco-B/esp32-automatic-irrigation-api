import gc
import time

import machine

from utils.utils import connect_to_wifi

BOOT_DELAY = 2
WIFI_TIMEOUT = 120
ENABLE_WEBREPL = False


def show_boot_info() -> None:
    print("\n" + "=" * 50)
    print("ESP32 Irrigation Controller - Booting...")
    print("=" * 50)
    gc.collect()
    print(f"Free memory: {gc.mem_free()} bytes")
    print(f"Used memory: {gc.mem_alloc()} bytes")
    print(f"CPU Frequency: {machine.freq() / 1000000:.0f} MHz")
    print("=" * 50 + "\n")


def boot_sequence() -> None:
    print(f"Waiting {BOOT_DELAY} seconds for system stability...")
    time.sleep(BOOT_DELAY)

    print("\n[1/1] Connecting to WiFi...")
    wifi_connected = connect_to_wifi(timeout=WIFI_TIMEOUT)
    if wifi_connected:
        print("WiFi connected successfully")
    else:
        print("WiFi connection failed — main program will retry")

    gc.collect()
    print(f"\nFree memory after boot: {gc.mem_free()} bytes")
    print("\nBoot sequence completed. Starting main program...\n")
    print("=" * 50 + "\n")


def setup_webrepl() -> None:
    try:
        import webrepl

        webrepl.start()
        print("WebREPL started")
    except ImportError:
        print("WebREPL not available")
    except Exception as e:
        print(f"WebREPL error: {e}")


try:
    show_boot_info()

    if ENABLE_WEBREPL:
        setup_webrepl()

    boot_sequence()

except Exception as e:
    print(f"\nBoot error: {e}")
    print("Continuing to main program anyway...")
    time.sleep(2)
