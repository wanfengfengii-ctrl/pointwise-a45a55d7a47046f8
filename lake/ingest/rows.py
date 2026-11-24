from collections.abc import Mapping
from dataclasses import dataclass

from lake.wire import array, unpack_int
from .origins import RowOrigin


@dataclass(frozen=True)
class ReadingRow:
    key: int
    liters: int | None
    origin: RowOrigin

    def __post_init__(self):
        if type(self.key) is not int:
            raise ValueError('reading key must be an integer')
        if self.liters is not None and type(self.liters) is not int:
            raise ValueError('reading must be integer liters or None')
        if not isinstance(self.origin, RowOrigin):
            raise ValueError('reading requires an original record position')


def make_reading_row(key: int, liters: int | None, origin: RowOrigin) -> ReadingRow:
    return ReadingRow(key, liters, origin)


def ensure_unique_keys(rows) -> None:
    seen = set()
    for row in rows:
        if row.key in seen:
            raise ValueError('duplicate reading key')
        seen.add(row.key)


def order_rows_by_key(rows) -> tuple[ReadingRow, ...]:
    return tuple(sorted(rows, key=lambda row: row.key))


def parse_input_rows(raw_rows, origin_for) -> tuple[ReadingRow, ...]:
    if isinstance(raw_rows, (str, bytes, Mapping)):
        raise ValueError('expected an iterable of reading triples')
    try:
        incoming = iter(raw_rows)
    except TypeError as exc:
        raise ValueError('expected an iterable of reading triples') from exc
    rows = []
    for raw in incoming:
        if not isinstance(raw, (tuple, list)) or len(raw) != 3:
            raise ValueError('each reading requires key, liters and position')
        key, liters, position = raw
        rows.append(make_reading_row(key, liters, origin_for(position)))
    ensure_unique_keys(rows)
    return tuple(rows)


def row_data(row: ReadingRow) -> list:
    return [
        hex(row.key),
        None if row.liters is None else hex(row.liters),
        row.origin.kind,
        row.origin.source_id,
        hex(row.origin.position),
    ]


def rows_from_data(data) -> tuple[ReadingRow, ...]:
    if type(data) is not list:
        raise ValueError('expected an array of stored readings')
    rows = []
    for item in data:
        key, liters, kind, source_id, position = array(item, 5)
        rows.append(make_reading_row(
            unpack_int(key),
            None if liters is None else unpack_int(liters),
            RowOrigin(kind, source_id, unpack_int(position)),
        ))
    ensure_unique_keys(rows)
    return tuple(rows)
