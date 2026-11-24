from collections.abc import Collection
from dataclasses import dataclass

from lake.issue.manifest import FrozenManifest
from lake.issue.pages import PageIdentity
from lake.revision.ranges import KeyRange, contains_key, intersect_ranges


@dataclass(frozen=True)
class CoverageSlice:
    span: KeyRange
    owner: PageIdentity | None
    verified: bool


def resolve_coverage(window: KeyRange, manifest: FrozenManifest,
                     received: Collection[PageIdentity]) -> tuple[CoverageSlice, ...]:
    """Resolve the last declaration on each span before considering page availability."""
    boundaries = {window.lo, window.hi}
    clipped = []
    for entry in manifest.entries:
        if entry.coverage is None:
            continue
        overlap = intersect_ranges(window, entry.coverage)
        if overlap is not None:
            boundaries.update((overlap.lo, overlap.hi))
            clipped.append((overlap, entry.identity))

    cuts = sorted(boundaries)
    slices = []
    for lo, hi in zip(cuts, cuts[1:]):
        # No declaration can start or end inside this slice.
        owner = next((identity for span, identity in reversed(clipped) if contains_key(span, lo)), None)
        slices.append(CoverageSlice(KeyRange(lo, hi), owner, owner is None or owner in received))
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
