"""KST(Asia/Seoul, UTC+9) 기준 '오늘' 계산.

GitHub Actions 러너는 기본 TZ가 UTC라, 아침 스케줄(07:31 KST = 전날 22:31 UTC)
실행 시 datetime.now()가 하루 전 날짜를 반환해 발행글의 "기준일"이 실제
발행일보다 하루 어긋난다. KST는 DST가 없으므로 고정 UTC+9 오프셋으로 계산한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def kst_today(fmt: str = "%Y-%m-%d") -> str:
    return datetime.now(KST).strftime(fmt)
