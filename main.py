from lib.umqtt import MQTTClient
from lib.micropydatabase import Database
from utils.utils import connect_to_wifi, is_wifi_connected, validate_program_data
from machine import Pin
import time
import json
import asyncio
from secrets import SERVER, USER, PASSWORD

# Constants
NOTIFICATION_TIMEOUT = 60
CHECK_PROGRAMS_SLEEP_INTERVAL = 10
MQTT_CHECK_MSG_SLEEP_INTERVAL = 0.2
MQTT_RETRY_INTERVAL = 1

# PinOut
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

# Topics
TOPICS = {
    "ZONE": b"api/irrigation/zone",
    "PROGRAM": b"api/irrigation/program"
}

table_obj = {
    "name": str,
    "zone": str,
    "active_day": str,
    "start_time": str,
    "duration": int,
    "is_active": bool,
    "is_running": bool
}


class IrrigationDatabase:
    def __init__(self, db_name):
        self.db_name = db_name
        self.irrigation_db = None
        self.irrigation_table = None

    def create_db(self):
        if not Database.exist(self.db_name):
            try:
                self.irrigation_db = Database.create(self.db_name)
            except Exception as e:
                print(e)
        else:
            try:
                self.irrigation_db = Database.open(self.db_name)
            except Exception as e:
                print(e)

    def create_table(self, table_name, table_obj):
        try:
            #self.irrigation_db.create_table(table_name, table_obj)
            self.irrigation_table =  self.irrigation_db.open_table("programs")
        except Exception as e:
            print(e)


    def new_program(self, new_program):
        self.irrigation_table.insert(new_program)

    def edit_program(self, row_id, new_data):
        self.irrigation_table.update_row(row_id, new_data)

    def get_all_programs(self):
        return list(self.irrigation_table.scan())

    def get_program_by_id(self, row_id):
        return self.irrigation_table.get_row(row_id)

    def delete_program(self, row_id):
        self.irrigation_table.delete_row(row_id)


class IrrigationController:
    def __init__(self):
        self.active_zone = None
        self.__deactivate_zone_after_delay_task = None

    def check_zone_status(self, zone_name):
        return zone_pins[zone_name].value()

    def activate_zone(self, zone_name, duration=None):
        if duration is not None and duration > 0:
            self.__deactivate_zone_after_delay_task = asyncio.create_task(self.deactivate_zone_after_delay(zone_name, duration))
        else:
            main_valve.on()
            time.sleep(0.2)
            zone_pins[zone_name].on()
            self.active_zone = zone_name

    async def deactivate_zone_after_delay(self, zone_name, duration):
        self.activate_zone(zone_name)
        await asyncio.sleep(duration)
        self.deactivate_zone(zone_name)

    def deactivate_zone(self, zone_name):
        zone_pins[zone_name].off()
        time.sleep(0.2)
        main_valve.off()
        self.active_zone = None

    def deactivate_all_zones(self):
        if self.__deactivate_zone_after_delay_task:
            self.__deactivate_zone_after_delay_task.cancel()
        main_valve.off()
        for zone in zone_pins.values():
            zone.off()
        self.active_zone = None

    def toggle_zone(self, zone_name, duration):
        if self.__deactivate_zone_after_delay_task:
            self.__deactivate_zone_after_delay_task.cancel()
        if self.active_zone is None:
            self.activate_zone(zone_name, duration)
        elif self.active_zone != zone_name:
            self.deactivate_zone(self.active_zone)
            self.activate_zone(zone_name, duration)
        elif self.active_zone == zone_name:
            self.deactivate_zone(zone_name)

    async def get_irrigation_status(self, programs):

        irrigation_status = {
            "active_zone": self.active_zone,
            "programs": programs,
            "float_switches": {
                "float_switch_1": float_switch_1.value(),
                "float_switch_2": float_switch_2.value(),
                "float_switch_3": float_switch_3.value(),
            }
        }

        try:
            success_message = json.dumps(irrigation_status)
            await self.mqtt_client.send_notification("api/notification/irrigation/status", success_message)

        except Exception as e:
            print(e)
            error_message = json.dumps({"data": "Impossibile ottenere stato irrigazione!"})
            await self.mqtt_client.send_notification("api/notification/irrigation/status", error_message)

    async def check_and_run_programs(self):
        while True:

            programs = self.db.get_all_programs()
            current_date = time.localtime()
            current_weekday = current_date[6]
            current_time = "{:02}:{:02}".format(current_date[3], current_date[4])
            current_hour, current_minute = current_date[3], current_date[4]
            current_seconds = current_hour * 3600 + current_minute * 60


            for program in programs:
                print(program)
                start_hour, start_minute = map(int, program["start_time"].split(":"))
                program_start_seconds = start_hour * 3600 + start_minute * 60
                program_end_seconds = program_start_seconds + program["duration"]

                if program["is_running"]:
                    if (int(current_seconds) >= int(program_end_seconds)) or (program["start_time"] != current_time and (program["zone"] != self.active_zone or self.active_zone is None)):
                        self.db.edit_program(program["_row"], {"is_running": False})

                if program["is_active"] and not program["is_running"]:
                    active_days = program['active_day'].split('-')
                    if str(current_weekday) in active_days and program["start_time"] == current_time:
                        if self.active_zone is not None:
                            self.deactivate_all_zones()

                        self.activate_zone(program["zone"], program["duration"])
                        self.db.edit_program(program["_row"], {"is_running": True})
                        print(f"Attivazione zona {program['zone']} per {program['duration'] / 60} minuti.")

            await self.get_irrigation_status(programs)

            await asyncio.sleep(CHECK_PROGRAMS_SLEEP_INTERVAL)


