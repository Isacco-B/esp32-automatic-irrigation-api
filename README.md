# ESP32 Automatic Irrigation API

MicroPython firmware for an ESP32 that controls an automatic irrigation system via MQTT.

## Features

- **8 zones + main valve** — only one zone active at a time; main valve opens/closes automatically
- **3 float switches** — water level monitoring (read-only)
- **Manual control** — activate any zone for a custom duration (max 60 min)
- **Automatic programs** — weekly schedules with conflict detection; programs cannot overlap on the same day
- **Manual priority** — a manual activation pauses the running auto program; it resumes automatically when the manual zone ends, for the remaining window time
- **Late start** — if an auto program's window is still open at check time, it starts for the remaining time
- **User pause/resume/stop** — the user can pause a running program; it can be resumed as long as the original time window has not expired
- **Duration capping** — a resumed program is truncated if another scheduled program starts before its natural end
- **MQTT notifications** — real-time feedback for every action

## Hardware

| Component | GPIO |
|-----------|------|
| Zone 1–8 | 16, 17, 18, 25, 26, 27, 32, 33 |
| Main valve | 19 |
| Float switches 1–3 | 23, 34, 35 |

## Project Structure

```
main.py                  # Core logic: scheduler, MQTT handlers, pause/resume
irrigation_controller.py # Hardware state: pins, zone activation, timeouts
irrigation_programs.py   # JSON-based program storage and conflict detection
boot.py                  # WiFi connection and NTP sync on startup
utils/
  timezone.py            # DST-aware local time (Italy)
  messages.py            # Notification message templates
  utils.py               # WiFi helpers and payload validation
lib/
  umqtt.py               # MQTT client
secrets.py               # WiFi and MQTT credentials (not committed)
```

## MQTT Topics

### Commands (subscribe)

| Topic | Description |
|-------|-------------|
| `api/irrigation/zone` | Manual zone control (`cmd`: on/off/toggle, `zone`, `duration`) |
| `api/irrigation/program/create` | Create a new auto program |
| `api/irrigation/program/edit` | Edit an existing program |
| `api/irrigation/program/delete` | Delete a program |
| `api/irrigation/program/list` | Request program list |
| `api/irrigation/program/upcoming` | Request next N scheduled activations |
| `api/irrigation/program/control` | Pause / resume / stop a running program |
| `api/irrigation/status` | Start streaming system status (1 s interval, 60 s window) |

### Notifications (publish)

| Topic | Description |
|-------|-------------|
| `api/notification/irrigation/zone` | Zone activation / deactivation events |
| `api/notification/irrigation/program` | Program CRUD results |
| `api/notification/irrigation/program/list` | Full program list |
| `api/notification/irrigation/program/upcoming` | Upcoming activations |
| `api/notification/irrigation/program/control` | Pause / resume / stop results |
| `api/notification/irrigation/status` | System status payload |

## Program Schema

```json
{
  "name": "Morning",
  "zone": "zone_1",
  "start_time": "07:00",
  "duration": 1800,
  "active_days": [0, 1, 2, 3, 4]
}
```

`active_days`: 0 = Monday … 6 = Sunday. `duration` in seconds.

## Setup

1. Copy `secrets.example.py` to `secrets.py` and fill in your credentials.
2. Flash all files to the ESP32 using [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) or Thonny.
3. The device connects to WiFi and syncs NTP on boot, then starts the MQTT loop.
