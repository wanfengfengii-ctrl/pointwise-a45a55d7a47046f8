from lake.ingest.origins import correction_origin
from lake.ingest.rows import ReadingRow, order_rows_by_key, parse_input_rows
from .ranges import KeyRange, contains_key
from .store import RevisionRecord


def validate_replacement(correction_id: str, span: KeyRange, rows) -> tuple[ReadingRow, ...]:
    readings = parse_input_rows(rows, lambda position: correction_origin(correction_id, position))
    if any(not contains_key(span, row.key) for row in readings):
        raise ValueError('replacement reading lies outside the declared range')
    return order_rows_by_key(readings)


def replace_rows(parent_rows: tuple[ReadingRow, ...], span: KeyRange,
                 replacement: tuple[ReadingRow, ...]) -> tuple[ReadingRow, ...]:
    survivors = tuple(row for row in parent_rows if not contains_key(span, row.key))
    return order_rows_by_key(survivors + replacement)


def materialize_revision(lineage: tuple[RevisionRecord, ...]) -> tuple[ReadingRow, ...]:
    readings = lineage[0].rows
    for revision in lineage[1:]:
        if revision.declaration is None:
            raise ValueError('non-base revision is missing a replacement declaration')
        readings = replace_rows(readings, revision.declaration, revision.rows)
    return readings
