from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from lake.wire import dump, require_text
from .origins import station_origin
from .rows import ReadingRow, parse_input_rows, row_data


@dataclass(frozen=True)
class ValidatedBatch:
    batch_id: str
    station: str
    day: str
    rows: tuple[ReadingRow, ...]


def validate_station_day(station: str, day: str) -> None:
    require_text(station, 'station')
    require_text(day, 'day')
    try:
        parsed = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError('day must be a calendar date in YYYY-MM-DD form') from exc
    if parsed.isoformat() != day:
        raise ValueError('day must be a calendar date in YYYY-MM-DD form')


def validate_batch(batch_id: str, station: str, day: str, rows) -> ValidatedBatch:
    require_text(batch_id, 'batch ID')
    validate_station_day(station, day)
    readings = parse_input_rows(rows, lambda position: station_origin(batch_id, position))
    return ValidatedBatch(batch_id, station, day, readings)


def batch_fingerprint(batch: ValidatedBatch) -> str:
    facts = [batch.batch_id, batch.station, batch.day, [row_data(row) for row in batch.rows]]
    return sha256(dump(facts)).hexdigest()
