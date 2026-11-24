from dataclasses import dataclass

from lake.wire import require_text


@dataclass(frozen=True)
class RowOrigin:
    kind: str
    source_id: str
    position: int

    def __post_init__(self):
        if self.kind not in ('station', 'correction'):
            raise ValueError('unknown row origin kind')
        require_text(self.source_id, 'origin ID')
        if type(self.position) is not int or self.position < 0:
            raise ValueError('origin position must be a nonnegative integer')


def station_origin(batch_id: str, position: int) -> RowOrigin:
    return RowOrigin('station', batch_id, position)


def correction_origin(correction_id: str, position: int) -> RowOrigin:
    return RowOrigin('correction', correction_id, position)
