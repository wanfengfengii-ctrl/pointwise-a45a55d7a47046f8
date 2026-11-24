from dataclasses import dataclass

from lake.wire import array, unpack_int


@dataclass(frozen=True, order=True)
class KeyRange:
    lo: int
    hi: int

    def __post_init__(self):
        if type(self.lo) is not int or type(self.hi) is not int or self.lo >= self.hi:
            raise ValueError('range requires integer endpoints with lo < hi')


def validate_range(lo: int, hi: int) -> KeyRange:
    return KeyRange(lo, hi)


def contains_key(span: KeyRange, key: int) -> bool:
    return span.lo <= key < span.hi


def intersect_ranges(left: KeyRange, right: KeyRange) -> KeyRange | None:
    lo = max(left.lo, right.lo)
    hi = min(left.hi, right.hi)
    return KeyRange(lo, hi) if lo < hi else None


def range_data(span: KeyRange | None) -> list | None:
    if span is None:
        return None
    return [hex(span.lo), hex(span.hi)]


def range_from_data(data) -> KeyRange | None:
    if data is None:
        return None
    lo, hi = array(data, 2)
    return validate_range(unpack_int(lo), unpack_int(hi))
