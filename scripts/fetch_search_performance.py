"""Search Console 성과를 받아 data/search_performance.json에 저장한다.

발행 워크플로우가 파이프라인 실행 전에 호출한다. GSC_SERVICE_ACCOUNT_JSON이
없거나 호출이 실패해도 exit 0 — 발행 흐름을 절대 막지 않는다.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[1]
if str(root_dir / "src") not in sys.path:
    sys.path.insert(0, str(root_dir / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from blogspot_automation.services.search_console_service import (  # noqa: E402
    fetch_search_performance,
    save_search_performance,
)


def main() -> int:
    data = fetch_search_performance()
    if not data:
        print("search performance: 데이터 없음 (키 미설정 또는 수집 실패) — 스킵")
        return 0
    saved = save_search_performance(data)
    print(f"search performance: 저장 {'성공' if saved else '실패'} — 쿼리 {len(data.get('queries') or [])}행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
