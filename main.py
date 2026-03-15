import json
import random
import time
from secrets import PASSWORD, SERVER, USER

import machine

import irrigation_controller as ctrl
from irrigation_programs import (
    check_conflict,
    create_program,
    delete_program,
    edit_program,
    get_all_programs,
    get_program_by_id,
)
from lib.umqtt import MQTTClient
from utils.messages import DEFAULT_USER, MESSAGES
from utils.timezone import now_unix, now_unix_ms
from utils.utils import (
    connect_to_wifi,
    is_wifi_connected,
    validate_program_data,
    validate_program_updates,
)

WIFI_TIMEOUT = 120
SLEEP_INTERVAL = 0.1
MQTT_RETRY_INTERVAL = 1
KEEP_ALIVE_INTERVAL = 10
NOTIFICATION_TIMEOUT = 60

STATUS_SEND_INTERVAL = 1000
ZONE_CHECK_INTERVAL = 1000
CHECK_PROGRAMS_INTERVAL = 10000

TOPICS = {
    "ZONE": b"api/irrigation/zone",
    "PROGRAM_CREATE": b"api/irrigation/program/create",
    "PROGRAM_EDIT": b"api/irrigation/program/edit",
    "PROGRAM_DELETE": b"api/irrigation/program/delete",
    "PROGRAM_LIST": b"api/irrigation/program/list",
    "PROGRAM_UPCOMING": b"api/irrigation/program/upcoming",
    "PROGRAM_CONTROL": b"api/irrigation/program/control",
    "GET_STATUS": b"api/irrigation/status",
}

NOTIFY = {
    "ZONE": b"api/notification/irrigation/zone",
    "PROGRAM": b"api/notification/irrigation/program",
    "PROGRAM_LIST": b"api/notification/irrigation/program/list",
    "PROGRAM_UPCOMING": b"api/notification/irrigation/program/upcoming",
    "PROGRAM_CONTROL": b"api/notification/irrigation/program/control",
    "STATUS": b"api/notification/irrigation/status",
}

mqtt_client = None
status_requested = False
status_end_time = 0

# Tracks when each program was last started to prevent double-triggers {program_id: time.time()}
program_last_started = {}


def send_notification(topic, message, success: bool = True) -> None:
    try:
        if isinstance(topic, str):
            topic = topic.encode()
        payload = {
            "data": message,
            "status": "success" if success else "error",
            "timestamp": now_unix_ms(),
        }
        mqtt_client.publish(topic, json.dumps(payload).encode("utf-8"))
    except Exception as e:
        print(f"Error sending notification on {topic}: {e}")


def parse_payload(msg: bytes) -> dict:
    try:
        return json.loads(msg.decode("utf-8"))
    except Exception as e:
        print(f"Error parsing payload: {e}")
        return {}


# ---------------------------------------------------------------------------
# Manual zone control
# ---------------------------------------------------------------------------


def handle_zone_command(data: dict) -> None:
    zone_name = data.get("zone")
    duration = data.get("duration")
    cmd = data.get("cmd", "toggle")
    username = data.get("user", DEFAULT_USER)

    if zone_name not in ctrl.VALID_ZONES:
        send_notification(
            NOTIFY["ZONE"], MESSAGES["zone"]["not_found"].format(zone=zone_name), False
        )
        return

    if cmd == "off":
        if ctrl.active_zone == zone_name:
            ctrl.deactivate_active_zone()
            msg = MESSAGES["zone"]["deactivated"].format(user=username, zone=zone_name)
            send_notification(NOTIFY["ZONE"], msg)
            check_and_run_programs()
        else:
            send_notification(
                NOTIFY["ZONE"], f"La zona {zone_name} non è attiva", False
            )
        return

    duration = (
        min(int(duration), ctrl.MANUAL_MAX_DURATION)
        if duration
        else ctrl.MANUAL_MAX_DURATION
    )

    if ctrl.active_zone is None:
        ctrl.activate_zone(zone_name, duration, is_manual=True)
        msg = MESSAGES["zone"]["activated"].format(
            user=username, zone=zone_name, duration=round(duration / 60, 1)
        )
        send_notification(NOTIFY["ZONE"], msg)

    elif ctrl.active_zone == zone_name:
        ctrl.deactivate_active_zone()
        msg = MESSAGES["zone"]["deactivated"].format(user=username, zone=zone_name)
        send_notification(NOTIFY["ZONE"], msg)
        check_and_run_programs()

    else:
        if not ctrl.manual_override:
            # Auto program running — pause it so it can resume after manual ends
            ctrl.paused_program = {
                "id": ctrl.active_program_id,
                "zone": ctrl.active_zone,
                "window_end": ctrl.zone_end_time,
            }

        ctrl.deactivate_active_zone()
        ctrl.activate_zone(zone_name, duration, is_manual=True)
        msg = MESSAGES["zone"]["manual_override"].format(user=username, zone=zone_name)
        send_notification(NOTIFY["ZONE"], msg)


