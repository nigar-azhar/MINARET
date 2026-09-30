"""Pull the Turtle blocks for specific Hadith individuals out of the SemanticHadith KG dump.

The dump (SemanticHadithKG.rdf.zip -> SemanticHadithKGV2.ttl, ~210 MB) is far too large to load
into rdflib just to look up the ~100 hadith a corpus actually cites, so it is streamed once and
only the needed `:<ID> rdf:type ...` statements are kept, verbatim, for
`common.parse_hadith_block()` to read. Results are cached as JSON next to the dump, keyed by the
set of requested IDs, so repeated KG builds do not re-stream the file.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable

TTL_MEMBER = "SemanticHadithKGV2.ttl"
_BLOCK_START = re.compile(r"^:([A-Z]{2}-HD\d{4}) ")


def _iter_lines(dump_path: Path):
    if dump_path.suffix == ".zip":
        with zipfile.ZipFile(dump_path) as zf:
            with zf.open(TTL_MEMBER) as raw:
                yield from io.TextIOWrapper(raw, encoding="utf-8")
    else:
        with open(dump_path, encoding="utf-8") as f:
            yield from f


def extract_blocks(dump_path: Path, kg_ids: Iterable[str], cache_dir: Path | None = None) -> dict:
    """Return {kg_id: raw_block_text or None}. A missing id maps to None (not in the dump)."""
    wanted = sorted(set(kg_ids))
    dump_path = Path(dump_path)
    cache_file = None
    if cache_dir is not None:
        digest = hashlib.sha256("\n".join(wanted).encode()).hexdigest()[:16]
        cache_file = Path(cache_dir) / f"hadith_blocks_{digest}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

    remaining = set(wanted)
    found: dict[str, str] = {}
    current_id, current = None, []
    for line in _iter_lines(dump_path):
        if current_id is None:
            m = _BLOCK_START.match(line)
            if m and m.group(1) in remaining:
                current_id, current = m.group(1), [line]
                if line.rstrip().endswith(" ."):
                    found[current_id] = "".join(current) + "\n\n"
                    remaining.discard(current_id)
                    current_id = None
            continue
        current.append(line)
        if line.rstrip().endswith(" ."):
            # Trailing blank line lets parse_hadith_block's end-of-statement regex match.
            found[current_id] = "".join(current) + "\n\n"
            remaining.discard(current_id)
            current_id = None
            if not remaining:
                break

    result = {k: found.get(k) for k in wanted}
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
