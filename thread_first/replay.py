"""Trace candidate vote openings using raw correspondence before any reference join."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE.parent / "archive"


def archive_module(root=ARCHIVE):
    spec = importlib.util.spec_from_file_location("frozen_archive", root / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


def raw_window(archive):
    messages = archive.load("subjects")
    votes = archive.load("vote_messages")
    openings = []
    notices = []
    for r in votes:
        subject = r["subject"]
        if archive.REPLY.search(subject) or not archive.VERSION.search(subject):
            continue
        if archive.RESULT.search(subject):
            if "2025-04" <= r["month"] <= "2025-12":
                notices.append(r)
        elif archive.VOTE.search(subject):
            openings.append(r)
    return messages, openings, notices


def reachable_openings(starts, messages, eligible, cutoff):
    result, seen = set(), set()
    work = list(starts)
    while work:
        ident = work.pop()
        if ident in seen:
            continue
        seen.add(ident)
        message = messages.get(ident)
        if message is None or message["when"] >= cutoff:
            continue
        if ident in eligible:
            result.add(ident)
        else:
            work.extend(message["refs"])
    return result


def infer(archive):
    messages, openings, notices = raw_window(archive)
    by_id = {r["id"]: r for r in messages}
    by_mid = {r["mid"]: r["id"] for r in messages if r["mid"]}
    outputs = []
    for q in notices:
        prior = [r for r in openings if r["when"] < q["when"]]
        ids = {r["id"] for r in prior}
        history = reachable_openings(q["refs"], by_id, ids, q["when"])
        cited = archive.THREAD_LINK.findall(archive.unquoted(q["body"]))
        linked = reachable_openings((by_mid[u] for u in cited if u in by_mid),
                                    by_id, ids, q["when"])
        roots = history | linked
        direct = next(iter(roots)) if len(roots) == 1 else None
        if len(roots) > 1:
            channel = "conflicting"
        elif history and linked:
            channel = "both"
        elif history:
            channel = "header"
        elif linked:
            channel = "body"
        else:
            channel = "neither"
        # Competing archival records are an explicit stop, not a reason to pick the top subject.
        fallback = None
        if not roots and prior:
            fallback = archive.rank_bm25(q["subject"], prior)["id"]
        def mid(ident):
            return by_id[ident]["mid"] if ident is not None else None
        outputs.append({"notice": q["mid"], "channel": channel,
                        "header_roots": sorted(mid(x) for x in history),
                        "body_roots": sorted(mid(x) for x in linked),
                        "direct": mid(direct), "thread_then_bm25": mid(direct or fallback)})
    return outputs


def score_after_inference(outputs, reference_file):
    original = [json.loads(l) for l in reference_file.read_text(encoding="utf8").splitlines()]
    refs = {r["mid"]: r["reference_mid"] for r in original if "2025-04" <= r["month"] <= "2025-12"}
    if len(outputs) != len(refs) or {r["notice"] for r in outputs} != set(refs):
        raise ValueError("Notice window changed")
    summary = {"notices": len(outputs), "channels": dict(Counter(r["channel"] for r in outputs))}
    for method in ("direct", "thread_then_bm25"):
        counts = Counter()
        for row in outputs:
            reference, selected = refs[row["notice"]], row[method]
            if reference:
                counts["same_channel_agreement" if selected == reference else "reference_mismatch_or_no_output"] += 1
            else:
                counts["unscored_prediction" if selected else "unscored_no_output"] += 1
        counts["returned"] = sum(r[method] is not None for r in outputs)
        summary[method] = dict(counts)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    outputs = infer(archive_module(args.archive))
    summary = score_after_inference(outputs, args.archive / "results.jsonl")
    for name, obj in [("predictions", outputs), ("summary", summary)]:
        (HERE / (name + ".json")).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
