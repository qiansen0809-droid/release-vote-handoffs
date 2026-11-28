"""Regression checks for a post-audit correction. No checks are holdout predictions."""
import json

from boundary import example
import infer
import intent


CASES = (
    ("I will cancel this vote.", "Defer"),
    ("I would cancel this vote.", "Defer"),
    ("I plan to cancel this vote.", "Defer"),
    ("I'm going to cancel this vote.", "Defer"),
    ("I'll cancel this vote.", "Defer"),
    ("Let’s cancel this vote.", "Defer"),
    ("Please cancel this vote.", "Defer"),
    ("I cancel this vote if the issue persists.", "Defer"),
    ("I cancel this vote, contingent on the issue persisting.", "Defer"),
    ("Cancel this vote tomorrow.", "Defer"),
    ("I would be glad if the vote has passed.", "Defer"),
    ("We hope the vote passes.", "Defer"),
    ("Cancel this thread, due to a build error.", "DoNotReuse"),
    ("I cancel this vote.", "DoNotReuse"),
    ("I have withdrawn this vote.", "DoNotReuse"),
    ("This vote has been cancelled.", "DoNotReuse"),
    ("The vote has passed. I will publish the release tomorrow.", "Reuse"),
    ("RC1 is closed and I will start a new vote.", "DoNotReuse"),
)


def check():
    results = []
    for message, expected in CASES:
        family = example()
        family["messages"][1]["body"] = message
        rows = intent.family_report_safe(family)["motions"]
        assert len(rows) == 1
        row = rows[0]
        for scope in infer.REQUIRED:
            decision = row[scope]
            assert decision["action"] == expected, (message, scope, decision)
            assert bool(decision["support"]) == (expected != "Defer"), message
            if decision["support"]:
                assert any(w["role"] == "conclusion" for w in decision["support"])
        results.append(dict(message=message, expected=expected))
    return results


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
