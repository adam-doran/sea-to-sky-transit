"""Read a static GTFS zip into plain rows."""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass

TABLES = (
    "agency",
    "feed_info",
    "routes",
    "stops",
    "trips",
    "stop_times",
    "shapes",
    "calendar",
    "calendar_dates",
)
# feed_info.txt changes on every daily export even when nothing else does
VOLATILE = {"feed_info.txt"}

Row = dict[str, str]


@dataclass(frozen=True)
class GtfsFeed:
    tables: dict[str, list[Row]]
    zip_sha256: str
    content_sha256: str  # ignores files that change on every export

    def table(self, name: str) -> list[Row]:
        return self.tables.get(name, [])


def read_gtfs_zip(data: bytes) -> GtfsFeed:
    tables: dict[str, list[Row]] = {}
    content = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in sorted(zf.namelist()):
            raw = zf.read(name)
            if name not in VOLATILE:
                content.update(name.encode())
                content.update(hashlib.sha256(raw).digest())
            table = name.removesuffix(".txt")
            if table in TABLES:
                # BC Transit's files start with a UTF-8 byte-order mark
                reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                tables[table] = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
    if "routes" not in tables or "trips" not in tables:
        raise ValueError("not a GTFS feed: routes.txt or trips.txt missing")
    return GtfsFeed(tables=tables, zip_sha256=hashlib.sha256(data).hexdigest(), content_sha256=content.hexdigest())
