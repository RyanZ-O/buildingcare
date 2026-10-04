"""Whole-building relationship proposals, separate from active simulation topology."""
from functools import lru_cache
import json
from pathlib import Path

@lru_cache(maxsize=4)
def _read(path, stamp):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def load(directory):
    path=Path(directory)/'service-graph.json'
    if not path.is_file(): return None
    return _read(str(path.resolve()),path.stat().st_mtime_ns)
