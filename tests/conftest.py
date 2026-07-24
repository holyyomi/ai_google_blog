"""테스트 전역 환경 격리.

cli_ai.py는 임포트 시 os.environ.setdefault("AI_BLOG_MODE", "true")를
실행한다 — 실제 프로세스에서는 그 프로세스 전체가 AI 모드로 돌아야 하므로
의도된 동작이지만, pytest는 같은 프로세스에서 수백 개 테스트를 순서대로
돌리기 때문에 cli_ai를 import하는 아무 테스트 하나가 먼저 실행되면 그 뒤
모든 테스트에 AI_BLOG_MODE=true가 새어 들어간다(2026-07-23 실측: 이 값을
읽는 새 로직을 추가하자 무관한 기존 테스트 4개가 전체 스위트에서만, 단독
실행 시엔 통과하는 방식으로 깨짐 — 전형적인 테스트 순서 의존 오염).

매 테스트 시작 전 이 값을 지워 기본값(미설정)에서 시작하게 한다. AI_BLOG_MODE
동작을 검증하는 테스트는 monkeypatch.setenv로 이 fixture 이후 명시적으로
설정하면 되므로 영향 없다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_ai_blog_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_BLOG_MODE", raising=False)
