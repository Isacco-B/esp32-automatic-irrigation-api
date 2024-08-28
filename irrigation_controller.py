from irrigation_database import get_all_programs, edit_program
from machine import Pin
import time
import asyncio
import json

CHECK_PROGRAMS_SLEEP_INTERVAL = 10
SEND_IRRIGATION_STATUS_SLEEP_INTERVAL = 5
ERROR_RETRY_INTERVAL = 2

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

main_valve = Pin(19, Pin.OUT)

float_switch_1 = Pin(23, Pin.IN)
float_switch_2 = Pin(34, Pin.IN)
float_switch_3 = Pin(35, Pin.IN)

active_zone = None
programs = []
deactivate_zone_after_delay_task = None

def check_zone_status(zone_name):
    return zone_pins[zone_name].value()

def activate_zone(zone_name, duration=None):
    global active_zone, deactivate_zone_after_delay_task
    if duration is not None and duration > 0:
        deactivate_zone_after_delay_task = asyncio.create_task(deactivate_zone_after_delay(zone_name, duration))
    else:
        main_valve.on()
        time.sleep(0.2)
        zone_pins[zone_name].on()
        active_zone = zone_name

async def deactivate_zone_after_delay(zone_name, duration):
    activate_zone(zone_name)
    await asyncio.sleep(duration)
    deactivate_zone(zone_name)

def deactivate_zone(zone_name):
    global active_zone
    zone_pins[zone_name].off()
    time.sleep(0.2)
    main_valve.off()
    active_zone = None

def deactivate_all_zones():
    global active_zone, deactivate_zone_after_delay_task
    if deactivate_zone_after_delay_task:
        deactivate_zone_after_delay_task.cancel()
    main_valve.off()
    for zone in zone_pins.values():
        zone.off()
    active_zone = None

def toggle_zone(zone_name, duration):
    global active_zone, deactivate_zone_after_delay_task
    if deactivate_zone_after_delay_task:
        deactivate_zone_after_delay_task.cancel()
    if active_zone is None:
        activate_zone(zone_name, duration)
    elif active_zone != zone_name:
        deactivate_zone(active_zone)
        activate_zone(zone_name, duration)
    elif active_zone == zone_name:
        deactivate_zone(zone_name)

def send_updated_status():
    from irrigation_mqtt import send_notification
    global programs
    programs = get_all_programs()
    try:     
        irrigation_status = {
            "active_zone": active_zone,
            "programs": programs,
            "float_switches": {
                "float_switch_1": float_switch_1.value(),
                "float_switch_2": float_switch_2.value(),
                "float_switch_3": float_switch_3.value(),
            }
        }         
        success_message = json.dumps(irrigation_status)
        send_notification("api/notification/irrigation/status", success_message)

    except Exception as e:   
        print(e)
        error_message = json.dumps({"data": "Impossibile ottenere stato irrigazione!"})
        send_notification("api/notification/irrigation/status", error_message)

async def send_irrigation_status():
    from irrigation_mqtt import send_notification
    while True:
        try:     
            irrigation_status = {
                "active_zone": active_zone,
                "programs": programs,
                "float_switches": {
                    "float_switch_1": float_switch_1.value(),
                    "float_switch_2": float_switch_2.value(),
                    "float_switch_3": float_switch_3.value(),
                }
            }         
            success_message = json.dumps(irrigation_status)
            send_notification("api/notification/irrigation/status", success_message)
            await asyncio.sleep(SEND_IRRIGATION_STATUS_SLEEP_INTERVAL)

        except Exception as e:   
            print(e)
            error_message = json.dumps({"data": "Impossibile ottenere stato irrigazione!"})
            send_notification("api/notification/irrigation/status", error_message)
            await asyncio.sleep(ERROR_RETRY_INTERVAL)

async def check_and_run_programs():
    global programs
    while True:
        try:
            programs = get_all_programs()
            adjusted_time = time.time() + 2 * 3600
            current_date = time.localtime(adjusted_time)
            current_weekday = current_date[6]
            current_time = "{:02}:{:02}".format(current_date[3], current_date[4])
            current_hour, current_minute = current_date[3], current_date[4]
            current_seconds = current_hour * 3600 + current_minute * 60

            for program in programs:
                start_hour, start_minute = map(int, program["start_time"].split(":"))
                program_start_seconds = start_hour * 3600 + start_minute * 60
                program_end_seconds = program_start_seconds + program["duration"]

                if program["is_running"]:
                    if (int(current_seconds) >= int(program_end_seconds)) or (program["start_time"] != current_time and (program["zone"] != active_zone or active_zone is None)):
                        edit_program(program["_row"], {"is_running": False})

                if program["is_active"] and not program["is_running"]:
                    active_days = program['active_day'].split('-')
                    if str(current_weekday) in active_days and program["start_time"] == current_time:
                        if active_zone is not None:
                            deactivate_all_zones()
                        
                        activate_zone(program["zone"], program["duration"])
                        edit_program(program["_row"], {"is_running": True})
                        print(f"Attivazione zona {program['zone']} per {program['duration'] / 60} minuti.")

            await asyncio.sleep(CHECK_PROGRAMS_SLEEP_INTERVAL)
            
        except Exception as e:
            print(f"Error check_and_run_programs: {e}")
            await asyncio.sleep(ERROR_RETRY_INTERVAL)