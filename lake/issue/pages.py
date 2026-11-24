from dataclasses import dataclass
from hashlib import sha256

from lake.ingest.rows import ReadingRow, order_rows_by_key, row_data, rows_from_data
from lake.wire import array, dump, load, require_text, unpack_int


@dataclass(frozen=True)
class PageIdentity:
    freeze_id: str
    revision_id: str
    page_no: int
    digest: str

    def __post_init__(self):
        require_text(self.freeze_id, 'freeze ID')
        require_text(self.revision_id, 'page revision ID')
        if type(self.page_no) is not int or self.page_no < 1:
            raise ValueError('page number must be a positive integer')
        if (type(self.digest) is not str or len(self.digest) != 64
                or any(character not in '0123456789abcdef' for character in self.digest)):
            raise ValueError('invalid page digest')


@dataclass(frozen=True)
class ColdPage:
    identity: PageIdentity
    rows: tuple[ReadingRow, ...]


def page_digest(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise ValueError('cold page payload must be bytes')
    return sha256(payload).hexdigest()


def identity_data(identity: PageIdentity) -> list:
    return [identity.freeze_id, identity.revision_id, hex(identity.page_no), identity.digest]


def identity_from_data(data) -> PageIdentity:
    freeze_id, revision_id, number, digest = array(data, 4)
    return PageIdentity(freeze_id, revision_id, unpack_int(number), digest)


def _page_payload(freeze_id: str, revision_id: str, page_no: int,
                  rows: tuple[ReadingRow, ...]) -> bytes:
    # Row positions within the page are the one-based indices of this array.
    return dump([1, freeze_id, revision_id, hex(page_no), [row_data(row) for row in rows]])


def make_cold_page(freeze_id: str, revision_id: str, page_no: int,
                   rows: tuple[ReadingRow, ...]) -> ColdPage:
    payload = _page_payload(freeze_id, revision_id, page_no, rows)
    return ColdPage(PageIdentity(freeze_id, revision_id, page_no, page_digest(payload)), rows)


def encode_page(page: ColdPage) -> bytes:
    identity = page.identity
    payload = _page_payload(identity.freeze_id, identity.revision_id, identity.page_no, page.rows)
    if page_digest(payload) != identity.digest:
        raise ValueError('cold page body differs from its identity')
    return payload


def decode_page(payload: bytes) -> ColdPage:
    version, freeze_id, revision_id, page_no, body = array(load(payload), 5)
    if type(version) is not int or version != 1:
        raise ValueError('unsupported cold page format')
    rows = rows_from_data(body)
    if rows != order_rows_by_key(rows):
        raise ValueError('cold page readings are out of key order')
    return ColdPage(PageIdentity(freeze_id, revision_id, unpack_int(page_no), page_digest(payload)), rows)
