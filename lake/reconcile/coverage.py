from collections.abc import Collection
from dataclasses import dataclass

from lake.issue.manifest import FrozenManifest, MoveEntry
from lake.issue.pages import PageIdentity
from lake.revision.ranges import KeyMove, KeyRange


@dataclass(frozen=True)
class CoverageSlice:
    span: KeyRange
    owner: PageIdentity | None
    offset: int
    verified: bool


def _remove_range(segments: list, span: KeyRange) -> list:
    kept = []
    for lo, hi, owner, offset in segments:
        if hi <= span.lo or lo >= span.hi:
            kept.append((lo, hi, owner, offset))
            continue
        if lo < span.lo:
            kept.append((lo, span.lo, owner, offset))
        if hi > span.hi:
            kept.append((span.hi, hi, owner, offset))
    return kept


def _apply_page(segments: list, span: KeyRange, owner: PageIdentity) -> list:
    return _remove_range(segments, span) + [(span.lo, span.hi, owner, 0)]


def _apply_move(segments: list, move: KeyMove) -> list:
    source, shift = move.source, move.shift
    mapped = [
        (max(lo, source.lo) + shift, min(hi, source.hi) + shift, owner, offset + shift)
        for lo, hi, owner, offset in segments
        if max(lo, source.lo) < min(hi, source.hi)
    ]
    segments = _remove_range(segments, source)
    segments = _remove_range(segments, move.dest)
    return segments + mapped


def _resolve_segments(manifest: FrozenManifest) -> list:
    """Replay the lineage declarations into sorted (lo, hi, owner, offset) bands."""
    segments = []
    for entry in manifest.entries:
        if isinstance(entry, MoveEntry):
            segments = _apply_move(segments, entry.move)
        elif entry.coverage is not None:
            segments = _apply_page(segments, entry.coverage, entry.identity)
    return sorted(segments)


def resolve_coverage(window: KeyRange, manifest: FrozenManifest,
                     received: Collection[PageIdentity]) -> tuple[CoverageSlice, ...]:
    """Resolve each band's owner and key offset before considering page availability."""
    boundaries = {window.lo, window.hi}
    clipped = []
    for lo, hi, owner, offset in _resolve_segments(manifest):
        overlap_lo, overlap_hi = max(lo, window.lo), min(hi, window.hi)
        if overlap_lo < overlap_hi:
            boundaries.update((overlap_lo, overlap_hi))
            clipped.append((overlap_lo, overlap_hi, owner, offset))

    cuts = sorted(boundaries)
    slices = []
    for lo, hi in zip(cuts, cuts[1:]):
        owner, offset = None, 0
        for band_lo, band_hi, band_owner, band_offset in clipped:
            if band_lo <= lo < band_hi:
                owner, offset = band_owner, band_offset
                break
        slices.append(CoverageSlice(KeyRange(lo, hi), owner, offset,
                                    owner is None or owner in received))
    return tuple(slices)


def coverage_ranges(slices: tuple[CoverageSlice, ...]) -> tuple[tuple[KeyRange, ...], tuple[KeyRange, ...]]:
    verified = []
    pending = []
    for piece in slices:
        ranges = verified if piece.verified else pending
        span = piece.span
        if ranges and ranges[-1].hi == span.lo:
            ranges[-1] = KeyRange(ranges[-1].lo, span.hi)
        else:
            ranges.append(span)
    return tuple(verified), tuple(pending)