# ---------------------------------------------------------------------------
# User-initiated pause / resume / stop of auto programs
# ---------------------------------------------------------------------------


def handle_program_control(data: dict) -> None:
    """Routes pause/resume/stop actions. Payload: {"action": "pause"|"resume"|"stop", "id": <int>, "user": "..."}"""
    action = data.get("action")
    username = data.get("user", DEFAULT_USER)

    try:
        program_id = int(data["id"])
    except (KeyError, TypeError, ValueError):
        send_notification(
            NOTIFY["PROGRAM_CONTROL"], "ID programma mancante o non valido", False
        )
        return

    if action == "pause":
        _handle_program_pause(program_id, username)
    elif action == "resume":
        _handle_program_resume(program_id, username)
    elif action == "stop":
        _handle_program_stop(program_id, username)
    else:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"], f"Azione non valida: {action}", False
        )


def _handle_program_pause(program_id: int, username: str) -> None:
    """Pauses a running auto program. Stores window_end so resume knows the original deadline."""
    if ctrl.active_program_id != program_id:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["not_running"],
            False,
        )
        return

    remaining = ctrl.get_remaining_seconds()
    window_end = ctrl.zone_end_time  # original scheduled end time
    zone = ctrl.active_zone

    ctrl.deactivate_active_zone()

    ctrl.user_paused_program = {
        "id": program_id,
        "zone": zone,
        "window_end": window_end,
    }

    program = get_program_by_id(program_id)
    name = program["name"] if program else str(program_id)
    msg = MESSAGES["program_control"]["paused"].format(
        user=username, name=name, remaining=round(remaining / 60, 1)
    )
    send_notification(NOTIFY["PROGRAM_CONTROL"], msg)


def _handle_program_resume(program_id: int, username: str) -> None:
    """Resumes a user-paused program if its time window has not expired."""
    if not ctrl.user_paused_program or ctrl.user_paused_program["id"] != program_id:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["not_paused"],
            False,
        )
        return

    if time.time() >= ctrl.user_paused_program["window_end"]:
        ctrl.user_paused_program = None
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["window_expired"],
            False,
        )
        return

    if ctrl.active_zone is not None:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["zone_busy"],
            False,
        )
        return

    paused = ctrl.user_paused_program
    ctrl.user_paused_program = None

    # Remaining time is computed from the original window, not from when it was paused
    new_remaining = int(paused["window_end"] - time.time())

    programs = get_all_programs()
    now = now_unix()
    local_t = time.localtime(now)
    current_seconds = local_t[3] * 3600 + local_t[4] * 60
    capped = _cap_to_next_program(
        new_remaining, current_seconds, paused["id"], programs
    )

    if capped <= 0:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["no_time"],
            False,
        )
        return

    ctrl.activate_zone(paused["zone"], capped, is_manual=False, program_id=paused["id"])

    program = get_program_by_id(paused["id"])
    name = program["name"] if program else str(paused["id"])
    msg = MESSAGES["program_control"]["resumed"].format(
        user=username, name=name, remaining=round(capped / 60, 1)
    )
    send_notification(NOTIFY["PROGRAM_CONTROL"], msg)


def _handle_program_stop(program_id: int, username: str) -> None:
    """Permanently stops a program regardless of its current state (running, user-paused, or auto-paused)."""
    stopped = False

    if ctrl.active_program_id == program_id:
        ctrl.deactivate_active_zone()
        stopped = True

    if ctrl.user_paused_program and ctrl.user_paused_program["id"] == program_id:
        ctrl.user_paused_program = None
        stopped = True

    if ctrl.paused_program and ctrl.paused_program["id"] == program_id:
        ctrl.paused_program = None
        stopped = True

    program = get_program_by_id(program_id)
    name = program["name"] if program else str(program_id)

    if stopped:
        msg = MESSAGES["program_control"]["stopped"].format(user=username, name=name)
        send_notification(NOTIFY["PROGRAM_CONTROL"], msg)
    else:
        send_notification(
            NOTIFY["PROGRAM_CONTROL"],
            MESSAGES["program_control"]["not_running"],
            False,
        )


