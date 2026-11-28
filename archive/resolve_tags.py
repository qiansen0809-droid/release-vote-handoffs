"""Compare explicitly cited Git tags with the separately advertised commit.

Live refresh: python resolve_tags.py --refresh (git and internet required).
Offline replay: python resolve_tags.py
"""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import re
import subprocess

HERE = Path(__file__).resolve().parent


def observe(item):
    repo, tags = item
    # Restrict external requests to the public Apache mirror.
    if not re.fullmatch(r"apache/[a-z0-9.-]+",repo):
        raise ValueError(repo)
    filters = [f"refs/tags/{t}{s}" for t in sorted(tags) for s in ("","^{}")]
    command = ["git"]
    if os.name == "nt":
        command += ["-c","http.sslBackend=openssl"]
    command += ["-c","credential.helper=","ls-remote","--tags",
                f"https://github.com/{repo}.git",*filters]
    try:
        process = subprocess.run(command,capture_output=True,text=True,timeout=75)
        ok=not process.returncode
        lines=process.stdout.splitlines() if ok else []
    except (OSError,subprocess.TimeoutExpired):
        ok=False
        lines=[]
    observed={}
    for line in lines:
        oid,ref=line.split()
        if ref in filters and re.fullmatch(r"[0-9a-f]{40}",oid):
            observed[ref]=oid
    rows={}
    for tag in tags:
        ref=f"refs/tags/{tag}"
        target=observed.get(ref+"^{}",observed.get(ref))
        rows[tag]=dict(status="resolved" if target else "absent" if ok else "fetch_error",
                       target=target,ref_object=observed.get(ref),peeled=observed.get(ref+"^{}"))
    return repo,rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--refresh",action="store_true")
    args=parser.parse_args()
    rows=[json.loads(s) for s in (HERE/"results.jsonl").read_text(encoding="utf8").splitlines()]
    eligible=[r for r in rows if r["reference"] and
              len(r["advertised"]["tags"])==len(r["advertised"]["oids"])==1]
    cache=HERE/"git_snapshot.json"
    if args.refresh:
        by_repo=defaultdict(set)
        for row in eligible:
            repo,tag=row["advertised"]["tags"][0]
            by_repo[repo].add(tag)
        with ThreadPoolExecutor(max_workers=4) as pool:
            refs=dict(pool.map(observe,sorted(by_repo.items())))
        data=dict(captured_utc=datetime.now(timezone.utc).isoformat(),refs=refs)
        cache.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf8")
    data=json.loads(cache.read_text(encoding="utf8"))
    outcomes=[]
    for r in eligible:
        repo,tag=r["advertised"]["tags"][0]
        seen=data["refs"][repo][tag]
        expected=r["advertised"]["oids"][0]
        verdict=seen["status"]
        if verdict=="resolved":
            verdict="agrees" if seen["target"]==expected else "differs"
        outcomes.append(dict(month=r["month"],mid=r["mid"],opening_mid=r["reference_mid"],
                             repository=repo,tag=tag,expected=expected,observed=seen["target"],
                             outcome=verdict))
    report=dict(captured_utc=data["captured_utc"],
                counts=dict(Counter(r["outcome"] for r in outcomes)),
                held_out_counts=dict(Counter(r["outcome"] for r in outcomes if r["month"]>="2025-04")),
                observations=outcomes)
    (HERE/"git_audit.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(report["counts"],report["held_out_counts"])


if __name__=="__main__":
    main()
