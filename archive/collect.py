"""Collect one calendar year of the ASF Incubator's public general mailing list.

Usage: python collect.py. Uses only the Python standard library.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen
import gzip
import json
import re
import time

HERE = Path(__file__).resolve().parent
MONTHS = ("2024-12",) + tuple(f"2025-{i:02d}" for i in range(1,13))
URL = "https://lists.apache.org/api/mbox.lua?list=general@incubator.apache.org&date="


def fetch(month):
    url = URL + month
    for attempt in range(3):
        try:
            with urlopen(url, timeout=100) as reply:
                content = reply.read()
            break
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if not content.startswith(b"From "):
        raise ValueError(f"Unexpected content for {month}")
    stats_url = f"https://lists.apache.org/api/stats.lua?list=general&domain=incubator.apache.org&d={month}"
    for attempt in range(3):
        try:
            with urlopen(stats_url,timeout=60) as reply:
                metadata = json.load(reply)
            break
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    permalinks = {r["message-id"]:r["mid"] for r in metadata["emails"]}
    chunks = re.split(rb"(?m)^From [^\r\n]*\n", content)[1:]
    rows = []
    for raw in chunks:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        body = msg.get_body(preferencelist=("plain", "html"))
        if body:
            try:
                body = body.get_content()
            except (LookupError, UnicodeError):
                body = body.get_payload(decode=True).decode("utf-8", "replace")
        subject = " ".join(str(msg.get("subject", "")).split())
        stamp = parsedate_to_datetime(msg["date"])
        stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        ident = str(msg["message-id"]).strip()
        rows.append(dict(month=month, subject=subject, id=ident, mid=permalinks.get(ident),
                         when=stamp.astimezone(timezone.utc).isoformat(),
                         refs=re.findall(r"<[^<>\s]+>", " ".join(
                             str(msg.get(k, "")) for k in ("references", "in-reply-to"))),
                         body=body or ""))
    return dict(month=month, url=url, mbox_sha256=sha256(content).hexdigest(),
                bytes=len(content), messages=len(rows), stats_url=stats_url,
                matched_permalinks=sum(bool(r["mid"]) for r in rows)), rows


def main():
    with ThreadPoolExecutor(max_workers=3) as pool:
        all_months = list(pool.map(fetch, MONTHS))
    manifest = [item for item, _ in all_months]
    seen = {}
    for _, rows in all_months:
        for row in rows:
            seen.setdefault(row["id"], row)
    # Keep message content for release-vote discovery and linking. Store the
    # subject of every message for checking inclusion/exclusion without network.
    subjects = [{k: row[k] for k in ("month", "subject", "when", "id", "mid","refs")}
                for row in seen.values()]
    votes = [row for row in seen.values()
             if re.search(r"\b(votes?|results?|cancel(?:led|ed)?)\b",row["subject"],re.I)]
    for name, data in [("subjects",subjects), ("vote_messages",votes)]:
        data.sort(key=lambda row: (row["when"], row["id"]))
        records = "\n".join(json.dumps(row,ensure_ascii=False) for row in data)+"\n"
        (HERE / (name+".jsonl.gz")).write_bytes(gzip.compress(records.encode(),mtime=0))
    report = dict(months=manifest, unique_messages=len(seen), stored_vote_messages=len(votes))
    (HERE/"manifest.json").write_text(json.dumps(report,indent=2)+"\n", encoding="utf8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
