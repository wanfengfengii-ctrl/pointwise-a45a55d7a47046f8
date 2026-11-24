from lake.ingest.validation import validate_station_day
from lake.issue.manifest import FrozenManifest, PageEntry, base_coverage
from lake.issue.pages import ColdPage, PageIdentity, decode_page, page_digest
from lake.revision.ranges import KeyRange, contains_key
from lake.wire import require_text


def verify_manifest(manifest: FrozenManifest) -> None:
    if not isinstance(manifest, FrozenManifest):
        raise ValueError('expected a frozen manifest')
    require_text(manifest.freeze_id, 'freeze ID')
    require_text(manifest.revision_id, 'manifest revision ID')
    validate_station_day(manifest.station, manifest.day)
    if type(manifest.entries) is not tuple or not manifest.entries:
        raise ValueError('manifest must contain a base page')
    revisions = set()
    for page_no, entry in enumerate(manifest.entries, start=1):
        if not isinstance(entry, PageEntry) or not isinstance(entry.identity, PageIdentity):
            raise ValueError('invalid manifest page entry')
        identity = entry.identity
        if identity.freeze_id != manifest.freeze_id or identity.page_no != page_no:
            raise ValueError('manifest page identity or sequence mismatch')
        if identity.revision_id in revisions:
            raise ValueError('manifest repeats a source revision')
        revisions.add(identity.revision_id)
        if entry.coverage is None:
            if page_no != 1:
                raise ValueError('replacement page requires a declared range')
        elif not isinstance(entry.coverage, KeyRange):
            raise ValueError('invalid manifest coverage')
    if manifest.entries[-1].identity.revision_id != manifest.revision_id:
        raise ValueError('manifest tip revision mismatch')


def verify_page(manifest: FrozenManifest, identity: PageIdentity, payload: bytes) -> ColdPage:
    if (not isinstance(identity, PageIdentity) or identity.freeze_id != manifest.freeze_id
            or identity.page_no > len(manifest.entries)):
        raise ValueError('cold page identity is outside this freeze')
    entry = manifest.entries[identity.page_no - 1]
    if identity != entry.identity or page_digest(payload) != identity.digest:
        raise ValueError('cold page does not match the expected identity and digest')
    page = decode_page(payload)
    if page.identity != identity:
        raise ValueError('cold page header mismatches the expected identity')
    if identity.page_no == 1:
        if base_coverage(page.rows) != entry.coverage:
            raise ValueError('base page coverage mismatch')
        expected_origin = 'station'
        revision_prefix = 'batch:'
    else:
        if entry.coverage is None or any(not contains_key(entry.coverage, row.key) for row in page.rows):
            raise ValueError('cold page reading outside its declared range')
        expected_origin = 'correction'
        revision_prefix = 'amend:'
    if any(row.origin.kind != expected_origin or revision_prefix + row.origin.source_id != identity.revision_id
           for row in page.rows):
        raise ValueError('cold page contains a row from a different source record')
    return page
