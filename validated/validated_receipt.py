"""Issue a routed handoff receipt or compare it with the independent SQLite implementation."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from registry import load, registry, request

POLICY = "two-reference-source-identity/2"
ROLES = ("opening", "result")
NEGATIVES = {"withdrawn", "failed"}
OWNERS = {"Reuse": "receiving maintainer", "Review": "release owner",
          "DoNotReuse": "receiving maintainer", "Defer": "evidence custodian"}


def sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{40}", value) is not None


def fingerprint(row):
    data = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def verify(archive, incoming):
    incoming = incoming if isinstance(incoming, dict) else {}
    motion_id = incoming.get("motion")
    motion = archive["motions"].get(motion_id) if isinstance(motion_id, str) else None
    entries = [r for r in archive["records"] if r["motion"] == motion_id]
    refs = motion["refs"] if motion else {}
    snapshots = incoming.get("snapshots")
    observations = []
    for i, side in enumerate(("older", "newer")):
        s = snapshots[i] if isinstance(snapshots, list) and i < len(snapshots) else None
        s = s if isinstance(s, dict) else {}
        name = s.get("ref")
        pin = refs.get(name, {}) if isinstance(name, str) else {}
        observations.append({"side": side, "ref": name, "received_commit": s.get("commit"),
                             "registered_commit": pin.get("commit"), "source": pin.get("source"),
                             "observed_at": pin.get("observed_at")})
    output = {"policy": POLICY, "motion": motion_id, "repository": incoming.get("repository"),
              "outcome": None, "candidate_commit": None, "candidate_basis": None,
              "registered_sources": [{"role": r["role"], "url": r["url"]} for r in entries],
              "verified_evidence": [], "observations": observations}

    def finish(decision, reason, instruction):
        return {**output, "decision": decision, "reason": reason,
                "next_owner": OWNERS[decision], "next_action": instruction}

    if not motion or incoming.get("repository") != motion["repository"]:
        return finish("Defer", "motion_or_repository_unverified", "Identify the motion and its repository.")
    packet = incoming.get("packet")
    if not isinstance(packet, list) or any(not isinstance(r, dict) for r in packet):
        return finish("Defer", "invalid_packet", "Supply the registered opening and conclusion.")
    selected = {}
    for role in ROLES:
        reg = [r for r in entries if r["role"] == role]
        sent = [r for r in packet if r.get("role") == role]
        if len(reg) != 1:
            return finish("Defer", f"{role}_registry_cardinality",
                          f"Identify one authoritative {role} and reconcile competing records.")
        if len(sent) != 1 or sent[0] != reg[0]:
            return finish("Defer", f"{role}_packet_mismatch",
                          f"Supply the matching registered {role} with its original source.")
        row = reg[0]
        selected[role] = row
        output["verified_evidence"].append({"role": role, "url": row["url"],
            "supporting_urls": row.get("supporting_urls", []), "record_sha256": fingerprint(row)})
    links = [r["url"] for r in selected.values()]
    if len(packet) != 2 or any(not isinstance(u, str) or not u for u in links) or links[0] == links[1]:
        return finish("Defer", "invalid_evidence_roles", "Provide two distinct source records of the required roles.")
    outcome = selected["result"].get("outcome")
    candidate = selected["opening"].get("candidate_commit")
    output.update(outcome=outcome, candidate_commit=candidate, candidate_basis=selected["opening"].get("candidate_basis"))
    if isinstance(outcome, str) and outcome in NEGATIVES:
        return finish("DoNotReuse", f"motion_{outcome}",
                      "Record this disposition and seek a separate successful motion or request a new vote.")
    if outcome != "passed":
        return finish("Defer", "unresolved_disposition", "Obtain the authoritative disposition of this motion.")
    if not sha(candidate):
        return finish("Defer", "candidate_unverified", "Establish the voted commit from the opening and repository.")
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        return finish("Defer", "two_observations_required", "Supply one older and one newer reference observation.")
    for s in observations:
        if not sha(s["registered_commit"]) or s["received_commit"] != s["registered_commit"]:
            return finish("Defer", s["side"] + "_observation_unverified",
                          f"Obtain or reconcile the {s['side']} reference observation with its archived pin.")
    outside = [s["side"] for s in observations if s["received_commit"] != candidate]
    if outside:
        return finish("Review", "outside_scope_" + "_and_".join(outside),
                      "Review the uncovered source or identify another applicable motion.")
    return finish("Reuse", "both_commits_match", "Attach this receipt to the handoff record.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use this trusted JSON registry instead of the packaged one.")
    cmds = parser.add_subparsers(dest="command", required=True)
    for command in ("lookup", "request"):
        sub = cmds.add_parser(command)
        for field in ("motion", "older", "newer"):
            sub.add_argument(field)
    for command in ("verify", "sql"):
        cmds.add_parser(command).add_argument("packet", type=Path)
    args = parser.parse_args()
    db = load(args.archive) if args.archive else registry()
    if args.command in {"lookup", "request"}:
        if args.motion not in db["motions"]:
            parser.error("Unknown motion. Available motions: " + ", ".join(db["motions"]))
        packet = request(db, args.motion, args.older, args.newer)
    else:
        packet = load(args.packet)
    if args.command == "sql":
        from sql_baseline import decide
        result = {"decision": decide(db, packet)}
    else:
        result = packet if args.command == "request" else verify(db, packet)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
