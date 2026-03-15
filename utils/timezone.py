import time

import ntptime

NTP_HOST = "pool.ntp.org"
NTP_MAX_RETRIES = 10
EPOCH_OFFSET = 946684800


def _last_sunday(year: int, month: int) -> int:
    if month == 12:
        last_day = 31
    else:
        next_month = time.mktime((year, month + 1, 1, 0, 0, 0, 0, 0, 0))
        curr_month = time.mktime((year, month, 1, 0, 0, 0, 0, 0, 0))
        last_day = (next_month - curr_month) // 86400

    t = time.localtime(time.mktime((year, month, last_day, 0, 0, 0, 0, 0, 0)))
    return last_day - t[6]


def _is_dst(utc_t: tuple) -> bool:
    year, month, day, hour = utc_t[0], utc_t[1], utc_t[2], utc_t[3]

    if month < 3 or month > 10:
        return False
    if 3 < month < 10:
        return True

    ls = _last_sunday(year, month)

    if month == 3:
        return day > ls or (day == ls and hour >= 1)
    if month == 10:
        return day < ls or (day == ls and hour < 1)


def tz_offset() -> int:
    return 7200 if _is_dst(time.localtime()) else 3600


def sync_ntp() -> bool:
    ntptime.host = NTP_HOST

    for attempt in range(1, NTP_MAX_RETRIES + 1):
        try:
            ntptime.settime()
            print(f"NTP sync OK — UTC: {time.localtime()}")
            return True
        except Exception as e:
            print(f"NTP attempt {attempt}/{NTP_MAX_RETRIES} failed: {e}")
            time.sleep(2)

    print("NTP sync failed")
    return False


def now_unix() -> int:
    return time.time() + EPOCH_OFFSET + tz_offset()


def now_unix_ms() -> int:
    return now_unix() * 1000
