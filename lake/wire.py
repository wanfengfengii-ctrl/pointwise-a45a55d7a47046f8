"""Canonical JSON and lossless integer fields for stored and shipped records."""

import json


def dump(data) -> bytes:
    return json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


def load(payload: bytes):
    if type(payload) is not bytes:
        raise ValueError('record payload must be bytes')
    try:
        return json.loads(payload.decode('utf-8'))
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid record payload') from exc


def array(data, size: int) -> list:
    if type(data) is not list or len(data) != size:
        raise ValueError(f'expected an array of {size} fields')
    return data


def require_text(value, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f'{field} must be nonblank text')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(f'{field} must be valid Unicode text') from exc
    return value


def unpack_int(value) -> int:
    if type(value) is not str:
        raise ValueError('invalid integer encoding')
    try:
        number = int(value, 16)
    except ValueError as exc:
        raise ValueError('invalid integer encoding') from exc
    if hex(number) != value:
        raise ValueError('noncanonical integer encoding')
    return number