class MQTTHandler:
    def __init__(self, topics, client_id, server, user, password, irrigation_controller):
        self.__client_id = client_id
        self.__server = server
        self.__user = user
        self.__password = password
        self.client = None
        self.irrigation_controller = irrigation_controller
        self.topics = topics

    def connect_to_mqtt(self):
        while not is_wifi_connected():
            connect_to_wifi()

        while True:
            try:
                self.client = MQTTClient(client_id=self.__client_id, server=self.__server, user=self.__user, password=self.__password)
                self.client.set_callback(self.sub_cb)
                self.client.connect()
                time.sleep(2)
                for topic in TOPICS.values():
                    self.client.subscribe(topic)
                print(f"Connected to {SERVER}")
                return
            except OSError as e:
                print(f"Connection failed: {e}. Retrying in {MQTT_RETRY_INTERVAL} seconds...")
                time.sleep(MQTT_RETRY_INTERVAL)

    def sub_cb(self, topic, msg):
        asyncio.create_task(self.handle_message(topic, msg))
        
    async def send_notification(self,topic, message):
            if self.client is not None:
                self.client.publish(topic, message)

    async def handle_message(self, topic, msg):
        print((topic, msg))
        try:
            if topic == TOPICS["ZONE"]:
                data = json.loads(msg.decode('utf-8'))
                zone_name = data.get("zone")
                duration = data.get("time")
                if zone_name in zone_pins:
                    self.irrigation_controller.toggle_zone(zone_name, duration)
                else:
                    print("Invalid Zone Name")

            elif topic == TOPICS["PROGRAM"]:
                data = json.loads(msg.decode('utf-8'))
                is_valid, message = validate_program_data(data)
                if not is_valid:
                    print(message)
                    error_message = json.dumps({"data": message})
                    await self.send_notification("api/notification/irrigation", error_message)
                    return
                action = data.get("action")
                if action == "create":
                    try:
                        self.irrigation_controller.db.new_program(data["program"])
                        success_message = json.dumps({"data": "Programma creato con successo!"})
                        await self.send_notification("api/notification/irrigation", success_message)
                        await self.irrigation_controller.check_and_run_programs()
                    except Exception as e:
                        print(e)
                        error_message = json.dumps({"data": "Impossibile creare programma!"})
                        await self.send_notification("api/notification/irrigation", error_message)

                elif action == "edit":
                    try:
                        program_id = data.get("id")
                        self.irrigation_controller.db.edit_program(program_id, data["program"])
                        success_message = json.dumps({"data": "Programma modificato con successo!"})
                        await self.send_notification("api/notification/irrigation", success_message)
                        await self.irrigation_controller.check_and_run_programs()
                    except Exception as e:
                        print(e)
                        error_message = json.dumps({"data": "Impossibile modificare il programma!"})
                        await self.send_notification("api/notification/irrigation", error_message)
                elif action == "delete":
                    try:
                        program_id = data.get("id")
                        self.irrigation_controller.db.delete_program(program_id)
                        success_message = json.dumps({"data": "Programma elimintato con successo!"})
                        await self.send_notification("api/notification/irrigation", success_message)
                        await self.irrigation_controller.check_and_run_programs()
                    except Exception as e:
                        print(e)
                        error_message = json.dumps({"data": "Impossibile eliminare il programma!"})
                        await self.send_notification("api/notification/irrigation", error_message)

                print(f"Program {action} action executed")

        except Exception as e:
            print(f"Error handling message {topic}: {e}")

    async def keep_connection_active(self):
        while True:
            if is_wifi_connected() and self.client:
                try:
                    self.client.publish("api/ping", "ping")
                    await asyncio.sleep(10)
                except Exception as e:
                    print(f"Error sending ping to broker: {e}")

async def main():

    irrigation_db = IrrigationDatabase(db_name="irr_db")
    irrigation_db.create_db()
    irrigation_db.create_table(table_name="programs", table_obj=table_obj)

    irrigation_controller = IrrigationController()
    irrigation_controller.db = irrigation_db

    mqtt_handler = MQTTHandler(client_id="123", user=USER, password=PASSWORD, server=SERVER, topics=TOPICS, irrigation_controller=irrigation_controller)
    mqtt_handler.connect_to_mqtt()

    irrigation_controller.mqtt_client = mqtt_handler
    irrigation_controller.deactivate_all_zones()

    keep_connection_task = asyncio.create_task(mqtt_handler.keep_connection_active())
    check_programs_task = asyncio.create_task(mqtt_handler.irrigation_controller.check_and_run_programs())

    try:
        while True:
            try:
                mqtt_handler.client.check_msg()
                await asyncio.sleep(MQTT_CHECK_MSG_SLEEP_INTERVAL)
            except OSError as e:
                print(f"Error checking messages: {e}")
                mqtt_handler.connect_to_mqtt()
    except CancelledError:
        print("Main loop cancelled. Cleaning up...")
    finally:
        if keep_connection_task:
            keep_connection_task.cancel()
            try:
                await keep_connection_task
            except asyncio.CancelledError:
                print("keep_connection_task has been cancelled")

        if check_programs_task:
            check_programs_task.cancel()
            try:
                await check_programs_task
            except asyncio.CancelledError:
                print("check_programs_task has been cancelled")


asyncio.run(main())
