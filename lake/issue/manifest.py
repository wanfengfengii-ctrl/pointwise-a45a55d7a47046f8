from dataclasses import dataclass

from lake.ingest.rows import ReadingRow
from lake.revision.ranges import KeyMove, KeyRange, range_data, range_from_data
from lake.revision.store import RevisionRecord
from lake.wire import array, dump, load, require_text
from .pages import ColdPage, PageIdentity, identity_data, identity_from_data


@dataclass(frozen=True)
class PageEntry:
    coverage: KeyRange | None
    identity: PageIdentity


@dataclass(frozen=True)
class MoveEntry:
    """A key-band relocation declared in the lineage; the move itself has no page."""
    revision_id: str
    move: KeyMove


@dataclass(frozen=True)
class FrozenManifest:
    freeze_id: str
    revision_id: str
    station: str
    day: str
    entries: tuple[PageEntry | MoveEntry, ...]


def base_coverage(rows: tuple[ReadingRow, ...]) -> KeyRange | None:
    if not rows:
        return None
    return KeyRange(rows[0].key, rows[-1].key + 1)


def build_manifest(freeze_id: str, lineage: tuple[RevisionRecord, ...],
                   pages: tuple[ColdPage, ...]) -> FrozenManifest:
    entries = []
    page_by_revision = {page.identity.revision_id: page for page in pages}
    for revision in lineage:
        if isinstance(revision.declaration, KeyMove):
            entries.append(MoveEntry(revision.revision_id, revision.declaration))
            continue
        coverage = revision.declaration
        if revision.parent_id is None:
            coverage = base_coverage(revision.rows)
        entries.append(PageEntry(coverage, page_by_revision[revision.revision_id].identity))
    last = lineage[-1]
    return FrozenManifest(freeze_id, last.revision_id, last.station, last.day, tuple(entries))


def _entry_data(entry: PageEntry | MoveEntry) -> list:
    if isinstance(entry, MoveEntry):
        return ['move', entry.revision_id, range_data(entry.move)]
    return ['page', range_data(entry.coverage), identity_data(entry.identity)]


def _entry_from_data(data) -> PageEntry | MoveEntry:
    tag = data[0] if type(data) is list and data else None
    if tag == 'move':
        tag, revision_id, move = array(data, 3)
        return MoveEntry(require_text(revision_id, 'move revision ID'), range_from_data(move))
    if tag == 'page':
        tag, coverage, identity = array(data, 3)
        return PageEntry(range_from_data(coverage), identity_from_data(identity))
    coverage, identity = array(data, 2)
    return PageEntry(range_from_data(coverage), identity_from_data(identity))


def encode_manifest(manifest: FrozenManifest) -> bytes:
    if any(isinstance(entry, MoveEntry) for entry in manifest.entries):
        entries = [_entry_data(entry) for entry in manifest.entries]
        return dump([2, manifest.freeze_id, manifest.revision_id, manifest.station, manifest.day, entries])
    entries = [
        [range_data(entry.coverage), identity_data(entry.identity)]
        for entry in manifest.entries
    ]
    return dump([1, manifest.freeze_id, manifest.revision_id, manifest.station, manifest.day, entries])


def decode_manifest(payload: bytes) -> FrozenManifest:
    version, freeze_id, revision_id, station, day, entries = array(load(payload), 6)
    if type(version) is not int or version not in (1, 2) or type(entries) is not list:
        raise ValueError('unsupported or invalid manifest format')
    if version == 1:
        decoded = []
        for item in entries:
            coverage, identity = array(item, 2)
            decoded.append(PageEntry(range_from_data(coverage), identity_from_data(identity)))
    else:
        decoded = [_entry_from_data(item) for item in entries]
    return FrozenManifest(freeze_id, revision_id, station, day, tuple(decoded))
