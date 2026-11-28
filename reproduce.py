"""Recalculate the public row-based results; optionally rerun extractors on hydrated mail."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import subprocess
import sys
from hashlib import sha256

HERE = Path(__file__).resolve().parent
SCOPES = ("current_two_tag", "historical_destination")
DEFINITE = {"Review", "DoNotReuse", "Reuse"}


def rows(name):
    with (HERE / "data" / name).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def linkage():
    source = rows("notice_linkage.csv")
    test = [r for r in source if r["month"] >= "2025-04"]
    supported = [r for r in test if r["reference"]]
    unknown = [r for r in test if not r["reference"]]
    assert len(source) == 61 and len(supported) == 44 and len(unknown) == 4
    expected = {
        "latest": (12, 32, 0, 4),
        "bm25": (42, 2, 0, 4),
        "key": (40, 1, 3, 4),
        "direct": (44, 0, 0, 0),
        "direct_then_bm25": (44, 0, 0, 4),
    }
    result = {}
    for k, target in expected.items():
        agree = sum(r[k] == r["reference"] for r in supported)
        abstain = sum(not r[k] for r in supported)
        v = (
            agree,
            len(supported) - agree - abstain,
            abstain,
            sum(bool(r[k]) for r in unknown),
        )
        assert v == target, (k, v, target)
        result[k] = v
    jointly = {
        k: sum(
            r[k] == r["reference"] and r["git_outcome"] == "agrees" for r in supported
        )
        for k in ("bm25", "key")
    }
    assert jointly == {"bm25": 19, "key": 18}
    print(
        "Notice linkage (agree / differ / abstain / proposed with unknown reference):",
        result,
    )
    print("Joint opening and current Git agreement on 44 traceable notices:", jointly)


def recovery():
    source = rows("reference_openings.csv")
    ref = {(r["subset"], r["opening"]): r for r in source}
    assert len(source) == len(ref) == 32
    groups = defaultdict(list)
    for r in rows("recovery_predictions.csv"):
        assert (r["subset"], r["opening"]) in ref
        groups[r["subset"], r["method"], r["question"]].append(r)
    expected = {
        ("development", "earlier"): (14, 3, None),
        ("development", "revision1"): (17, 9, 8),
        ("development", "revision2"): (17, 9, 8),
        ("panel1", "earlier"): (5, 2, 0),
        ("panel1", "revision1"): (6, 2, 1),
        ("panel1", "revision2"): (7, 5, 5),
        ("panel2", "earlier"): (3, 1, 0),
        ("panel2", "revision1"): (5, 1, 0),
        ("panel2", "revision2"): (7, 1, 0),
    }
    for (panel, method), target in expected.items():
        located = []
        correct = []
        for scope in SCOPES:
            subset = groups.get((panel, method, scope), [])
            if not subset:
                correct.append(None)
                continue
            assert (
                len(subset)
                == len({r["opening"] for r in subset})
                == sum(r["subset"] == panel for r in source)
            )
            if any(r["actual"] not in DEFINITE | {"NoRecord", "Defer"} for r in subset):
                raise ValueError("Invalid prediction in public row file")
            located.append(sum(r["actual"] != "NoRecord" for r in subset))
            correct.append(
                sum(
                    r["actual"] in DEFINITE
                    and r["actual"] == ref[(panel, r["opening"])][scope]
                    for r in subset
                )
            )
        observed = (located[0], *correct)
        assert len(set(located)) == 1 and observed == target, (panel, method, observed)
        print(
            f"{panel} / {method}: found {located[0]}, correct determinate (current, dated) {tuple(correct)}"
        )
    for panel, target in {
        "development": (9, 8),
        "panel1": (5, 5),
        "panel2": (4, 3),
    }.items():
        assert (
            tuple(
                sum(r["subset"] == panel and r[scope] in DEFINITE for r in source)
                for scope in SCOPES
            )
            == target
        )


def coordination():
    events = rows("coordination_issues.csv")
    stats = Counter(r["coverage"] for r in events)
    counts = (
        len(events),
        sum(bool(r["reply_by_another_person"]) for r in events),
        sum(bool(r["third_step"]) for r in events),
    )
    assert len({r["issue"] for r in events}) == len(events) and counts == (37, 21, 13)
    assert stats == {"Core": 2, "Mixed": 1, "External": 34}
    with_reply = Counter(
        r["coverage"] for r in events if r["reply_by_another_person"]
    )
    assert with_reply == {"Core": 1, "Mixed": 1, "External": 19}
    assert all(not r["third_step"] or r["reply_by_another_person"] for r in events)
    print("Coordination (issues, reply, subsequent step):", counts)
    diff = json.loads((HERE / "data/git_difference.json").read_bytes())
    assert len(diff) == 1 and diff[0]["ahead_by"] == 1 and len(diff[0]["files"]) == 83
    assert all(Path(f["path"]).name == "pom.xml" for f in diff[0]["files"])
    print("Hudi candidate-to-final comparison: 1 commit, 83 Maven POM paths.")


def extraction(folder, requested):
    from hydrate import fingerprint

    sys.path.insert(0, str(HERE / "reconstruction"))
    import infer
    import successor

    catalog = json.loads((HERE / "data/family_sources.json").read_bytes())
    expected = rows("recovery_predictions.csv")
    frozen = json.loads((HERE / "data/extractor_sha256.json").read_bytes())
    for name, digest in frozen.items():
        assert (
            sha256((HERE / "reconstruction" / name).read_bytes()).hexdigest() == digest
        ), name
    for project in requested or catalog:
        specification = catalog[project]
        restored = json.loads((folder / (project + ".json")).read_bytes())
        messages = restored["messages"]
        assert len(messages) == len(specification["messages"]), project
        for restored_m, row in zip(messages, specification["messages"], strict=True):
            assert {k: restored_m[k] for k in ("url", "date", "subject", "sender")} == {
                k: row[k] for k in ("url", "date", "subject", "sender")
            }
            assert fingerprint(restored_m["body"]) == row["body_sha256"]
        family = dict(specification, messages=messages)
        for method, extractor in (
            ("revision1", infer.family_report),
            ("revision2", successor.family_report),
        ):
            motions = extractor(family)["motions"]
            details = {m["opening"]: m for m in motions if m.get("opening")}
            selected = [
                r for r in expected if r["method"] == method and r["project"] == project
            ]
            assert selected and set(details).issubset(r["opening"] for r in selected)
            for r in selected:
                prediction = (
                    details[r["opening"]][r["question"]]["action"]
                    if r["opening"] in details
                    else "NoRecord"
                )
                assert prediction == r["actual"], (project, method, r, prediction)
        print(
            f"{project}: re-extracted both revisions from {len(messages)} verified original bodies."
        )


def checked(cmd):
    r = subprocess.run(
        [sys.executable, "-B", *cmd],
        cwd=HERE,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    print("Passed", " ".join(cmd))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--captures", type=Path, help="Directory of hash-checked hydrated captures"
    )
    parser.add_argument(
        "--project", help="Limit raw rerun to a named project; requires --captures"
    )
    args = parser.parse_args()
    if args.project and not args.captures:
        parser.error("--project requires --captures")
    if not __debug__:
        raise SystemExit("Run with assertions enabled (omit -O).")
    linkage()
    recovery()
    coordination()
    checked(["validated/evaluate.py"])
    checked(["acquisition/acquire.py", "replay", "--check"])
    checked(["reconstruction/boundary.py"])
    checked(["reconstruction/check_intent.py"])
    if args.captures:
        extraction(args.captures, [args.project] if args.project else None)


if __name__ == "__main__":
    main()
