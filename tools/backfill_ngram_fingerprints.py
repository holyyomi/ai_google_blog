"""발행 이력에 6-gram 지문을 소급 적재한다 (2026-09-10 신설).

n-gram 중복 게이트(`news_quality_gate._max_ngram_jaccard`)는 과거 발행 글의
`content_ngram_fingerprint`와 비교한다. 그런데 이 필드는 게이트 신설 이후
발행분부터만 쌓이므로, 백필이 없으면 게이트가 한동안
`content_ngram_history_unavailable` 경고만 남기고 실질 차단을 못 한다.

라이브 블로그 피드에서 실제 발행 HTML을 받아 지문을 계산해 채운다.
피드는 발행된 본문 그대로라 게이트가 보는 것과 같은 텍스트다.

사용:
    PYTHONPATH=src python tools/backfill_ngram_fingerprints.py            # 미리보기
    PYTHONPATH=src python tools/backfill_ngram_fingerprints.py --apply    # 실제 기록
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from blogspot_automation.services.content_similarity_service import ngram_fingerprints

HISTORY_PATH = Path("data/publish_history.json")
FEED_URL = "https://holyyomiai.blogspot.com/feeds/posts/default"


def _fetch_feed(max_results: int = 500) -> dict[str, str]:
    """발행 URL -> 본문 HTML."""
    out: dict[str, str] = {}
    start = 1
    while True:
        response = requests.get(
            FEED_URL,
            params={"alt": "json", "max-results": 150, "start-index": start},
            timeout=60,
        )
        response.raise_for_status()
        entries = response.json().get("feed", {}).get("entry") or []
        if not entries:
            break
        for entry in entries:
            url = next(
                (l["href"] for l in entry.get("link", []) if l.get("rel") == "alternate"),
                "",
            )
            html = (entry.get("content") or {}).get("$t") or ""
            if url and html:
                out[url.split("?")[0]] = html
        if len(entries) < 150 or len(out) >= max_results:
            break
        start += 150
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 파일에 기록")
    args = parser.parse_args()

    records = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print("publish_history.json 형식이 예상과 다르다", file=sys.stderr)
        return 1

    print(f"이력 {len(records)}건 로드, 피드 수신 중...")
    feed = _fetch_feed()
    print(f"피드에서 발행 글 {len(feed)}편 확보")

    filled = skipped_existing = unmatched = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        url = str(record.get("url") or "").split("?")[0]
        if not url:
            continue
        if record.get("content_ngram_fingerprint"):
            skipped_existing += 1
            continue
        html = feed.get(url)
        if not html:
            unmatched += 1
            continue
        fingerprints = ngram_fingerprints(html)
        if not fingerprints:
            continue
        if args.apply:
            record["content_ngram_fingerprint"] = fingerprints
        filled += 1

    print(f"\n  채울 대상   : {filled}건")
    print(f"  이미 보유   : {skipped_existing}건")
    print(f"  피드에 없음 : {unmatched}건 (삭제됐거나 다른 블로그)")

    if not args.apply:
        print("\n미리보기였다. 실제로 기록하려면 --apply")
        return 0

    HISTORY_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n기록 완료 → {HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
