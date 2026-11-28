"""Read the two source-backed negative motions alongside the earlier seven votes."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ART = HERE.parent


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def registry():
    archive = load(ART / "receipt" / "archive.json")
    negative = load(HERE / "negative_motions.json")
    assert archive["motions"].keys().isdisjoint(negative["motions"])
    archive["motions"].update(negative["motions"])
    archive["records"].extend(negative["records"])
    return archive


def request(archive, motion_id, older, newer):
    motion = archive["motions"][motion_id]
    return {
        "motion": motion_id,
        "repository": motion["repository"],
        "packet": [dict(row) for row in archive["records"] if row["motion"] == motion_id],
        "snapshots": [
            {"ref": name, "commit": motion["refs"].get(name, {}).get("commit")}
            for name in (older, newer)
        ],
    }
