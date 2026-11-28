"""Produce a source-linked action for one nominated release opening and question."""
import argparse
import json
from pathlib import Path
import sys

ARTIFACT = Path(__file__).resolve().parent
sys.path.insert(0, str(ARTIFACT / "reconstruction"))
from infer import read_capture
from successor import family_report

POLICIES = {
    "current-tags": "current_two_tag",
    "dated-source": "historical_destination",
}


def handoff(family, opening, question):
    report = family_report(family)
    hits = [m for m in report["motions"] if m["opening"] == opening]
    result = {
        "repository": family["repository"],
        "release": family["version"],
        "opening": opening,
        "question": question,
        "git_observed_at": family.get("tag_observation", {}).get("observed_utc"),
    }
    if len(hits) != 1:
        return {**result, "action": "Defer", "owner": "evidence custodian",
                "reason": "no unique reconstructed motion for the nominated opening",
                "next": ["locate and reconcile the opening in the captured mail"],
                "support": []}
    motion = hits[0]
    decision = motion[POLICIES[question]]
    action = decision["action"]
    if action == "Defer":
        owner, tasks = "evidence custodian", decision["requests"]
    elif action == "Review":
        owner, tasks = "release owner", ["review the source difference or identify an applicable motion"]
    elif action == "DoNotReuse":
        owner, tasks = "receiving maintainer", ["record the negative disposition and seek an applicable motion"]
    elif action == "Reuse":
        owner, tasks = "receiving maintainer", ["attach the scoped source evidence to the handoff"]
    else:
        raise ValueError(f"Unsupported action {action}")
    return {**result, "action": action, "owner": owner, "reason": decision["reason"],
            "next": tasks, "support": decision["support"],
            "closing_witnesses": motion["closing_witnesses"],
            "candidate_observation": motion["candidate_observation"],
            "dated_commits": motion["dated_commits"],
            "final_observation": motion["final_observation"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("opening", help="Exact URL of the nominated opening")
    parser.add_argument("question", choices=POLICIES)
    args = parser.parse_args()
    print(json.dumps(handoff(read_capture(args.capture), args.opening, args.question),
                     indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
