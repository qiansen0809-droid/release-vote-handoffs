"""Evidence acquisition for one registered release motion using opaque typed reads."""
import argparse
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, permutations
from pathlib import Path
import json
import re

ORDER = ("result", "opening", "older", "newer")
ROUTE = {"Defer": "evidence custodian", "DoNotReuse": "receiving maintainer",
         "Review": "release owner", "Reuse": "receiving maintainer"}
OID = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Block:
    status: str
    url: str = ""
    oid: str = ""
    detail: str = ""


class Provider:
    """This local adapter exposes an envelope and four separately requested projections."""
    def __init__(self, archive, incoming):
        self.archive = archive
        self.incoming = incoming if isinstance(incoming, dict) else {}
        self.motion_id = self.incoming.get("motion")
        self.motion = archive["motions"].get(self.motion_id) if isinstance(self.motion_id, str) else None

    def envelope(self):
        if self.motion is None or self.motion["repository"] != self.incoming.get("repository"):
            return Block("invalid", detail="Unregistered motion or repository mismatch.")
        rows = self.incoming.get("packet")
        if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("role") not in ("opening", "result") for row in rows):
            return Block("invalid", detail="Invalid envelope or unrecognized evidence role.")
        return Block("valid", detail="Motion, repository and transmitted role-name format accepted.")

    def read(self, key):
        if key in ("older", "newer"):
            obs = self.incoming.get("snapshots")
            if not isinstance(obs, list) or len(obs) != 2:
                return Block("invalid", detail="Missing or malformed two-observation array.")
            side = obs[0 if key == "older" else 1]
            ref = side.get("ref") if isinstance(side, dict) else None
            pin = self.motion["refs"].get(ref, {}) if isinstance(ref, str) else {}
            commit = pin.get("commit")
            if not isinstance(commit, str) or not OID.fullmatch(commit) or side.get("commit") != commit:
                return Block("invalid", detail="Missing reference pin or disagreement with transmitted observation.")
            return Block("valid", pin.get("source", ""), commit, str(ref))

        registered = [r for r in self.archive["records"] if r["motion"] == self.motion_id and r["role"] == key]
        transmitted = [r for r in self.incoming["packet"] if r["role"] == key]
        if len(registered) != 1 or len(transmitted) != 1:
            return Block("invalid", detail="Absent or nonunique registered/transmitted " + key + ".")
        rec = registered[0]
        if transmitted[0] != rec or not isinstance(rec.get("url"), str) or not rec["url"]:
            return Block("invalid", detail="Record differs from registry or lacks a source URL.")
        if key == "result":
            disposition = rec.get("outcome")
            if disposition == "passed":
                return Block("pass", rec["url"], detail="Registered passing conclusion.")
            if disposition in ("withdrawn", "failed"):
                return Block("negative", rec["url"], detail=disposition)
            return Block("invalid", rec["url"], detail="Unresolved collective disposition.")
        candidate = rec.get("candidate_commit")
        if not isinstance(candidate, str) or not OID.fullmatch(candidate):
            return Block("unbound", rec["url"], detail="Valid opening without a verified candidate commit.")
        return Block("bound", rec["url"], candidate, "Valid opening and nominated candidate.")


def feasible(seen):
    """Image of the four-action policy over all completions of the unread blocks."""
    opening, closing = seen.get("opening"), seen.get("result")
    pins = [seen.get(side) for side in ("older", "newer")]
    if any(b and b.status == "invalid" for b in (opening, closing)):
        return {"Defer"}
    if opening and closing and opening.url == closing.url:
        return {"Defer"}
    outcomes = set()
    if not opening or not closing:
        outcomes.add("Defer")  # An unread role might be absent, altered or contradictory.
    if not closing or closing.status == "negative":
        outcomes.add("DoNotReuse")
    if closing and closing.status == "negative":
        return outcomes
    if (opening and opening.status == "unbound") or any(b and b.status == "invalid" for b in pins):
        return outcomes | {"Defer"}
    if any(b is None for b in pins):
        outcomes.add("Defer")
    commits = [b.oid for b in (opening, *pins) if b is not None]
    if len(set(commits)) <= 1:
        outcomes.add("Reuse")
    if len(commits) < 3 or len(set(commits)) > 1:
        outcomes.add("Review")
    return outcomes


def signature(seen):
    marks = tuple(seen[k].status if k in seen else "" for k in ORDER)
    left, right = seen.get("opening"), seen.get("result")
    same_url = bool(left and right and left.url and left.url == right.url)
    return marks, same_url


def minimal_support(seen, decision):
    for size in range(len(seen) + 1):
        for keys in combinations((k for k in ORDER if k in seen), size):
            if feasible({k:seen[k] for k in keys}) == {decision}:
                return list(keys)
    raise AssertionError("A certified action must have a support.")


