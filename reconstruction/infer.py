"""Build typed, source-linked release-vote records from one mail/Git capture.

No inspection labels, known winners, project exceptions or network calls are used.
"""
import argparse
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

RC = re.compile(r"(?<![a-z])(?:rc|(?:release[ _-]+)?candidate)[\s.#:_-]*(\d+)\b", re.I)
VOTE = re.compile(r"\[\s*votes?\s*\]", re.I)
RESULT = re.compile(r"\[\s*(?:results?|cancel(?:led|ed)?|withdrawn|closed)\s*\]", re.I)
PREFIX = re.compile(r"^\s*(?:subject|re|aw|fw|fwd)\s*:\s*", re.I)
RESPONSE = re.compile(r"^\s*(?:re|aw|fw|fwd)\s*:", re.I)
CALL = re.compile(r"\b(?:call(?:ing)?\s+(?:for\s+)?(?:a|the|this)?\s*vote|please\b.{0,65}?\bvote\b|"
                  r"(?:the|this)\s+vote\s+(?:is|will|remains?)\s+(?:open|run|remain)|"
                  r"(?:vote|tag|commit)\s+(?:to\s+be\s+voted|on\s+(?:releasing|accepting))|"
                  r"propos(?:e|ing)\s+(?:the\s+)?release|vote\s+for\s+(?:a|the|this)\s+release)\b", re.I)
LINK = re.compile(r"https?://github\.com/([^/ \t<>]+)/([^/ \t<>]+)/(?:releases/tag|tree)/([^\s<>()\[\]?#]+)", re.I)
TYPED_OID = re.compile(
    r"\b(?:(?:its|the|git|release|source|candidate)\s+)?"
    r"(?:commit(?:\s+(?:hash|id|oid|SHA(?:-?1)?))?|git\s+(?:reference|hash|revision)|"
    r"(?:its|release|candidate|source)\s+hash)"
    r"(?:\s+(?:for\s+(?:this|the)\s+(?:release|candidate)|(?:to\s+be\s+)?voted\s+(?:on|upon)))?"
    r"\s*(?:(?:is|at|was)\s*|[:=]\s*|\s+)(?:[:=]\s*)?([a-f0-9]{40})\b", re.I)
HEX40 = re.compile(r"\b[a-f0-9]{40}\b", re.I)
TARGET = r"(?:the\s+|this\s+|our\s+)?(?:vote|voting|ballot|thread|rc\s*#?\d*|candidate|release)"
PASS = re.compile(
    r"\b(?:(?:this\s+|the\s+)?(?:vote|voting|ballot|release|proposal|rc\s*#?\d+)"
    r"(?:\s+(?:for|to\s+release)\s+[\w. -]{1,85}?)?\s+"
    r"(?:(?:has|was|is|has\s+been|has\s+concluded\s+and)\s+)?"
    r"(?:passed|passes|approved|successful)\b|"
    r"(?:we\s+(?:have\s+)?(?:unanimously\s+)?approved\s+(?:this|the)\s+release)|"
    r"it\s+pass(?:es|ed)\s+with\b)", re.I)
NEG = re.compile(
    r"\b(?:"
    r"(?:the\s+|this\s+)?(?:vote|voting|ballot|proposal|rc\s*#?\d+)\s+"
    r"(?:(?:was|has\s+been|has|is)\s+)?(?:failed|withdrawn|cancelled|canceled|did\s+not\s+pass)|"
    r"(?:i|we|let['’]s)\s+(?:(?:have|are|will)\s+)?(?:cancel(?:led|ed|ling|ing)?|withdraw(?:n|ing)?|sink|abandon(?:ing)?)\s+"
    +TARGET+r"|(?:cancel|withdraw)\s+(?:this|the)\s+(?:vote|thread|ballot)|"
    r"(?:rc\s*#?\d+|this\s+(?:vote|thread))\s+is\s+closed\s+and\s+.{0,50}?\b(?:start|open|initiate)\s+"
    r"(?:a\s+new|the\s+next|another)\s+(?:release\s+)?vote)", re.I)
HYPOTHETICAL = re.compile(r"\b(?:if|unless|assuming|whether|when|could|would|might|will|may|hope|expect|"
                          r"believe|think|hopeful|suppose|not|never|cannot|how\s+to)\b", re.I)
REQUIRED = ("current_two_tag", "historical_destination")


def read_capture(path):
    path = Path(path)
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(raw)


def unquoted(body):
    kept = []
    for line in body.splitlines():
        s = line.strip()
        if (s.startswith(">") or re.match(r"^On .{0,240}wrote:\s*$", s)
                or re.match(r"^-+\s*(?:Original Message|Forwarded message)\s*-+$", s, re.I)
                or s == "--"):
            break
        kept.append(s)
    return " ".join(" ".join(kept).split())


