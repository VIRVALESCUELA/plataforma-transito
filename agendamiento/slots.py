from datetime import time


SCHEDULE_SLOTS = [
    {"key": "0900", "label": "09:00", "start": time(9, 0), "end": time(9, 45), "minutes": 45},
    {"key": "0945", "label": "09:45", "start": time(9, 45), "end": time(10, 30), "minutes": 45},
    {"key": "1030", "label": "10:30", "start": time(10, 30), "end": time(11, 15), "minutes": 45},
    {"key": "1115", "label": "11:15", "start": time(11, 15), "end": time(12, 0), "minutes": 45},
    {"key": "1200", "label": "12:00", "start": time(12, 0), "end": time(13, 0), "minutes": 60},
    {"key": "1500", "label": "15:00", "start": time(15, 0), "end": time(15, 45), "minutes": 45},
    {"key": "1545", "label": "15:45", "start": time(15, 45), "end": time(16, 30), "minutes": 45},
    {"key": "1630", "label": "16:30", "start": time(16, 30), "end": time(17, 15), "minutes": 45},
    {"key": "1715", "label": "17:15", "start": time(17, 15), "end": time(18, 0), "minutes": 45},
    {"key": "1800", "label": "18:00", "start": time(18, 0), "end": time(19, 0), "minutes": 60},
    {"key": "1900", "label": "19:00", "start": time(19, 0), "end": time(20, 0), "minutes": 60},
]

SCHEDULABLE_SLOTS = SCHEDULE_SLOTS
SLOT_BY_KEY = {slot["key"]: slot for slot in SCHEDULABLE_SLOTS}
FRIDAY_WORK_BLOCKED_SLOT_KEYS = {"1200", "1800", "1900"}
