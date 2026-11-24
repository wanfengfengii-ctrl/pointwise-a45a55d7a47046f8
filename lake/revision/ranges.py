from dataclasses import dataclass

from lake.wire import array, unpack_int


@dataclass(frozen=True, order=True)
class KeyRange:
    lo: int
    hi: int

    def __post_init__(self):
        if type(self.lo) is not int or type(self.hi) is not int or self.lo >= self.hi:
            raise ValueError('range requires integer endpoints with lo < hi')


@dataclass(frozen=True)
class KeyMove:
    """Relocate the half-open source band to start at dest_lo, preserving length."""
    source: KeyRange
    dest_lo: int

    def __post_init__(self):
        if not isinstance(self.source, KeyRange):
            raise ValueError('move requires a source key range')
        if type(self.dest_lo) is not int:
            raise ValueError('move destination must be an integer key')
        if intersect_ranges(self.source, self.dest) is not None:
            raise ValueError('move source and destination must not intersect')

    @property
    def shift(self) -> int:
        return self.dest_lo - self.source.lo

    @property
    def dest(self) -> KeyRange:
        return KeyRange(self.dest_lo, self.dest_lo + (self.source.hi - self.source.lo))


def validate_move(lo: int, hi: int, dest_lo: int) -> KeyMove:
    return KeyMove(validate_range(lo, hi), dest_lo)


def validate_range(lo: int, hi: int) -> KeyRange:
    return KeyRange(lo, hi)


def contains_key(span: KeyRange, key: int) -> bool:
    return span.lo <= key < span.hi


def intersect_ranges(left: KeyRange, right: KeyRange) -> KeyRange | None:
    lo = max(left.lo, right.lo)
    hi = min(left.hi, right.hi)
    return KeyRange(lo, hi) if lo < hi else None


def range_data(span: KeyRange | KeyMove | None) -> list | None:
    if span is None:
        return None
    if isinstance(span, KeyMove):
        return [hex(span.source.lo), hex(span.source.hi), hex(span.dest_lo)]
    return [hex(span.lo), hex(span.hi)]


def range_from_data(data) -> KeyRange | KeyMove | None:
    if data is None:
        return None
    if type(data) is list and len(data) == 3:
        lo, hi, dest_lo = data
        return validate_move(unpack_int(lo), unpack_int(hi), unpack_int(dest_lo))
    lo, hi = array(data, 2)
    return validate_range(unpack_int(lo), unpack_int(hi))
