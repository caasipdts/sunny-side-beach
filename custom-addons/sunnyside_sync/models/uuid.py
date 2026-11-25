import secrets
import time
import uuid


def new_uuid7():
    """Create an RFC 9562 UUIDv7 without requiring Python 3.14's uuid.uuid7()."""
    timestamp_ms = time.time_ns() // 1_000_000
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return str(uuid.UUID(int=value))
