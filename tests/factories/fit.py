"""
Builds small, valid binary .FIT activity files for tests (no device files committed).

Only the messages the backend reads are written: file_id, record (timestamp, heart_rate, power)
and session (start_time, sport, total_elapsed_time, total_timer_time).
"""

import datetime
import struct
from typing import List, Optional

FIT_EPOCH = datetime.datetime(1989, 12, 31, tzinfo=datetime.timezone.utc)
SPORTS = {"running": 1, "cycling": 2, "swimming": 5, "training": 10}

_CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def _crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def _definition(local: int, global_num: int, fields):
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for num, size, base in fields:
        out += struct.pack("<BBB", num, size, base)
    return out


def _fit_time(dt: datetime.datetime) -> int:
    return int((dt - FIT_EPOCH).total_seconds())


def build_fit(
    start: datetime.datetime = datetime.datetime(2026, 10, 6, 7, 0, tzinfo=datetime.timezone.utc),
    seconds: int = 3600,
    power: Optional[List[int]] = None,
    heart_rate: Optional[List[int]] = None,
    sport: Optional[str] = "cycling",
    include_session: bool = True,
) -> bytes:
    """power/heart_rate are per-second samples (len == seconds) or None to omit that channel."""
    body = b""
    body += _definition(0, 0, [(0, 1, 0x00), (4, 4, 0x86)])           # file_id: type, time_created
    body += struct.pack("<BBI", 0, 4, _fit_time(start))                 # type 4 = activity

    body += _definition(1, 20, [(253, 4, 0x86), (3, 1, 0x02), (7, 2, 0x84)])  # record
    for i in range(seconds):
        hr = heart_rate[i] if heart_rate else 0xFF                       # 0xFF / 0xFFFF = invalid
        pw = power[i] if power else 0xFFFF
        body += struct.pack("<BIBH", 1, _fit_time(start) + i, hr, pw)

    if include_session:
        body += _definition(2, 18, [(253, 4, 0x86), (2, 4, 0x86), (5, 1, 0x00), (7, 4, 0x86), (8, 4, 0x86)])
        sport_code = SPORTS.get(sport, 0xFF) if sport else 0xFF
        body += struct.pack("<BIIBII", 2, _fit_time(start) + seconds, _fit_time(start), sport_code,
                            seconds * 1000, seconds * 1000)

    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    header += struct.pack("<H", _crc(header))
    data = header + body
    return data + struct.pack("<H", _crc(data))
