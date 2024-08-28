from utils.utils import connect_to_wifi
from machine import Pin

power_led = Pin(14, Pin.OUT)

power_led.on()
connect_to_wifi()