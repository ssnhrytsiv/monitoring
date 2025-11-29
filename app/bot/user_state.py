# простий глобальний словник
USER_PROCESSING = {}

def is_processing(uid: int) -> bool:
    return USER_PROCESSING.get(uid) == "processing"

def start_processing(uid: int):
    USER_PROCESSING[uid] = "processing"

def finish_processing(uid: int):
    USER_PROCESSING[uid] = None