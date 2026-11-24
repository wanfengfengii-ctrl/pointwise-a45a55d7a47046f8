from dataclasses import dataclass

from lake.ingest.origins import RowOrigin
from lake.issue.pages import PageIdentity


@dataclass(frozen=True)
class AuditOrigin:
    page: PageIdentity
    page_position: int
    source: RowOrigin

    @property
    def freeze_id(self) -> str:
        return self.page.freeze_id


def make_audit_origin(page: PageIdentity, page_position: int, source: RowOrigin) -> AuditOrigin:
    return AuditOrigin(page, page_position, source)
