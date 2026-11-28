"""Paired comparison on identical registry, packet and observations."""
import argparse
import copy
import json
from collections import Counter

from registry import ART, HERE, load, registry, request
from sql_baseline import decide
from validated_receipt import verify

FAULTS = ("missing_result", "foreign_result", "edited_result", "conflicting_registered_result",
          "missing_older_observation", "changed_newer_observation")


def damaged(db, packet, fault, foreign=None):
    db, packet = copy.deepcopy(db), copy.deepcopy(packet)
    r = next(item for item in packet["packet"] if item["role"] == "result")
    if fault == "missing_result":
        packet["packet"].remove(r)
    elif fault == "foreign_result":
        packet["packet"][packet["packet"].index(r)] = next(
            x for x in db["records"] if x["motion"] == foreign and x["role"] == "result")
    elif fault == "edited_result":
        r["outcome"] = "withdrawn"
    elif fault == "conflicting_registered_result":
        other = "passed" if r["outcome"] != "passed" else "withdrawn"
        db["records"].append({**r, "url": "urn:fixture:conflicting-result", "outcome": other})
    elif fault == "missing_older_observation":
        packet["snapshots"][0].pop("commit")
    elif fault == "changed_newer_observation":
        observed = packet["snapshots"][1]["commit"]
        pins = db["motions"][packet["motion"]]["refs"].values()
        packet["snapshots"][1]["commit"] = next(pin["commit"] for pin in pins if pin["commit"] != observed)
    elif fault == "no_git_observations":
        packet.pop("snapshots")
    else:
        raise ValueError(fault)
    return db, packet


def evaluate():
    db = registry()
    originals = load(ART / "receipt" / "cases.json")
    old_results = load(ART / "receipt" / "results.json")
    legacy = list(dict.fromkeys(c["motion"] for c in originals))
    rows, examples = [], {}

    def compare(group, case, archive, packet, expected):
        actual = verify(archive, packet)
        sql = decide(archive, packet)
        rows.append({"group": group, "motion": packet["motion"], "case": case, "expected": expected,
                     "receipt": actual["decision"], "sqlite_validation": sql,
                     "receipt_reason": actual["reason"], "next_owner": actual["next_owner"]})
        if actual["decision"] != expected or sql != expected:
            raise AssertionError(rows[-1])
        return actual

    for c, old in zip(originals,old_results["rows"],strict=True):
        motion = c["motion"]
        packet = request(db, motion, c["older"], c["newer"])
        assert c["continuity"] == old["receipt"]
        compare("complete", [c["older"],c["newer"]], db, packet, c["continuity"])
        if c["continuity"] == "Reuse":
            foreign = legacy[(legacy.index(motion) + 1) % len(legacy)]
            for fault in FAULTS:
                bad_db, bad_packet = damaged(db, packet, fault, foreign)
                compare("single_fault", fault, bad_db, bad_packet, "Defer")
    assert {(r["motion"],r["case"],r["expected"]) for r in rows if r["group"] == "single_fault"} == {
        (r["motion"],r["fault"],r["decision"]) for r in old_results["faults"]}

    for motion in ("polaris-ipmc-rc5","otava-ipmc-rc3"):
        older,newer = db["motions"][motion]["refs"]
        packet = request(db, motion, older, newer)
        result = compare("documented_negative", [older,newer], db, packet, "DoNotReuse")
        examples[motion] = result
        for fault,expected in (("missing_result","Defer"), ("conflicting_registered_result","Defer"),
                               ("no_git_observations","DoNotReuse")):
            bad_db,bad_packet = damaged(db, packet, fault)
            compare("negative_control", fault, bad_db, bad_packet, expected)
    examples["kafka"] = verify(db, request(db,"kafka","3.9.0","3.9.1"))
    summary = {}
    for group in dict.fromkeys(r["group"] for r in rows):
        part = [r for r in rows if r["group"] == group]
        summary[group] = {
            "n": len(part), "action_agreement": sum(r["receipt"]==r["sqlite_validation"] for r in part),
            "expected_action_counts": dict(Counter(r["expected"] for r in part)),
            "both_correct": sum(r["receipt"] == r["sqlite_validation"] == r["expected"] for r in part),
            "both_definite": sum(r["receipt"] != "Defer" and r["sqlite_validation"] != "Defer" for r in part)
        }
    return {"summary": summary, "rows": rows}, examples


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    results,examples = evaluate()
    for name, obj in (("results.json", results),("examples.json",examples)):
        if args.write:
            (HERE/name).write_text(json.dumps(obj,indent=2)+"\n",encoding="utf-8")
        elif obj != load(HERE/name):
            raise SystemExit(f"Replay differs in {name}")
    print(json.dumps(results["summary"],indent=2))
