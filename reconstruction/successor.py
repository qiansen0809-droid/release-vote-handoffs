"""Recover source-continuity records from a repository-scoped mail and Git capture.

An opening anchors a motion even when it names no source. Positive decisions
require a separate, repository-bound designation for the requested time scope.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from urllib.parse import unquote

import infer
from intent import is_enacted


BALLOT_OPEN = re.compile(r"\b(?:vote|ballot)\s+(?:(?:is|remains)\s+)?open\s+for\s+\d+\s*(?:h|hour|day)", re.I)
AFFIRMATIVE_NEGATIVE = re.compile(
    r"\b(?:I\s+am|we\s+are|I['’]m|we['’]re)\s+(?:cancell?ing|withdrawing|abandoning)\s+"
    + infer.TARGET + r"\b", re.I)
EXPLICIT_RESULT = re.compile(r"\b(?:vote|ballot)\s+(?:result|outcome)\s*[:=]\s*(passed|approved|failed|withdrawn|cancelled|canceled)\b", re.I)
TAG_CONTEXT = re.compile(r"\b(?:release candidate tag|candidate tag|source(?: code)? tag|git tag|tag(?:ged)? in git(?:hub)?)\b", re.I)
OID = r"([a-fA-F0-9]{40})\b"
GIT_COMMIT_URL = re.compile(
    r"https?://github\.com/([^/\s<>]+)/([^/\s<>]+)/(?:commit|tree)/" + OID + r"(?![/\w])", re.I)
GIT_LABEL = re.compile(r"\bgit\s+(?:commit\s+)?sha(?:-?1)?\s*(?:is\s*|[:=]\s*)?" + OID, re.I)
SOURCE_LABEL = re.compile(
    r"(?:\b(?:release|candidate|source)(?:\s+(?:code|candidate))?\s+(?:commit|revision|source)"
    r"|\bcommit\s+(?:to\s+be\s+voted(?:\s+(?:on|upon))?|for\s+(?:this|the)\s+(?:release|candidate))"
    r"|\b(?:source\s+code|git\s+commit))\s*(?:id|hash|sha|sha1|link|url)?\s*(?:is|at)?\s*[:=(\[<\-]*\s*$", re.I)
NON_SOURCE = re.compile(r"\b(?:cherry[- ]?pick\w*|fix(?:ed|ing|es)?|bug|issue|pull request|fingerprint|checksum|signing key)\b", re.I)
LINK_INDEX = re.compile(r"\[(\d+)\]\s*$")
EXTRA_QUOTE = re.compile(r"^(?:.{1,180}(?:writes|wrote)\s*:|-----\s*(?:Original Message|Forwarded message))$", re.I)


def body_text(message):
    """Strip archive quote boundaries before the inherited wrapped-text fold."""
    lines = []
    for line in message["body"].splitlines():
        if EXTRA_QUOTE.match(line.strip()):
            break
        lines.append(line)
    return infer.unquoted("\n".join(lines))


def local_prefix(text, offset):
    return re.split(r"(?<=[.!?;])\s+|\s+\*\s+", text[:offset])[-1][-210:]


def opening_groups(family):
    groups = defaultdict(list)
    for index, message in enumerate(family["messages"]):
        s = re.sub(r"^\s*subject:\s*", "", message["subject"], flags=re.I)
        rcs = infer.candidate_numbers(s)
        if (not infer.has_version(s, family["version"]) or not infer.VOTE.search(s) or
                infer.RESULT.search(s) or infer.RESPONSE.match(s) or len(rcs) > 1):
            continue
        body = body_text(message)
        if not (infer.CALL.search(body) or BALLOT_OPEN.search(body)):
            continue
        rc = next(iter(rcs), None)
        # Numbered rounds share an identity. An unnumbered motion is local to its
        # subject and opening; no round number is inferred from release order.
        key = (rc, None if rc is not None else infer.normalized_subject(s))
        groups[key].append((index, message))
    return groups


def source_designations(family, opening, rc):
    top = body_text(opening)
    repository = family["repository"].casefold()
    version = family["version"]
    tags, commits, foreign, incompatible = [], [], [], []

    def append(bucket, value, quote, basis):
        witness = dict(infer.witness(opening, value, quote), basis=basis)
        if witness not in bucket:
            bucket.append(witness)

    for h in infer.LINK.finditer(top):
        name = unquote(h[3]).rstrip("/.,;:'\"*")
        rcs = infer.candidate_numbers(name)
        # A final tag or a bare suffix is not intrinsically a candidate.
        # A numeric suffix is admitted only alongside an explicit candidate/tag
        # designation naming this exact ref in the author's own opening.
        numeric = re.search(re.escape(version) + r"[-_](\d+)$", name, re.I)
        preceding = local_prefix(top, h.start())
        explicit = any(name in preceding[label.end():] for label in TAG_CONTEXT.finditer(preceding))
        if not rcs and not (numeric and explicit):
            continue
        if not rcs:
            rcs = {int(numeric[1])}
        app_repo = (h[1] + "/" + h[2]).casefold()
        if app_repo != repository:
            if infer.has_version(name, version) or explicit:
                append(foreign, name, h[0], "foreign candidate ref")
            continue
        if not infer.has_version(name, version) or len(rcs) != 1 or (rc is not None and rcs != {rc}):
            append(incompatible, name, h[0], "candidate ref disagrees with opening")
            continue
        append(tags, name, h[0], "opening ref link")

    # Exact syntactic tag--object edges and explicit Git labels, never an
    # arbitrary forty-digit string, may identify the historical source object.
    names = {w["value"] for w in tags}
    for name in sorted(names):
        adjacent = re.compile(r"(?<![\w/-])" + re.escape(name) + r"[\"'`]?\s*\(\s*" + OID + r"\s*\)")
        for h in adjacent.finditer(top):
            if TAG_CONTEXT.search(local_prefix(top, h.start())):
                append(commits, h[1].lower(), h[0], "named source tag with parenthesized object")
    for pattern in (infer.TYPED_OID, GIT_LABEL):
        for h in pattern.finditer(top):
            left = local_prefix(top, h.start())
            if not NON_SOURCE.search(left[-62:]) and names:
                append(commits, h[1].lower(), h[0], "labeled object in repository-bound opening")
    for h in GIT_COMMIT_URL.finditer(top):
        left = local_prefix(top, h.start())
        pointer = LINK_INDEX.search(left)
        declared = bool(SOURCE_LABEL.search(left) and not NON_SOURCE.search(left[-90:]))
        if pointer and not declared:
            marker = re.escape("[" + pointer[1] + "]")
            declared = any(SOURCE_LABEL.search(local_prefix(top, m.start())) and
                           not NON_SOURCE.search(local_prefix(top, m.start())[-90:])
                           for m in re.finditer(marker, top[:h.start()], re.I))
        if not declared:
            continue
        if (h[1] + "/" + h[2]).casefold() != repository:
            append(foreign, h[3].lower(), h[0], "foreign designated commit")
        else:
            append(commits, h[3].lower(), h[0], "repository-bound source commit link")
    return tags, commits, foreign, incompatible


def closures(family, index, opening, rc):
    accepted, excluded = [], []
    sender = opening["sender"].strip().casefold()
    subject = infer.normalized_subject(opening["subject"])
    for i, message in enumerate(family["messages"]):
        if (not sender or message["sender"].strip().casefold() != sender or
                message["url"] == opening["url"] or (message["date"], i) <= (opening["date"], index) or
                infer.normalized_subject(message["subject"]) != subject):
            continue
        text = body_text(message)
        candidates = infer.signed_claims(dict(message, body=text), rc)
        for pat in (AFFIRMATIVE_NEGATIVE, EXPLICIT_RESULT):
            for hit in pat.finditer(text):
                left = local_prefix(text, hit.start())
                if (infer.HYPOTHETICAL.search(left) or infer.candidate_numbers(hit[0]) - {rc}
                        or infer.candidate_numbers(left) - {rc}):
                    continue
                value = "pass" if pat is EXPLICIT_RESULT and hit[1].casefold() in ("passed", "approved") else "negative"
                candidates.append(infer.witness(message, value, hit[0]))
        for witness in candidates:
            bucket = accepted if is_enacted(witness, text) else excluded
            if witness not in bucket:
                bucket.append(witness)
    return accepted, excluded


def family_report(family):
    motions = []
    for (rc, _), roots in opening_groups(family).items():
        row = dict(rc=rc, opening_candidates=[m["url"] for _, m in roots], opening=None, identity_issue=None,
                   candidate_tags=[], foreign_tags=[], incompatible_tags=[], dated_commits=[], candidate_tag=None,
                   closing_witnesses=[], excluded_closing_witnesses=[], outcome="unknown")
        if len(roots) != 1:
            row["identity_issue"] = "competing openings for motion identity"
        else:
            index, opening = roots[0]
            row["opening"] = opening["url"]
            row["opening_witness"] = infer.witness(opening, "open", opening["subject"])
            tags, commits, foreign, incompatible = source_designations(family, opening, rc)
            names = {w["value"] for w in tags}
            row.update(candidate_tags=tags, foreign_tags=foreign, incompatible_tags=incompatible, dated_commits=commits)
            if foreign or incompatible or len(names) > 1:
                row["identity_issue"] = "conflicting candidate or repository designations"
            elif names:
                row["candidate_tag"] = next(iter(names))
            row["closing_witnesses"], row["excluded_closing_witnesses"] = closures(family, index, opening, rc)
            signs = {w["value"] for w in row["closing_witnesses"]}
            row["outcome"] = next(iter(signs)) if len(signs) == 1 else ("conflict" if signs else "unknown")
        row["candidate_observation"] = infer.observation(family, row["candidate_tag"])
        row["final_observation"] = infer.observation(family, family["final_tag"])
        row["source_state"] = infer.source_state(row)
        for scope in infer.REQUIRED:
            action = infer.decide(row, scope, "typed")
            action["support"] = infer.selected_sources(row, scope, action["action"])
            if action["support"]:
                # Preserve the words and date of the enrolled closing, including
                # negative dispositions that do not depend on Git observations.
                action["support"][0].update(row["opening_witness"])
                action["support"][1].update(row["closing_witnesses"][0])
            row[scope] = action
        motions.append(row)
    return dict(project=family["project"], repository=family["repository"], release=family["version"],
                variant="successor", motions=motions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    print(json.dumps(family_report(infer.read_capture(args.snapshot)), indent=2))
