"""Retrieve only the raw public family mail needed for a requested reconstruction."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from time import sleep

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "data/family_sources.json"


def read_url_body(url):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit(
            "Install beautifulsoup4 to recover message text from public HTML."
        )
    for attempt in range(3):
        try:
            request = Request(
                url, headers={"User-Agent": "release-vote-handoffs research replay"}
            )
            with urlopen(request, timeout=40) as response:
                document = BeautifulSoup(response.read(), "html.parser")
            tag = document.select_one(".msgBody")
            if tag is None:
                raise ValueError(f"Archive body missing at {url}")
            return tag.get_text()
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            sleep(2**attempt)


def saved_bodies(project, root):
    for part in ("portable", "cohort", "prospective", "prospective2"):
        file = root / part / (project + ".json.gz")
        if file.is_file():
            family = json.loads(gzip.decompress(file.read_bytes()))
            return {m["url"]: m["body"] for m in family["messages"]}
    raise FileNotFoundError(
        f"No family capture for {project} under the supplied author-packet directory"
    )


def fingerprint(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def fill(project, family, output, author_packet):
    output.mkdir(parents=True, exist_ok=True)
    target = output / (project + ".json")
    expected = {m["url"]: m["body_sha256"] for m in family["messages"]}
    cached = {}
    if target.exists():
        cached = {
            m["url"]: m["body"] for m in json.loads(target.read_bytes())["messages"]
        }
    if author_packet is not None:
        cached.update(saved_bodies(project, author_packet))
    # Message order and frozen Git pins come from the public catalog, including misses.
    rows = []
    for m in family["messages"]:
        url = m["url"]
        body = cached.get(url)
        if body is None or fingerprint(body) != expected[url]:
            if author_packet is not None:
                raise ValueError(f"Author-packet body mismatch at {url}")
            body = read_url_body(url)
        if fingerprint(body) != expected[url]:
            raise ValueError(
                f"Archived message differs from its original body digest at {url}"
            )
        rows.append({k: v for k, v in dict(m, body=body).items() if k != "body_sha256"})
    enriched = dict(family, messages=rows)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(enriched, tmp, ensure_ascii=False)
    tmp_path.replace(target)
    print(
        f"{project}: verified {len(rows)} bodies and restored {len(family['tags'])} frozen pins"
    )


if __name__ == "__main__":
    catalog = json.loads(CATALOG.read_bytes())
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", choices=sorted(catalog))
    group.add_argument("--all", action="store_true")
    parser.add_argument("--out", type=Path, default=HERE / "local-captures")
    parser.add_argument(
        "--author-artifact",
        type=Path,
        help="Read the archived families from an existing local author packet",
    )
    args = parser.parse_args()
    for project in ([args.project] if args.project else sorted(catalog)):
        fill(project, catalog[project], args.out, args.author_artifact)