def stop_cost(complete, order):
    seen = {}
    for key in order:
        seen[key] = complete[key]
        if len(feasible(seen)) == 1:
            return len(seen)
    raise AssertionError("Incomplete policy.")


class Planner:
    """Minimize training-set mean remaining reads without relaxing the stopping condition."""
    def __init__(self, training):
        self.training = tuple(training)
        candidates = permutations(ORDER)
        self.fixed = min(candidates, key=lambda order: sum(stop_cost(row, order) for row in training))
        self.policy = {}
        self._build()

    def _build(self):
        @lru_cache(maxsize=None)
        def visit(keys, indices):
            views = [{k:self.training[i][k] for k in keys} for i in indices]
            # A signature contains only status and URL equality, never case or motion IDs.
            # All rows sharing these marks have the same need for further checks, even
            # when the final Reuse/Review action differs by the actual SHA comparison.
            terminal = [len(feasible(view)) == 1 for view in views]
            assert len(set(terminal)) == 1
            if terminal[0]:
                return 0
            best_value = float("inf")
            best_key = None
            for key in ORDER:
                if key in keys:
                    continue
                next_keys = tuple(k for k in ORDER if k == key or k in keys)
                partitions = {}
                for i in indices:
                    sig = signature({k:self.training[i][k] for k in next_keys})
                    partitions.setdefault(sig, []).append(i)
                cost = len(indices) + sum(visit(next_keys, tuple(group)) for group in partitions.values())
                if cost < best_value:
                    best_key, best_value = key, cost
            self.policy[signature(views[0])] = best_key
            return best_value
        if self.training:
            visit((), tuple(range(len(self.training))))

    def choose(self, seen):
        key = self.policy.get(signature(seen))
        return key if key is not None else next(k for k in self.fixed if k not in seen)


def check(provider, strategy="policy", planner=None, budget=5):
    if not 1 <= budget <= 5:
        raise ValueError("Budget counts the envelope and must be between 1 and 5.")
    envelope = provider.envelope()
    seen = {}
    trace = {"envelope":vars(envelope)}
    if envelope.status == "invalid":
        return dict(decision="Defer", owner=ROUTE["Defer"], feasible=["Defer"], support=["envelope"], trace=trace, reads=1)
    order = {"eager":ORDER, "opening-first":("opening","result","older","newer"), "result-first":ORDER}
    if strategy == "fixed":
        order["fixed"] = planner.fixed
    while True:
        possible = feasible(seen)
        if len(possible) == 1 and (strategy != "eager" or len(seen) == 4):
            decision = next(iter(possible))
            return dict(decision=decision, owner=ROUTE[decision], feasible=[decision], support=["envelope", *minimal_support(seen, decision)],
                        trace=trace, reads=len(trace))
        if strategy == "policy":
            key = planner.choose(seen)
        elif strategy == "conditional":
            closing = seen.get("result")
            keys = ("result","older","newer","opening") if closing and closing.status == "pass" else ORDER
            key = next(k for k in keys if k not in seen)
        else:
            key = next(k for k in order[strategy] if k not in seen)
        if len(trace) == budget:
            return dict(decision=None, feasible=sorted(possible), next_read=key,
                        support=None, trace=trace, reads=len(trace))
        block = provider.read(key)
        seen[key] = block
        trace[key] = vars(block)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="cmd", required=True)
    verify = cmds.add_parser("verify", help="Run on a received JSON packet and a trusted JSON registry.")
    verify.add_argument("packet", type=Path)
    verify.add_argument("--registry", type=Path)
    verify.add_argument("--strategy", choices=["result-first","opening-first","conditional","eager","fixed","policy"],default="policy")
    verify.add_argument("--budget",type=int,default=5)
    replay = cmds.add_parser("replay", help="Rescore the complete paired benchmark and abstract truth-table check.")
    replay.add_argument("--check", action="store_true")
    args = parser.parse_args()
    from benchmark import fixtures, get_registry, summarize
    if args.cmd == "replay":
        summarize(args.check)
        return
    packet = json.loads(args.packet.read_text(encoding="utf-8-sig"))
    archive = json.loads(args.registry.read_text(encoding="utf-8-sig")) if args.registry else get_registry()
    planner = None
    if args.strategy in ("fixed","policy"):
        # Exclude the current motion from the bundled offline planner's training set.
        current = packet.get("motion") if isinstance(packet, dict) else None
        train = [c.blocks for c in fixtures(skip_motion=current, with_sql=False) if c.blocks]
        planner = Planner(train)
    print(json.dumps(check(Provider(archive,packet),args.strategy,planner,args.budget), indent=2))


if __name__ == "__main__":
    main()

