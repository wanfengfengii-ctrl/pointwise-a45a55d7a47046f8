from dataclasses import dataclass

from lake.ingest.rows import ReadingRow
from lake.revision.ranges import KeyRange, range_data, range_from_data
from lake.revision.store import RevisionRecord
from lake.wire import array, dump, load
from .pages import ColdPage, PageIdentity, identity_data, identity_from_data


@dataclass(frozen=True)
class PageEntry:
    coverage: KeyRange | None
    identity: PageIdentity


@dataclass(frozen=True)
class FrozenManifest:
    freeze_id: str
    revision_id: str
    station: str
    day: str
    entries: tuple[PageEntry, ...]


def base_coverage(rows: tuple[ReadingRow, ...]) -> KeyRange | None:
    if not rows:
        return None
    return KeyRange(rows[0].key, rows[-1].key + 1)


def build_manifest(freeze_id: str, lineage: tuple[RevisionRecord, ...],
                   pages: tuple[ColdPage, ...]) -> FrozenManifest:
    entries = []
    for revision, page in zip(lineage, pages, strict=True):
        coverage = revision.declaration
        if revision.parent_id is None:
            coverage = base_coverage(revision.rows)
        entries.append(PageEntry(coverage, page.identity))
    last = lineage[-1]
    return FrozenManifest(freeze_id, last.revision_id, last.station, last.day, tuple(entries))


def encode_manifest(manifest: FrozenManifest) -> bytes:
    entries = [
        [range_data(entry.coverage), identity_data(entry.identity)]
        for entry in manifest.entries
    ]
    return dump([1, manifest.freeze_id, manifest.revision_id, manifest.station, manifest.day, entries])


def decode_manifest(payload: bytes) -> FrozenManifest:
    version, freeze_id, revision_id, station, day, entries = array(load(payload), 6)
    if type(version) is not int or version != 1 or type(entries) is not list:
        raise ValueError('unsupported or invalid manifest format')
    decoded = []
    for item in entries:
        coverage, identity = array(item, 2)
        decoded.append(PageEntry(range_from_data(coverage), identity_from_data(identity)))
    return FrozenManifest(freeze_id, revision_id, station, day, tuple(decoded))
