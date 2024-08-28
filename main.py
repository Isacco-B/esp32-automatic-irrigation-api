from irrigation_database import connect_db
from irrigation_mqtt import connect_to_mqtt, keep_connection_active
from irrigation_controller import check_and_run_programs, send_irrigation_status
from utils.utils import sync_time
import asyncio

MQTT_CHECK_MSG_SLEEP_INTERVAL = 0.5
MQTT_RETRY_INTERVAL = 1

connect_db()
sync_time()

async def main():
    while True:
        try:
            client = connect_to_mqtt()
            keep_connection_active_task = asyncio.create_task(keep_connection_active())
            check_and_run_programs_task = asyncio.create_task(check_and_run_programs())
            send_irrigation_status_task = asyncio.create_task(send_irrigation_status())

            while True:
                await asyncio.sleep(MQTT_CHECK_MSG_SLEEP_INTERVAL)
                try:
                    client.check_msg()
                except Exception as e:
                    print(f"Error checking messages: {e}")
                    break

        except Exception as e:
            print(f"MQTT communication error: {e}")

        finally:
            tasks = [keep_connection_active_task, check_and_run_programs_task, send_irrigation_status_task]
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        print("Task was cancelled")
            try:
                client.disconnect()
            except Exception as e:
                print(f"Error disconnecting client: {e}")

            await asyncio.sleep(MQTT_RETRY_INTERVAL)

asyncio.run(main())
