"""Optional user deadline for a finite test queue. GPL-3.0-or-later."""
import datetime as dt
import math


def deadline_timestamp(value):
    if value is None:
        return math.inf
    if not isinstance(value, str):
        raise ValueError('Deadline must be an aware ISO timestamp or null')
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Deadline timezone is required')
    return parsed.timestamp()
