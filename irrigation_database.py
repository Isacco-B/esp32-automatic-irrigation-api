from lib.micropydatabase import Database

irrigation_db = None
irrigation_table = None

def connect_db():
    global irrigation_db, irrigation_table
    db_name = "irr_db"
    table_name = "programs"
    table_obj = {
        "name": str,
        "zone": str,
        "active_day": str,
        "start_time": str,
        "duration": int,
        "is_active": bool,
        "is_running": bool
    }
    if not Database.exist(db_name):
        Database.create(db_name)
        irrigation_db = Database.open(db_name)
        irrigation_db.create_table(table_name, table_obj)
        irrigation_table = irrigation_db.open_table(table_name)
    else:
        irrigation_db = Database.open(db_name)    
        irrigation_table = irrigation_db.open_table(table_name)

def new_program(new_program):
    irrigation_table.insert(new_program)

def edit_program(row_id, new_data):
    irrigation_table.update_row(row_id, new_data)

def get_all_programs():
    return list(irrigation_table.scan())

def get_program_by_id(row_id):
    return irrigation_table.get_row(row_id)

def delete_program(row_id):
    irrigation_table.delete_row(row_id)