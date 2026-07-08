"""발행 이력 원장 병합 — 어느 브랜치의 런이든 main 원장에 안전하게 합류시킨다.

배경(2026-07-08 구조 감사, 로드맵 3): 기존 persist 스텝은 main 브랜치 런에서만
원장을 커밋했다(`git push HEAD:main`이 브랜치 전체를 밀어버리기 때문에 조건이
필요했음). 그 결과 feature 브랜치에서 실행된 발행(수동 리허설 포함)의 기록이
main 원장에 남지 않았고, dedup·엔티티 쿨다운이 "이미 발행했는지"를 몰라
같은 주제가 라이브에 연속으로 쌓였다(네이버 AI 3연속 사건의 원인 b).

이 스크립트는 "원장 파일만" 병합한다:
  merged = main의 원장(base) ∪ 이번 런의 원장(incoming)
- 중복 판정: 레코드의 정규화 JSON 해시 (완전 동일 레코드만 중복으로 접음 —
  같은 주제의 다른 시도는 각각 의미 있는 기록이므로 보존).
- 순서: run_at(없으면 date) 기준 시간순 안정 정렬 — 원장은 append-only 시간순.
- base가 병합 사이에 새 레코드를 얻었어도 유실 없음 (합집합이므로).

워크플로우에서의 사용(브랜치 무관):
  cp data/publish_history.json /tmp/run_ledger.json   # 이번 런 결과 보존
  git fetch origin main && git checkout -f -B ledger-merge origin/main
  python scripts/merge_publish_history.py \
      --base data/publish_history.json --incoming /tmp/run_ledger.json \
      --out data/publish_history.json
  # 이후 data/publish_history.json "만" add/commit → push origin HEAD:main
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def load_records(path: Path) -> list[dict[str, Any]]:
    """원장 로드 — 없거나 손상돼도 크래시 대신 빈 목록(병합은 보수적으로 진행)."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"warn: {path} 파싱 실패 ({exc}) — 빈 원장으로 취급", file=sys.stderr)
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def record_fingerprint(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def record_timestamp(record: dict[str, Any]) -> str:
    """정렬 키 — ISO 문자열은 사전순=시간순. 없으면 빈 문자열(맨 앞 유지)."""
    for field in ("run_at", "published_at", "date"):
        value = str(record.get(field) or "").strip()
        if value:
            return value
    return ""


def merge_ledgers(
    base: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """base ∪ incoming을 시간순으로. 반환: (병합 결과, incoming에서 새로 추가된 수)."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    added_from_incoming = 0
    for source, records in (("base", base), ("incoming", incoming)):
        for record in records:
            fingerprint = record_fingerprint(record)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            merged.append(record)
            if source == "incoming":
                added_from_incoming += 1
    merged.sort(key=record_timestamp)  # 안정 정렬 — 동일 타임스탬프는 원 순서 유지
    return merged, added_from_incoming


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="main 원장 경로")
    parser.add_argument("--incoming", required=True, type=Path, help="이번 런 원장 경로")
    parser.add_argument("--out", required=True, type=Path, help="병합 결과 저장 경로")
    args = parser.parse_args()

    base = load_records(args.base)
    incoming = load_records(args.incoming)
    merged, added = merge_ledgers(base, incoming)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"merged ledger: base={len(base)} incoming={len(incoming)} "
        f"-> total={len(merged)} (new from incoming={added})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
