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
# Uncompressed, across the tables read. BC Transit's are under 1 MB; a zip
# claiming more than this is refused before anything is decompressed.
MAX_UNCOMPRESSED_BYTES = 50 * 2**20

Row = dict[str, str]


@dataclass(frozen=True)
class GtfsFeed:
    tables: dict[str, list[Row]]
    zip_sha256: str
    content_sha256: str  # ignores files that change on every export

    def table(self, name: str) -> list[Row]:
        return self.tables.get(name, [])


def read_gtfs_zip(data: bytes) -> GtfsFeed:
    """Only the files in TABLES are decompressed. The content hash covers
    those same files, which for BC Transit's feeds is every file."""
    tables: dict[str, list[Row]] = {}
    content = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [zf.getinfo(name) for name in sorted(zf.namelist()) if name.removesuffix(".txt") in TABLES]
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(f"GTFS tables over {MAX_UNCOMPRESSED_BYTES:,} bytes uncompressed")
        for info in members:
            with zf.open(info) as f:
                raw = f.read(info.file_size + 1)  # never more than the size checked above
            if len(raw) > info.file_size:
                raise ValueError(f"{info.filename} is larger than its zip entry says")
            if info.filename not in VOLATILE:
                content.update(info.filename.encode())
                content.update(hashlib.sha256(raw).digest())
            # BC Transit's files start with a UTF-8 byte-order mark
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
            tables[info.filename.removesuffix(".txt")] = rows
    if "routes" not in tables or "trips" not in tables:
        raise ValueError("not a GTFS feed: routes.txt or trips.txt missing")
    return GtfsFeed(tables=tables, zip_sha256=hashlib.sha256(data).hexdigest(), content_sha256=content.hexdigest())
