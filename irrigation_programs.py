import json

PROGRAMS_FILE = "/programs.json"


def _load_data() -> dict:
    try:
        with open(PROGRAMS_FILE, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"next_id": 1, "programs": []}


def _save_data(data: dict) -> None:
    try:
        with open(PROGRAMS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving programs: {e}")
        raise


def get_all_programs() -> list:
    return _load_data()["programs"]


def get_program_by_id(program_id: int) -> dict:
    for prog in get_all_programs():
        if prog["id"] == program_id:
            return prog
    return None


def create_program(program_data: dict) -> dict:
    data = _load_data()
    new_id = data["next_id"]
    program = {"id": new_id, "is_active": True}
    program.update(program_data)
    data["programs"].append(program)
    data["next_id"] = new_id + 1
    _save_data(data)
    return program


def edit_program(program_id: int, updates: dict) -> dict:
    data = _load_data()
    for i, prog in enumerate(data["programs"]):
        if prog["id"] == program_id:
            data["programs"][i].update(updates)
            _save_data(data)
            return data["programs"][i]
    return None


def delete_program(program_id: int) -> bool:
    data = _load_data()
    original_len = len(data["programs"])
    data["programs"] = [p for p in data["programs"] if p["id"] != program_id]
    if len(data["programs"]) < original_len:
        _save_data(data)
        return True
    return False


def check_conflict(program_data: dict, exclude_id: int = None) -> tuple:
    """
    Check if program_data overlaps with any existing active program.
    Returns (has_conflict: bool, conflicting_name: str | None).
    Conflict = same day AND overlapping time window (start_time + duration).
    """
    programs = get_all_programs()
    new_start = _time_to_seconds(program_data["start_time"])
    new_end = new_start + program_data["duration"]
    new_days = set(program_data["active_days"])

    for prog in programs:
        if prog["id"] == exclude_id:
            continue
        if not prog.get("is_active", True):
            continue

        shared_days = new_days.intersection(set(prog["active_days"]))
        if not shared_days:
            continue

        existing_start = _time_to_seconds(prog["start_time"])
        existing_end = existing_start + prog["duration"]

        if new_start < existing_end and new_end > existing_start:
            return True, prog.get("name", "sconosciuto")

    return False, None


def _time_to_seconds(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 3600 + m * 60