def candidate_numbers(s):
    return {int(n) for n in RC.findall(s)}


def has_version(s, version):
    return bool(re.search(r"(?<![\d.])"+re.escape(version)+r"(?!\d|\.\d)", s))


def normalized_subject(subject):
    s = subject
    while PREFIX.match(s):
        s = PREFIX.sub("", s, count=1)
    return " ".join(re.findall(r"[a-z0-9]+", RESULT.sub("", VOTE.sub("", s)).casefold()))


def witness(m, value, quote):
    return {"value":value, "url":m["url"], "date":m["date"], "quote":quote}


def source_claims(family, m):
    top = unquoted(m["body"])
    tags = []
    foreign = []
    for link in LINK.finditer(top):
        repo = (link[1]+"/"+link[2]).casefold()
        name = unquote(link[3]).rstrip("/.,;:'\"*")
        if not has_version(name,family["version"]) or not candidate_numbers(name):
            continue
        dest = tags if repo == family["repository"].casefold() else foreign
        dest.append(witness(m,name,link[0]))
    # A hash must designate the voted revision. Other full hexadecimal tokens
    # (a key fingerprint, an issue-fixing commit) remain outside this proof.
    typed = [witness(m,h[1].lower(),h[0]) for h in TYPED_OID.finditer(top)]
    any_hash = [witness(m,h[0].lower(),h[0]) for h in HEX40.finditer(top)]
    return tags, foreign, typed, any_hash


def signed_claims(m, rc):
    top = unquoted(m["body"])
    claims = []
    for value, pat in (("pass",PASS),("negative",NEG)):
        for hit in pat.finditer(top):
            # Periods in release numbers are not sentence boundaries.
            before = re.split(r"(?<=[.!?;])\s+",top[:hit.start()])[-1]
            after = top[hit.end():]
            if (HYPOTHETICAL.search(before) or re.match(r"\s+(?:if|when|unless)\b",after,re.I)
                    or re.match(r"\s*[?]",after) or "?" in hit[0]):
                continue
            # A statement about an explicitly different RC cannot close this motion.
            if candidate_numbers(hit[0]) - {rc} or candidate_numbers(before) - {rc}:
                continue
            if hit[0].casefold().startswith("it pass") and not re.search(
                    r"(?:vote|voting|ballot).{0,90}\b(?:closed|ended|concluded)\b.{0,20}$",
                    top[max(0,hit.start()-140):hit.start()],re.I):
                continue
            claims.append(witness(m,value,hit[0]))
    return claims


def observation(family, name):
    obs = family.get("tag_observation", {})
    rec = family["tags"].get(name,{})
    # Explicit provenance on both the observation and URL must match the named repo.
    canonical = "/"+family["repository"].strip("/").casefold()
    declared = obs.get("queried") or family.get("tag_repository")
    repo_match = False
    if declared:
        parsed = urlsplit(declared)
        repo_match = (parsed.hostname == "github.com" and
                      parsed.path.rstrip("/").removesuffix(".git").casefold() == canonical)
    locator = rec.get("url") or ""
    parsed = urlsplit(locator)
    path = unquote(parsed.path)
    segments = path.split("/", 4)
    ref_match = (len(segments)==5 and ("/"+segments[1]+"/"+segments[2]).casefold()==canonical and
                 segments[3]=="tree" and segments[4]==name)
    valid = (repo_match and parsed.hostname == "github.com" and ref_match and obs.get("observed_utc") and
             HEX40.fullmatch(rec.get("commit") or "") is not None)
    return {"name":name, "commit":rec["commit"].lower() if valid else None,
            "url":locator or None, "observed_at":obs.get("observed_utc"),
            "reported_commit":rec.get("commit"), "repository_verified":bool(valid)}


def decide(row, scope, variant):
    def answer(action,reason,*requests):
        return {"action":action,"reason":reason,"requests":list(requests)}
    if row["identity_issue"]:
        return answer("Defer",row["identity_issue"],"reconcile opening and candidate designation")
    # The matched coupled control sees precisely the same parsed witnesses but
    # gates all downstream evidence on a resolved current candidate object.
    candidate = row["candidate_observation"]["commit"]
    final = row["final_observation"]["commit"]
    shas = {w["value"] for w in row["dated_commits"]}
    if variant=="coupled" and (not candidate or len(shas)>1 or (shas and shas!={candidate})):
        return answer("Defer","current source gate blocked motion reconstruction","reconcile candidate pin")
    if row["outcome"]=="negative":
        return answer("DoNotReuse","documented negative outcome")
    if row["outcome"]!="pass":
        task="reconcile closing claims" if row["outcome"]=="conflict" else "obtain explicit collective conclusion"
        return answer("Defer",row["outcome"]+" outcome",task)
    if len(shas)>1:
        return answer("Defer","competing candidate commit designations","reconcile dated source claims")
    if scope=="historical_destination":
        source = next(iter(shas),None)
        missing = "obtain dated candidate commit designation"
    else:
        source = candidate
        missing = "obtain current candidate tag pin"
        if source and shas and shas!={source}:
            return answer("Defer","dated commit disagrees with candidate tag","resolve disputed source binding")
    gaps = ([missing] if not source else [])+([] if final else ["obtain final tag pin"])
    if gaps:
        return answer("Defer","required source witness missing",*gaps)
    if source!=final:
        return answer("Review","voted source differs from final observation")
    return answer("Reuse","vote and required source comparison established")


