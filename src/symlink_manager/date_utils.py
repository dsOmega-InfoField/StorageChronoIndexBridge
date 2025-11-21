from pathlib import Path
from datetime import datetime, timezone


DATE_DELIMITER = '.'
TIME_DELIMITER = '.'
DATETIME_PARTS_DELIMITER = '_'


# Get string of format:
# 2024.07.21_13.05.03
def format_datetime(d: datetime):
    return f'{d.year:04}{DATE_DELIMITER}{d.month:02}{DATE_DELIMITER}{d.day:02}{DATETIME_PARTS_DELIMITER}{d.hour:02}{TIME_DELIMITER}{d.minute:02}{TIME_DELIMITER}{d.second:02}'


def postfix_created_file_with_utc(filepath: Path) -> Path:
    now_utc = datetime.now(timezone.utc)

    return filepath.with_name(
        f'{filepath.name}{{{format_datetime(now_utc)}}}'
    )
