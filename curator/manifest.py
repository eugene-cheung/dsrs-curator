"""Cache-hit / request manifest. Printed on stderr; optional file is gitignored."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ManifestEntry:
    url: str
    path: str
    status: int
    cache_hit: bool
    bytes: int


@dataclass
class Manifest:
    entries: list[ManifestEntry] = field(default_factory=list)

    def record(
        self,
        url: str,
        path: Path,
        *,
        status: int,
        cache_hit: bool,
        n_bytes: int,
    ) -> None:
        self.entries.append(
            ManifestEntry(
                url=url,
                path=str(path),
                status=status,
                cache_hit=cache_hit,
                bytes=n_bytes,
            )
        )

    def summary_lines(self) -> list[str]:
        hits = sum(1 for e in self.entries if e.cache_hit)
        misses = len(self.entries) - hits
        total_bytes = sum(e.bytes for e in self.entries)
        return [
            f"EDGAR manifest: {len(self.entries)} GETs, "
            f"{hits} cache hits, {misses} fetches, {total_bytes} bytes",
        ]

    def print_summary(self) -> None:
        for line in self.summary_lines():
            print(line, file=sys.stderr)

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            for e in self.entries:
                fh.write(json.dumps(e.__dict__, sort_keys=True) + "\n")