def _time_str_to_seconds(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 3600 + m * 60


def _cap_to_next_program(
    duration: int, current_seconds: int, exclude_id: int, programs: list
) -> int:
    """
    Truncates 'duration' so the resumed program does not overlap the next scheduled program.
    Checks both today and tomorrow (in case the window extends past midnight).
    Returns the (possibly reduced) duration in seconds.
    """
    now = now_unix()
    local_t = time.localtime(now)
    current_weekday = local_t[6]
    next_weekday = (current_weekday + 1) % 7
    end_seconds = current_seconds + duration

    for prog in programs:
        if prog["id"] == exclude_id:
            continue
        if not prog.get("is_active", True):
            continue
        start_s = _time_str_to_seconds(prog["start_time"])
        # Check today
        if current_weekday in prog["active_days"]:
            if current_seconds < start_s < end_seconds:
                end_seconds = start_s
        # Check tomorrow if the window extends past midnight
        if end_seconds > 86400 and next_weekday in prog["active_days"]:
            start_s_tomorrow = start_s + 86400
            if current_seconds < start_s_tomorrow < end_seconds:
                end_seconds = start_s_tomorrow

    return end_seconds - current_seconds


def _try_resume_paused_program(programs: list = None) -> None:
    """
    Resumes an auto-paused program (interrupted by a manual zone).
    Truncates its duration if another program is scheduled before its natural end.
    Discards it silently if the original time window has already expired.
    """
    if not ctrl.paused_program:
        return

    paused = ctrl.paused_program
    ctrl.paused_program = None

    actual_remaining = int(paused["window_end"] - time.time())
    if actual_remaining <= 0:
        print(f"Paused program {paused['id']} window expired, discarding")
        return

    if programs is None:
        programs = get_all_programs()

    now = now_unix()
    local_t = time.localtime(now)
    current_seconds = local_t[3] * 3600 + local_t[4] * 60

    capped = _cap_to_next_program(
        actual_remaining, current_seconds, paused["id"], programs
    )

    if capped <= 0:
        print(
            f"Paused program {paused['id']} has no room before next scheduled program, discarding"
        )
        return

    ctrl.activate_zone(paused["zone"], capped, is_manual=False, program_id=paused["id"])
    msg = MESSAGES["zone"]["auto_resumed"].format(
        zone=paused["zone"], duration=round(capped / 60, 1)
    )
    send_notification(NOTIFY["ZONE"], msg)


def _start_auto_program(prog: dict, duration: int = None) -> None:
    """Starts an auto program. 'duration' supports late-start (partial window)."""
    actual_duration = duration if duration is not None else prog["duration"]
    program_last_started[prog["id"]] = time.time()
    ctrl.activate_zone(
        prog["zone"], actual_duration, is_manual=False, program_id=prog["id"]
    )
    msg = MESSAGES["zone"]["auto_activated"].format(
        zone=prog["zone"], duration=round(actual_duration / 60, 1)
    )
    send_notification(NOTIFY["ZONE"], msg)


# ---------------------------------------------------------------------------
# Zone timeout
# ---------------------------------------------------------------------------


def check_zone_timeout() -> None:
    if not ctrl.is_zone_timeout():
        return

    zone_name = ctrl.active_zone
    was_manual = ctrl.manual_override
    ctrl.deactivate_active_zone()

    if was_manual:
        msg = MESSAGES["zone"]["timeout_deactivated"].format(zone=zone_name)
    else:
        msg = MESSAGES["zone"]["auto_deactivated"].format(zone=zone_name)

    send_notification(NOTIFY["ZONE"], msg)

    # Trigger immediately without waiting for the next 10s tick
    check_and_run_programs()


# ---------------------------------------------------------------------------
# Auto program scheduler
# ---------------------------------------------------------------------------


def check_and_run_programs() -> None:
    """
    Checks whether an auto program should start now.

    Priority:
    1. A scheduled program whose time window is active (start <= now < start+duration):
       starts for the remaining window time (late-start), discarding any auto-paused program.
    2. An auto-paused program (no scheduled program currently due):
       resumes for its remaining window time, capped at the next scheduled program start.

    The auto-paused and user-paused programs are excluded from the scheduler loop
    to avoid being picked up as a fresh start.
    """
    if ctrl.manual_override:
        return

    if ctrl.active_zone is not None:
        return

    programs = get_all_programs()
    now = now_unix()
    local_t = time.localtime(now)
    current_weekday = local_t[6]  # 0=Mon, 6=Sun
    current_seconds = local_t[3] * 3600 + local_t[4] * 60

    paused_id = ctrl.paused_program["id"] if ctrl.paused_program else None
    user_paused_id = (
        ctrl.user_paused_program["id"] if ctrl.user_paused_program else None
    )

    # Discard expired user-paused program
    if (
        ctrl.user_paused_program
        and time.time() >= ctrl.user_paused_program["window_end"]
    ):
        print(f"User-paused program {user_paused_id} window expired, discarding")
        ctrl.user_paused_program = None
        user_paused_id = None

    # Find a scheduled program whose time window is currently active
    due_program = None
    due_remaining = None
    for prog in programs:
        if not prog.get("is_active", True):
            continue
        # Skip auto-paused program — handled by _try_resume_paused_program
        if prog["id"] == paused_id:
            continue
        # Skip user-paused program — only the user can resume it explicitly
        if prog["id"] == user_paused_id:
            continue
        if time.time() - program_last_started.get(prog["id"], 0) < 70:
            continue
        if current_weekday not in prog["active_days"]:
            continue
        start_s = _time_str_to_seconds(prog["start_time"])
        end_s = start_s + prog["duration"]
        if start_s <= current_seconds < end_s:
            due_program = prog
            due_remaining = end_s - current_seconds  # late start: remaining window time
            break

    if due_program:
        # Scheduled program takes priority — discard any auto-paused program
        if ctrl.paused_program:
            print(
                f"Paused program {ctrl.paused_program['id']} discarded: "
                f"'{due_program['name']}' is due"
            )
            ctrl.paused_program = None
        _start_auto_program(due_program, due_remaining)

    elif ctrl.paused_program:
        _try_resume_paused_program(programs)


# ---------------------------------------------------------------------------
# Program CRUD
# ---------------------------------------------------------------------------


def handle_program_create(data: dict) -> None:
    program_data = data.get("program")

    is_valid, error = validate_program_data(program_data)
    if not is_valid:
        send_notification(NOTIFY["PROGRAM"], error, False)
        return

    has_conflict, conflict_name = check_conflict(program_data)
    if has_conflict:
        msg = MESSAGES["program"]["conflict"].format(name=conflict_name)
        send_notification(NOTIFY["PROGRAM"], msg, False)
        return

    try:
        program = create_program(program_data)
        msg = MESSAGES["program"]["created"].format(name=program["name"])
        send_notification(NOTIFY["PROGRAM"], msg)
        _send_program_list()
    except Exception as e:
        print(f"Error creating program: {e}")
        send_notification(NOTIFY["PROGRAM"], MESSAGES["program"]["error_create"], False)


def handle_program_edit(data: dict) -> None:
    updates = data.get("program", {})

    try:
        program_id = int(data["id"])
    except (KeyError, TypeError, ValueError):
        send_notification(
            NOTIFY["PROGRAM"], "ID programma mancante o non valido", False
        )
        return

    existing = get_program_by_id(program_id)
    if not existing:
        send_notification(NOTIFY["PROGRAM"], MESSAGES["program"]["not_found"], False)
        return

    is_valid, error = validate_program_updates(updates)
    if not is_valid:
        send_notification(NOTIFY["PROGRAM"], error, False)
        return

    # Merge for conflict check against the full updated program
    merged = {}
    merged.update(existing)
    merged.update(updates)

    has_conflict, conflict_name = check_conflict(merged, exclude_id=program_id)
    if has_conflict:
        msg = MESSAGES["program"]["conflict"].format(name=conflict_name)
        send_notification(NOTIFY["PROGRAM"], msg, False)
        return

    try:
        program = edit_program(program_id, updates)
        msg = MESSAGES["program"]["edited"].format(name=program["name"])
        send_notification(NOTIFY["PROGRAM"], msg)

        # If disabled, stop it wherever it currently is
        if not program.get("is_active", True):
            was_active = ctrl.active_program_id == program_id
            if was_active:
                ctrl.deactivate_active_zone()
                send_notification(
                    NOTIFY["ZONE"],
                    f"Programma '{program['name']}' disabilitato: zona disattivata",
                )
            if ctrl.paused_program and ctrl.paused_program.get("id") == program_id:
                ctrl.paused_program = None
            if (
                ctrl.user_paused_program
                and ctrl.user_paused_program.get("id") == program_id
            ):
                ctrl.user_paused_program = None
            if was_active:
                check_and_run_programs()

        _send_program_list()
    except Exception as e:
        print(f"Error editing program: {e}")
        send_notification(NOTIFY["PROGRAM"], MESSAGES["program"]["error_edit"], False)


def handle_program_delete(data: dict) -> None:
    try:
        program_id = int(data["id"])
    except (KeyError, TypeError, ValueError):
        send_notification(
            NOTIFY["PROGRAM"], "ID programma mancante o non valido", False
        )
        return

    # Remove from all active states before deleting
    was_active = ctrl.active_program_id == program_id
    if was_active:
        ctrl.deactivate_active_zone()
        send_notification(
            NOTIFY["ZONE"], f"Programma {program_id} eliminato: zona disattivata"
        )
    if ctrl.paused_program and ctrl.paused_program.get("id") == program_id:
        ctrl.paused_program = None
    if ctrl.user_paused_program and ctrl.user_paused_program.get("id") == program_id:
        ctrl.user_paused_program = None
    program_last_started.pop(program_id, None)

    success = delete_program(program_id)
    if success:
        send_notification(NOTIFY["PROGRAM"], MESSAGES["program"]["deleted"])
        _send_program_list()
        if was_active:
            check_and_run_programs()
    else:
        send_notification(NOTIFY["PROGRAM"], MESSAGES["program"]["not_found"], False)


# ---------------------------------------------------------------------------
# Status and program list
# ---------------------------------------------------------------------------


def send_irrigation_status() -> None:
    try:
        user_paused = ctrl.user_paused_program
        payload = {
            "active_zone": ctrl.active_zone,
            "manual_override": ctrl.manual_override,
            "zone_remaining_seconds": ctrl.get_remaining_seconds(),
            "paused_program": (
                {
                    "id": ctrl.paused_program["id"],
                    "zone": ctrl.paused_program["zone"],
                    "window_remaining_seconds": max(
                        0, int(ctrl.paused_program["window_end"] - time.time())
                    ),
                }
                if ctrl.paused_program
                else None
            ),
            "user_paused_program": (
                {
                    "id": user_paused["id"],
                    "zone": user_paused["zone"],
                    "window_remaining_seconds": max(
                        0, int(user_paused["window_end"] - time.time())
                    ),
                }
                if user_paused
                else None
            ),
            "float_switches": ctrl.get_float_switches(),
            "timestamp": now_unix_ms(),
        }
        mqtt_client.publish(NOTIFY["STATUS"], json.dumps(payload).encode("utf-8"))
    except Exception as e:
        print(f"Error sending irrigation status: {e}")


def _send_program_list() -> None:
    try:
        programs = get_all_programs()
        payload = {
            "programs": programs,
            "total": len(programs),
            "timestamp": now_unix_ms(),
        }
        mqtt_client.publish(NOTIFY["PROGRAM_LIST"], json.dumps(payload).encode("utf-8"))
    except Exception as e:
        print(f"Error sending program list: {e}")


def _send_upcoming_programs() -> None:
    try:
        upcoming = _compute_upcoming_programs()
        payload = {
            "upcoming": upcoming,
            "timestamp": now_unix_ms(),
        }
        mqtt_client.publish(
            NOTIFY["PROGRAM_UPCOMING"], json.dumps(payload).encode("utf-8")
        )
    except Exception as e:
        print(f"Error sending upcoming programs: {e}")


def _compute_upcoming_programs(n: int = 10) -> list:
    """Returns the next N activations across all active programs, sorted by start time."""
    programs = get_all_programs()
    now = now_unix()
    local_t = time.localtime(now)
    today_weekday = local_t[6]
    today_seconds = local_t[3] * 3600 + local_t[4] * 60 + local_t[5]

    upcoming = []

    for prog in programs:
        if not prog.get("is_active", True):
            continue

        start_h, start_m = map(int, prog["start_time"].split(":"))
        start_seconds = start_h * 3600 + start_m * 60

        for day_offset in range(8):
            check_weekday = (today_weekday + day_offset) % 7

            if check_weekday not in prog["active_days"]:
                continue

            # Today but start time already passed — skip
            if day_offset == 0 and start_seconds <= today_seconds:
                continue

            next_unix = now - today_seconds + day_offset * 86400 + start_seconds
            upcoming.append(
                {
                    "id": prog["id"],
                    "name": prog["name"],
                    "zone": prog["zone"],
                    "start": next_unix,
                    "duration": prog["duration"],
                }
            )
            break

    upcoming.sort(key=lambda x: x["start"])
    return upcoming[:n]


# ---------------------------------------------------------------------------
# MQTT connection
# ---------------------------------------------------------------------------


def handle_message(topic: bytes, msg: bytes) -> None:
    global status_requested, status_end_time
    print(f"Received - Topic: {topic}, Message: {msg}")

    data = parse_payload(msg)

    if topic == TOPICS["ZONE"]:
        handle_zone_command(data)

    elif topic == TOPICS["PROGRAM_CREATE"]:
        handle_program_create(data)

    elif topic == TOPICS["PROGRAM_EDIT"]:
        handle_program_edit(data)

    elif topic == TOPICS["PROGRAM_DELETE"]:
        handle_program_delete(data)

    elif topic == TOPICS["PROGRAM_LIST"]:
        _send_program_list()

    elif topic == TOPICS["PROGRAM_UPCOMING"]:
        _send_upcoming_programs()

    elif topic == TOPICS["PROGRAM_CONTROL"]:
        handle_program_control(data)

    elif topic == TOPICS["GET_STATUS"]:
        status_requested = True
        status_end_time = time.time() + NOTIFICATION_TIMEOUT


def connect_to_mqtt() -> bool:
    global mqtt_client

    if mqtt_client:
        try:
            mqtt_client.disconnect()
        except Exception:
            pass
        mqtt_client = None

    while not is_wifi_connected():
        print("WiFi not connected, attempting connection...")
        connect_to_wifi(timeout=WIFI_TIMEOUT)
        time.sleep(1)

    try:
        client = MQTTClient(
            client_id=str(random.randint(100000, 999999)),
            user=USER,
            password=PASSWORD,
            server=SERVER,
        )
        client.set_callback(handle_message)
        client.connect()
        time.sleep_ms(200)

        for topic_name, topic in TOPICS.items():
            client.subscribe(topic)
            print(f"Subscribed to {topic_name}")

        print(f"Connected to MQTT broker at {SERVER}")
        mqtt_client = client
        return True
    except Exception as e:
        print(f"Failed to connect to MQTT: {e}")
        return False


def keep_connection_active() -> None:
    try:
        mqtt_client.publish(b"api/ping", b"ping")
    except Exception as e:
        print(f"Error sending ping: {e}")
        raise


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def cleanup_pins() -> None:
    try:
        ctrl.deactivate_all_zones()
    except Exception as e:
        print(f"Error cleaning up pins: {e}")


def main() -> None:
    global status_requested, mqtt_client

    cleanup_pins()

    last_zone_check = time.ticks_ms()
    last_program_check = time.ticks_ms()
    last_send_status = time.ticks_ms()
    last_keep_alive = time.time()

    while True:
        try:
            if not connect_to_mqtt():
                print("Failed to connect to MQTT, retrying...")
                time.sleep(MQTT_RETRY_INTERVAL)
                continue

            while True:
                current_time = time.time()
                ms_now = time.ticks_ms()

                mqtt_client.check_msg()

                if time.ticks_diff(ms_now, last_zone_check) >= ZONE_CHECK_INTERVAL:
                    check_zone_timeout()
                    last_zone_check = ms_now

                if (
                    time.ticks_diff(ms_now, last_program_check)
                    >= CHECK_PROGRAMS_INTERVAL
                ):
                    check_and_run_programs()
                    last_program_check = ms_now

                if status_requested:
                    if (
                        time.ticks_diff(ms_now, last_send_status)
                        >= STATUS_SEND_INTERVAL
                    ):
                        send_irrigation_status()
                        last_send_status = ms_now
                    if current_time >= status_end_time:
                        status_requested = False
                        print("Status request timeout")

                if current_time - last_keep_alive >= KEEP_ALIVE_INTERVAL:
                    keep_connection_active()
                    last_keep_alive = current_time

                time.sleep(SLEEP_INTERVAL)

        except KeyboardInterrupt:
            print("Program interrupted by user")
            break

        except Exception as e:
            print(f"MQTT communication error: {e}")

        finally:
            try:
                if mqtt_client:
                    mqtt_client.disconnect()
                    mqtt_client = None
            except Exception as e:
                print(f"Error disconnecting client: {e}")

            time.sleep(MQTT_RETRY_INTERVAL)

    cleanup_pins()
    print("Program terminated")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {e}")
        cleanup_pins()
        machine.reset()
