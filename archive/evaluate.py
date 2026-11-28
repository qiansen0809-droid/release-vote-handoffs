"""Replay the artifact offline. The reference uses RFC identities and explicit
archive links; the competing retrieval methods read only subjects."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote
import gzip
import json
import math
import re

HERE = Path(__file__).resolve().parent
VERSION = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)*)(?!\d)")
RC = re.compile(r"(?:\brc|release[ -]+candidate)\s*[-.#]?\s*(\d+)",re.I)
RESULT = re.compile(r"\[\s*(?:results?|cancel(?:led|ed|lation)?)\s*\]",re.I)
VOTE = re.compile(r"\[\s*vote\s*\]",re.I)
REPLY = re.compile(r"^\s*(?:re|fwd?|aw|回复)\s*[:：]",re.I)
THREAD_LINK = re.compile(r"https?://lists\.apache\.org/thread/([a-z0-9]{32})(?![a-z0-9])",re.I)
NOISE = set("release releases vote result results cancel canceled cancelled cancellation apache incubating incubator of for on as is ipmc the version v candidate".split())


def load(name):
    raw = gzip.decompress((HERE / (name+".jsonl.gz")).read_bytes()).decode()
    return [json.loads(line) for line in raw.splitlines()]


def key(subject):
    version = VERSION.search(subject)
    if not version:
        return None
    words = re.findall(r"[a-z]+", subject[:version.start()].lower())
    project = " ".join(w for w in words if w not in NOISE)
    rc = RC.search(subject)
    return project, version[1], int(rc[1]) if rc else None


def unquoted(body):
    head = re.split(r"(?im)^\s*>|^\s*on [^\n]* wrote:\s*$|^\s*-+\s*original message\s*-+",body,maxsplit=1)[0]
    return head


def rank_bm25(subject, candidates):
    docs = [Counter(re.findall(r"[a-z0-9]+",row["subject"].lower())) for row in candidates]
    query = set(re.findall(r"[a-z0-9]+",subject.lower()))
    count = len(docs)
    average = sum(sum(doc.values()) for doc in docs)/count
    df = Counter(word for doc in docs for word in doc)
    def score(doc):
        norm = 1.2 * (0.25 + 0.75 * sum(doc.values())/average)
        return sum(math.log(1+(count-df[word]+0.5)/(df[word]+0.5))*
                   (doc[word]*2.2)/(doc[word]+norm) for word in sorted(query) if word in doc)
    return max(zip(candidates,docs),key=lambda pair:(score(pair[1]),pair[0]["when"],pair[0]["id"]))[0]


def advertised(row):
    # An explicitly cited GitHub ref has stronger provenance than a constructed
    # tag name. Restrict OIDs to commit-shaped GitHub links or an explicit
    # commit/hash/revision line (including one continuation line).
    body=unquoted(row["body"])
    version=VERSION.search(row["subject"])[1]
    github = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/(releases/tag|commits?|tree)/([^\s<>/\]?#)]+)",re.I)
    tags, oids = set(), set()
    for repo, kind, value in github.findall(body):
        value = unquote(value.rstrip(".,;\"'"))
        if re.fullmatch(r"[a-fA-F0-9]{40}",value) and kind.lower() in ("tree","commit","commits"):
            oids.add(value.lower())
        elif kind.lower() in ("tree","commits","releases/tag") and version in value:
            tags.add((repo.lower(),value))
    for line in re.findall(r"(?im)^.*?\b(?:commit|revision|hash)\b[^\n]{0,150}(?:\n[^\n]{0,150})?",body):
        oids.update(h.lower() for h in re.findall(r"\b[a-fA-F0-9]{40}\b",line))
    return dict(tags=sorted(tags),oids=sorted(oids))


def run():
    subjects=load("subjects")
    votes=load("vote_messages")
    by_id={r["id"]:r for r in subjects}
    by_mid={r["mid"]:r for r in subjects if r["mid"]}
    openings=[r for r in votes if VOTE.search(r["subject"]) and not RESULT.search(r["subject"])
              and VERSION.search(r["subject"]) and not REPLY.search(r["subject"])]
    opening_ids={r["id"] for r in openings}
    queries=[r for r in votes if r["month"].startswith("2025") and RESULT.search(r["subject"])
             and VERSION.search(r["subject"]) and not REPLY.search(r["subject"])]
    index={r["id"]:r for r in openings}

    @lru_cache(maxsize=None)
    def roots(ident):
        stack=[ident]
        reached=set()
        seen=set()
        while stack:
            ident=stack.pop()
            if ident in seen:
                continue
            seen.add(ident)
            if ident in opening_ids:
                reached.add(ident)
            elif ident in by_id:
                stack.extend(by_id[ident]["refs"])
        return reached

    rows=[]
    for q in queries:
        cand=[r for r in openings if r["when"] < q["when"]]
        ancestry=set().union(*(roots(i) for i in q["refs"]))
        urls=THREAD_LINK.findall(unquoted(q["body"]))
        explicit=set().union(*(roots(by_mid[u]["id"]) for u in urls if u in by_mid))
        possible=(ancestry|explicit)&{r["id"] for r in cand}
        gold=next(iter(possible)) if len(possible)==1 else None
        matching=[r for r in cand if key(q["subject"])==key(r["subject"])]
        model={"latest":cand[-1]["id"] if cand else None,
               "bm25":rank_bm25(q["subject"],cand)["id"] if cand else None,
               "key":matching[0]["id"] if len(matching)==1 else None}
        rows.append(dict(id=q["id"],mid=q["mid"],month=q["month"],subject=q["subject"],
                         key=key(q["subject"]),candidate_count=len(cand),
                         query_marker=RESULT.search(q["subject"])[0],reference=gold,
                         reference_mid=index[gold]["mid"] if gold else None,
                         header_roots=sorted(ancestry),body_roots=sorted(explicit),
                         cited_thread_ids=urls,predictions=model,
                         advertised=advertised(index[gold]) if gold else None))
    return openings,rows


def summarize(rows):
    ref=[r for r in rows if r["reference"]]
    # Reporting only. Raw project words are kept unchanged in retrieval.
    family={"fury":"fory","seata go":"seata","fluss shaded":"fluss"}
    product_names=sorted(set(r["key"][0] for r in rows))
    return dict(queries=len(rows),reference_supported=len(ref),
                ambiguous=sum(len(set(r["header_roots"]+r["body_roots"]))>1 for r in rows),
                product_names=product_names,
                project_families=sorted(set(family.get(p,p) for p in product_names)),
                markers=dict(Counter(r["query_marker"].lower() for r in rows)),
                source_both=sum(len(r["advertised"]["tags"])==len(r["advertised"]["oids"])==1 for r in ref),
                retrieval={m:dict(Counter("correct" if r["predictions"][m]==r["reference"]
                             else "wrong" if r["predictions"][m] else "defer" for r in ref))
                           for m in ("latest","bm25","key")})


def main():
    openings,rows=run()
    (HERE/"results.jsonl").write_text("".join(json.dumps(r,ensure_ascii=True)+"\n" for r in rows),encoding="utf8")
    out={"opening_pool":len(openings),"all":summarize(rows),
         "development":summarize([r for r in rows if r["month"]<"2025-04"]),
         "evaluation":summarize([r for r in rows if r["month"]>="2025-04"])}
    (HERE/"summary.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
    print(json.dumps(out,indent=2))


if __name__=="__main__":
    main()
