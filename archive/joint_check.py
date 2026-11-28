"""Count jointly verified links and Git-object agreements in the temporal evaluation."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
rows = [
    r for line in (root / "results.jsonl").read_text(encoding="utf-8").splitlines()
    if (r := json.loads(line))["month"] >= "2025-04" and r["reference"]
]
agrees = {
    item["mid"] for item in json.loads((root / "git_audit.json").read_text(encoding="utf-8"))["observations"]
    if item["outcome"] == "agrees"
}
for method in ("latest", "bm25", "key"):
    matches = [r for r in rows if r["predictions"][method] == r["reference"] and r["mid"] in agrees]
    print(f"{method}: {len(matches)} jointly verified / {len(rows)} traceable later notices")
