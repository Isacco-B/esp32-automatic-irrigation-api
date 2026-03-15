import time

from machine import Pin

MANUAL_MAX_DURATION = 3600

zone_pins = {
    "zone_1": Pin(16, Pin.OUT),
    "zone_2": Pin(17, Pin.OUT),
    "zone_3": Pin(18, Pin.OUT),
    "zone_4": Pin(25, Pin.OUT),
    "zone_5": Pin(26, Pin.OUT),
    "zone_6": Pin(27, Pin.OUT),
    "zone_7": Pin(32, Pin.OUT),
    "zone_8": Pin(33, Pin.OUT),
}

VALID_ZONES = set(zone_pins.keys())

main_valve = Pin(19, Pin.OUT)

float_switch_1 = Pin(23, Pin.IN)
float_switch_2 = Pin(34, Pin.IN)
float_switch_3 = Pin(35, Pin.IN)

active_zone = None
manual_override = False
zone_end_time = None       # time.time() of scheduled end for the active zone
active_program_id = None

# Auto program interrupted by a manual zone: {"id": int, "zone": str, "window_end": float}
paused_program = None

# Program explicitly paused by the user via command: {"id": int, "zone": str, "window_end": float}
user_paused_program = None


def _activate_pins(zone_name: str) -> None:
    main_valve.on()
    time.sleep_ms(200)
    zone_pins[zone_name].on()


def _deactivate_pins() -> None:
    for pin in zone_pins.values():
        pin.off()
    time.sleep_ms(200)
    main_valve.off()


def activate_zone(
    zone_name: str, duration: int, is_manual: bool = False, program_id: int = None
) -> None:
    global active_zone, manual_override, zone_end_time, active_program_id
    _activate_pins(zone_name)
    active_zone = zone_name
    manual_override = is_manual
    zone_end_time = time.time() + duration
    active_program_id = program_id


def deactivate_active_zone() -> dict:
    """Deactivates the current zone and returns its previous state."""
    global active_zone, manual_override, zone_end_time, active_program_id
    prev = {
        "zone": active_zone,
        "was_manual": manual_override,
        "program_id": active_program_id,
    }
    _deactivate_pins()
    active_zone = None
    manual_override = False
    zone_end_time = None
    active_program_id = None
    return prev


def deactivate_all_zones() -> None:
    """Emergency stop: deactivates all pins and resets all state."""
    global active_zone, manual_override, zone_end_time, active_program_id, paused_program, user_paused_program
    _deactivate_pins()
    active_zone = None
    manual_override = False
    zone_end_time = None
    active_program_id = None
    paused_program = None
    user_paused_program = None


def is_zone_timeout() -> bool:
    if active_zone is None or zone_end_time is None:
        return False
    return time.time() >= zone_end_time


def get_remaining_seconds() -> int:
    if active_zone is None or zone_end_time is None:
        return 0
    return max(0, int(zone_end_time - time.time()))


def get_float_switches() -> dict:
    return {
        "float_switch_1": float_switch_1.value(),
        "float_switch_2": float_switch_2.value(),
        "float_switch_3": float_switch_3.value(),
    }
