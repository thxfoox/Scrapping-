"""Save an analysis batch written with positional keys ("1", "2", ...) from the last digest.

    python save_batch.py /path/to/batch.json      # -> data/analysis/batch_NNN.json
"""

import json
import sys
from pathlib import Path

from build_report import DATA, load_places

keys = (DATA / "current_batch.txt").read_text().split()
raw = json.loads(Path(sys.argv[1]).read_text())
known = {p["key"]: p["name"] for p in load_places()}
out = {}
for pos, analysis in raw.items():
    key = keys[int(pos) - 1]
    if key not in known:
        sys.exit(f"position {pos}: unknown key {key}")
    expected = analysis.pop("_name", None)
    if expected and expected.lower()[:12] not in known[key].lower():
        sys.exit(f"position {pos}: name mismatch, digest has '{known[key]}', analysis says '{expected}'")
    out[key] = analysis
n = len(list((DATA / "analysis").glob("batch_*.json"))) + 1
path = DATA / "analysis" / f"batch_{n:03d}.json"
path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(f"saved {len(out)} analyses -> {path.name}: " + ", ".join(known[k] for k in out))
