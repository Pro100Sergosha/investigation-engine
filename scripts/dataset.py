"""HotpotQA dev (distractor) -> deduplicated `ParsedDoc` JSONL shards and gold questions in S3."""

import argparse
import hashlib
import json
import urllib.request
from collections import Counter
from dataclasses import asdict

import boto3

from engine.index import content_hash
from engine.models import ParsedDoc

# Official URL from the HotpotQA README first; the Wayback Machine copy is the fallback because
# the CMU host is sometimes unreachable. Both serve the same bytes, checked by SHA256 below.
URLS = [
    "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
    "https://web.archive.org/web/20260310132809id_/"
    "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
]
SHA256 = "4e9ecb5c8d3b719f624d66b60f8d56bf227f03914f5f0753d6fa1b359d7104ea"
SHARD_SIZE = 500  # ADR 0018: ~500 records per shard keeps one ingest run well under 15 min
TARGET = 50_000  # PLAN: the corpus must have at least 50k unique documents


def paragraphs(rows: list[dict]) -> list[ParsedDoc]:
    """Every context paragraph of every question as a `ParsedDoc`, in file order.

    Sentences after the first carry their own leading space (" The film ..."), and the few that
    do not are splitter cuts inside a sentence ('"Lucifer', '", which ...'). So "".join rebuilds
    the original paragraph; " ".join would put spaces inside quotes and URLs.
    """
    docs = []
    for row in rows:
        for title, sentences in row["context"]:
            docs.append(
                ParsedDoc(
                    source=f"hotpotqa:{title}",
                    title=title,
                    doc_type="jsonl",
                    text="".join(sentences).strip(),
                    metadata={"dataset": "hotpotqa"},
                )
            )
    return docs


def dedup(docs: list[ParsedDoc]) -> tuple[list[ParsedDoc], dict]:
    """Keep the first document per source and per content hash; count what was dropped.

    The hash is `content_hash`, the one `ingest` uses, so both sides agree on what a duplicate
    is. The source must be unique too, because an update replaces the document with that
    source: a second text under the same title would silently overwrite the first.
    """
    kept = []
    seen_sources: dict[str, str] = {}  # source -> hash of the text kept for it
    seen_hashes: set[str] = set()
    counts = {"exact_duplicates": 0, "title_conflicts": 0, "empty": 0}
    for doc in docs:
        if not doc.text:
            counts["empty"] += 1
            continue
        digest = content_hash(doc.text)
        if doc.source in seen_sources:
            if seen_sources[doc.source] == digest:
                counts["exact_duplicates"] += 1
            else:
                counts["title_conflicts"] += 1
            continue
        if digest in seen_hashes:
            # Same text under another title: ingest would drop it as a duplicate anyway.
            counts["exact_duplicates"] += 1
            continue
        seen_sources[doc.source] = digest
        seen_hashes.add(digest)
        kept.append(doc)
    return kept, counts


def shard(docs: list[ParsedDoc], size: int = SHARD_SIZE) -> list[str]:
    """Split into JSONL texts of at most `size` documents, one `ParsedDoc` per line."""
    lines = [json.dumps(asdict(doc), ensure_ascii=False) for doc in docs]
    return ["\n".join(lines[i : i + size]) + "\n" for i in range(0, len(lines), size)]


def questions(rows: list[dict]) -> list[dict]:
    """Gold labels for evaluation: supporting titles as document sources, deduped, in order."""
    out = []
    for row in rows:
        titles = dict.fromkeys(title for title, _ in row["supporting_facts"])
        out.append(
            {
                "_id": row["_id"],
                "question": row["question"],
                "answer": row["answer"],
                "type": row["type"],
                "level": row["level"],
                "supporting_titles": [f"hotpotqa:{title}" for title in titles],
            }
        )
    return out


def stats(rows: list[dict], seen: int, unique: int, counts: dict) -> dict:
    return {
        "questions": len(rows),
        "paragraphs_seen": seen,
        "unique_documents": unique,
        **counts,
        "by_type": dict(Counter(row["type"] for row in rows)),
        "meets_50k": unique >= TARGET,
    }


def _download() -> bytes:
    errors = []
    for url in URLS:
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
        except OSError as e:  # URLError and timeouts are OSError subclasses
            errors.append(f"{url}: {e}")
            continue
        if hashlib.sha256(data).hexdigest() != SHA256:
            errors.append(f"{url}: unexpected SHA256, file changed or truncated")
            continue
        print(f"downloaded {len(data):,} bytes from {url}")
        return data
    raise SystemExit("download failed:\n" + "\n".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print stats, upload nothing")
    args = parser.parse_args()

    rows = json.loads(_download())
    docs = paragraphs(rows)
    unique, counts = dedup(docs)
    summary = stats(rows, len(docs), len(unique), counts)
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        return

    s3 = boto3.client("s3")
    # Labels first: everything under jobs/ is inert, everything under bulk/ starts ingestion.
    s3.put_object(
        Bucket=args.bucket,
        Key="jobs/dataset/stats.json",
        Body=json.dumps(summary, indent=2).encode(),
    )
    gold = "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions(rows))
    s3.put_object(Bucket=args.bucket, Key="jobs/dataset/questions.jsonl", Body=gold.encode())
    shards = shard(unique)
    for i, text in enumerate(shards):
        key = f"bulk/hotpotqa/shard-{i:05d}.jsonl"
        s3.put_object(Bucket=args.bucket, Key=key, Body=text.encode())
        print(f"uploaded s3://{args.bucket}/{key}")
    print(f"{len(shards)} shards, {len(unique)} documents")


if __name__ == "__main__":
    main()