def source_state(row):
    values={w["value"] for w in row["dated_commits"]}
    current=row["candidate_observation"]["commit"]
    if len(values)>1:
        return "conflicting historical claims"
    if current and values and current not in values:
        return "dated and current claims disagree"
    if current and values:
        return "tag corroborates dated designation"
    if current:
        return "current tag only; continuity assumed"
    if values:
        return "dated designation only"
    return "unresolved"


def selected_sources(row, task, action):
    if action=="Defer":
        return []
    # The complete candidate set stays in the record to audit uniqueness and
    # disagreement. Return one source per required supporting role for reuse.
    support=[{"role":"opening","url":row["opening"]},
             {"role":"conclusion","url":row["closing_witnesses"][0]["url"]}]
    if action=="DoNotReuse":
        return support
    if task=="historical_destination":
        support.append(dict(role="dated_candidate_commit",**row["dated_commits"][0]))
    else:
        support.append(dict(role="current_candidate_pin",**row["candidate_observation"]))
        if row["dated_commits"]:
            support.append(dict(role="dated_candidate_consistency",**row["dated_commits"][0]))
    support.append(dict(role="final_pin",**row["final_observation"]))
    return support


def family_report(family, variant="typed"):
    if variant not in ("typed","coupled","untyped"):
        raise ValueError(variant)
    groups = {}
    for m in family["messages"]:
        s = m["subject"]
        rcs = candidate_numbers(s)
        if has_version(s,family["version"]) and (VOTE.search(s) or RESULT.search(s)) and len(rcs)==1:
            groups.setdefault(next(iter(rcs)),[]).append(m)
    motions = []
    for rc,messages in sorted(groups.items()):
        roots = []
        for msg in messages:
            subj = re.sub(r"^\s*subject:\s*","",msg["subject"],flags=re.I)
            if RESPONSE.match(subj) or RESULT.search(subj):
                continue
            if CALL.search(unquoted(msg["body"])):
                roots.append(msg)
        row = {"rc":rc,"opening_candidates":[m["url"] for m in roots],
               "opening":None,"identity_issue":None,"candidate_tags":[],"foreign_tags":[],
               "dated_commits":[],"candidate_tag":None,"closing_witnesses":[],"outcome":"unknown"}
        if len(roots)!=1:
            row["identity_issue"]="missing opening" if not roots else "competing openings"
        else:
            root = roots[0]
            row["opening"]=root["url"]
            tags,foreign,typed,untyped=source_claims(family,root)
            row.update(candidate_tags=tags,foreign_tags=foreign,dated_commits=untyped if variant=="untyped" else typed)
            names={w["value"] for w in tags}
            if len(names)==1:
                row["candidate_tag"]=next(iter(names))
            if foreign or len(names)!=1 or candidate_numbers(row["candidate_tag"] or "")!={rc}:
                row["identity_issue"]="foreign, missing or conflicting candidate designation"
            opening_order=next(i for i,m in enumerate(messages) if m is root)
            for order,m in enumerate(messages):
                if (m["url"]!=root["url"] and m["sender"].strip() and
                    m["sender"].strip().casefold()==root["sender"].strip().casefold() and
                    (m["date"],order)>(root["date"],opening_order) and
                    normalized_subject(m["subject"])==normalized_subject(root["subject"])):
                    row["closing_witnesses"].extend(signed_claims(m,rc))
            signs={w["value"] for w in row["closing_witnesses"]}
            row["outcome"]=next(iter(signs)) if len(signs)==1 else ("conflict" if signs else "unknown")
        row["candidate_observation"]=observation(family,row["candidate_tag"])
        row["final_observation"]=observation(family,family["final_tag"])
        row["source_state"]=source_state(row)
        for task in REQUIRED:
            row[task]=decide(row,task,variant)
            row[task]["support"]=selected_sources(row,task,row[task]["action"])
        motions.append(row)
    return {"project":family["project"],"repository":family["repository"],"release":family["version"],
            "variant":variant,"motions":motions}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--variant",choices=("typed","coupled","untyped"),default="typed")
    args=parser.parse_args()
    print(json.dumps(family_report(read_capture(args.snapshot),args.variant),indent=2))

