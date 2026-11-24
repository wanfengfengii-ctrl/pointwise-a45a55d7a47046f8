from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
import sqlite3
from types import MappingProxyType

from lake.issue.manifest import FrozenManifest
from lake.issue.pages import ColdPage, PageIdentity
from lake.transactions import enable_foreign_keys, transaction
from .inventory import init_inventory, read_manifest, read_received_pages


@dataclass(frozen=True)
class InventorySnapshot:
    manifest: FrozenManifest
    pages: Mapping[PageIdentity, ColdPage]


def open_inventory(path: str | PathLike) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    try:
        enable_foreign_keys(db)
        with transaction(db, write=True):
            init_inventory(db)
    except BaseException:
        db.close()
        raise
    return db


def read_inventory_snapshot(db: sqlite3.Connection, freeze_id: str) -> InventorySnapshot:
    """Read the registered manifest and its committed pages from one SQLite snapshot."""
    with transaction(db, write=False):
        manifest = read_manifest(db, freeze_id)
        pages = read_received_pages(db, freeze_id)
    return InventorySnapshot(manifest, MappingProxyType(pages))
