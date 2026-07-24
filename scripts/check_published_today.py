#!/usr/bin/env python3
"""오늘(KST) 라이브 발행이 이미 있는지 원장으로 판정한다 — stdout에 "true"/"false".

GHA(1순위)와 Cloud Run(폴백)이 같은 슬롯을 중복 발행하는 것을 막는 공용 가드.
2026-07-20~21 사고: GHA가 Actions-minute 한도로 큐에서 57분~2시간 지연되다
늦게라도 성공해버려, Cloud Run의 "최근 90분 내 GHA run 존재?" 체크 시점엔
없던 GHA가 나중에 같은 슬롯에 또 발행했다. 시간 기반 핸드셰이크는 지연에
깨지므로, 발행의 유일한 진실원장(data/publish_history.json)을 직접 본다 —
어느 쪽이든 실행 시작 시점에 "오늘 라이브 발행이 이미 있으면" 스킵한다.

"라이브 발행" 판정 (2026-07-24 원장 실측 기준):
- published == true
- url에 blogspot.com 포함 — publish_draft 리허설은 blogger.com/blog/post/edit
  URL이 남고, 게이트 차단 실행은 url이 비어 이 조건에서 자연히 제외된다.
- 날짜는 run_at(UTC ISO)을 KST로 변환해 비교. run_at이 없거나 깨졌으면
  date 필드로 폴백.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def published_today(entries: list, today_kst: str) -> bool:
    for entry in reversed(entries or []):
        if not isinstance(entry, dict) or not entry.get("published"):
            continue
        url = str(entry.get("url") or "")
        if "blogspot.com" not in url:
            continue
        entry_day = ""
        run_at = str(entry.get("run_at") or "")
        if run_at:
            try:
                entry_day = (
                    datetime.fromisoformat(run_at).astimezone(KST).strftime("%Y-%m-%d")
                )
            except ValueError:
                entry_day = ""
        if not entry_day:
            entry_day = str(entry.get("date") or "")
        if entry_day == today_kst:
            return True
    return False


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/publish_history.json"
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        # 원장이 없거나 깨졌으면 발행을 막지 않는다 — 이 가드는 중복 방지용이지
        # 발행 차단 게이트가 아니다.
        print("false")
        return
    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    print("true" if published_today(entries, today_kst) else "false")


if __name__ == "__main__":
    main()
