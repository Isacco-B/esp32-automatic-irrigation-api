from lib.umqtt import MQTTClient
from utils.utils import connect_to_wifi, is_wifi_connected, validate_program_data
from irrigation_database import new_program, edit_program, delete_program
from irrigation_controller import toggle_zone, send_updated_status
from secrets import SERVER, USER, PASSWORD, CLIENT_ID
import asyncio
import json
import time

MQTT_CHECK_MSG_SLEEP_INTERVAL = 0.5
KEEP_CONNECTION_ACTIVE_SLEEP_INTERVAL = 10
ERROR_RETRY_INTERVAL = 2

TOPICS = {
    "ZONE": b"api/irrigation/zone",
    "PROGRAM": b"api/irrigation/program"
}

zone_pins = ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5", "zone_6", "zone_7", "zone_8"]
mqtt_client = None 

def connect_to_mqtt():
    global mqtt_client
    while not is_wifi_connected():
        connect_to_wifi()

    client = MQTTClient(client_id=CLIENT_ID, user=USER, password=PASSWORD, server=SERVER)
    client.set_callback(sub_cb)
    client.connect() 
    time.sleep(0.5)
    for topic in TOPICS.values():
        client.subscribe(topic)
    print(f"Connected to {SERVER}")
    mqtt_client = client
    return client

def sub_cb(topic, msg):
    handle_message(topic, msg)

def send_notification(topic, message):
    mqtt_client.publish(topic, message)

def handle_message(topic, msg):
    print((topic, msg))
    try:
        if topic == TOPICS["ZONE"]: 
            data = json.loads(msg.decode('utf-8'))
            zone_name = data.get("zone")
            duration = data.get("time")
            if zone_name in zone_pins:
                toggle_zone(zone_name, duration)
            else:
                print("Invalid Zone Name")

        elif topic == TOPICS["PROGRAM"]:
            data = json.loads(msg.decode('utf-8'))
            is_valid, message = validate_program_data(data)
            if not is_valid:
                print(message)
                error_message = json.dumps({"data": message})
                send_notification("api/notification/irrigation", error_message)
                return 
            action = data.get("action")
            if action == "create":
                try:
                    new_program(data["program"])
                    success_message = json.dumps({"data": "Programma creato con successo!"})
                    send_notification("api/notification/irrigation", success_message)
                    send_updated_status()
                except Exception as e:
                    print(e)
                    error_message = json.dumps({"data": "Impossibile creare programma!"})
                    send_notification("api/notification/irrigation", error_message)

            elif action == "edit":
                try:
                    program_id = data.get("id")
                    edit_program(program_id, data["program"])
                    success_message = json.dumps({"data": "Programma modificato con successo!"})
                    send_notification("api/notification/irrigation", success_message)
                    send_updated_status()
                except Exception as e:
                    print(e)
                    error_message = json.dumps({"data": "Impossibile modificare il programma!"})
                    send_notification("api/notification/irrigation", error_message)
            elif action == "delete":
                try:
                    program_id = data.get("id")
                    delete_program(program_id)
                    success_message = json.dumps({"data": "Programma elimintato con successo!"})
                    send_notification("api/notification/irrigation", success_message)
                    send_updated_status()
                except Exception as e:
                    print(e)
                    error_message = json.dumps({"data": "Impossibile eliminare il programma!"})
                    send_notification("api/notification/irrigation", error_message)

    except Exception as e:
        print(f"Error handling message {topic}: {e}")

async def keep_connection_active():
    while True:
        try:
            mqtt_client.publish("api/ping", "ping")
            await asyncio.sleep(KEEP_CONNECTION_ACTIVE_SLEEP_INTERVAL)
        except Exception as e:
            print(f"Error sending ping to broker: {e}")
            await asyncio.sleep(ERROR_RETRY_INTERVAL)