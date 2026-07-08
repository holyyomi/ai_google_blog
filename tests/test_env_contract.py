"""env 계약 테스트 — 코드가 읽는 env와 ai_blog.yml이 주입하는 env의 정합 검증.

배경(2026-07-08 구조 감사): 이 파이프라인의 동작은 워크플로우 env 58개로
결정되는데, env 한 줄 누락이 곧 사일런트 동작 변경이었다:
- PR #23: ai_blog.yml에 PUBLISH_HOLD_PHASE2가 역사상 한 번도 없었음 → 기본값
  "true" → 5일 연속 자동발행 0건 (2026-07-03~06 사건의 결정타).
- PR #25: 커버 이미지 env 부재 → 모든 발행 글 썸네일 없음 (라이브에서야 발견).
이 테스트는 그 사고 유형을 "머지 전에" 잡는다: 발행에 치명적인 env가 워크플로우
에서 빠지거나, 워크플로우가 코드가 읽지도 않는 죽은 env를 들고 있으면 실패한다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_BLOG_YML = REPO_ROOT / ".github" / "workflows" / "ai_blog.yml"

# 발행 동작을 좌우하는 치명 env — 하나라도 워크플로우에서 빠지면 사일런트 사고.
# (새 발행 스위치를 추가하면 여기에도 추가할 것 — 이 목록이 곧 발행 env 계약이다)
CRITICAL_PUBLISH_ENVS = {
    "DRY_RUN",                 # 발행 여부 마스터 스위치
    "AUTO_PUBLISH",            # 자동 발행 허용
    "NEWS_PUBLISH_MODE",       # publish/dry_run 모드
    "NEWS_PUBLISH_AS_DRAFT",   # 수동 리허설=초안 (라이브 오염 차단)
    "PUBLISH_HOLD_PHASE2",     # 누락 시 기본 true → 전 발행 홀드 (PR #23)
    "BLOGGER_CLIENT_ID",
    "BLOGGER_CLIENT_SECRET",
    "BLOGGER_REFRESH_TOKEN",
    "BLOGGER_BLOG_ID",
    "AI_DEFAULT_COVER_IMAGE_URL",  # 누락 시 전 글 썸네일 없음 (PR #25)
    "BLOGSPOT_HOME_URL",
    "DEDUP_DAYS",              # 중복 방지 창
}

# 워크플로우에만 있고 src/scripts 코드가 직접 읽지 않아도 되는 키.
# 새로 추가하려면 왜 코드 스캔에 안 잡히는지 사유를 적을 것.
WORKFLOW_ONLY_ALLOWLIST: dict[str, str] = {}


def _yml_env_keys() -> set[str]:
    content = AI_BLOG_YML.read_text(encoding="utf-8")
    return set(re.findall(r"^\s+([A-Z][A-Z0-9_]+):", content, flags=re.MULTILINE))


def _code_env_keys() -> set[str]:
    """코드에 문자열 리터럴로 등장하는 ALL-CAPS 토큰 전부.

    env는 os.getenv 직접 호출뿐 아니라 _env_bool("KEY"), "api_key_env": "KEY",
    keys.append("KEY") 같은 간접 패턴으로도 읽힌다. 그래서 "키 이름이 코드
    어디에도 문자열로 존재하지 않으면 죽은 env"를 계약으로 삼는다 —
    이 방향(죽은 env 탐지)에는 넓은 스캔이 오탐을 줄이는 올바른 선택이다.
    """
    keys: set[str] = set()
    pattern = re.compile(r"[\"']([A-Z][A-Z0-9_]{2,})[\"']")
    for base in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            keys.update(pattern.findall(text))
    return keys


def test_critical_publish_envs_present_in_workflow() -> None:
    """치명 env가 ai_blog.yml에 전부 존재해야 한다 (PR #23/#25 재발 방지)."""
    missing = CRITICAL_PUBLISH_ENVS - _yml_env_keys()
    assert not missing, (
        f"ai_blog.yml에 치명 발행 env 누락: {sorted(missing)} — "
        "누락된 env는 기본값으로 조용히 동작이 바뀐다 (PR #23: 5일 미발행)"
    )


def test_critical_publish_envs_are_read_by_code() -> None:
    """치명 env를 코드가 실제로 읽어야 한다 (양쪽 오타·죽은 계약 방지)."""
    missing = CRITICAL_PUBLISH_ENVS - _code_env_keys()
    assert not missing, (
        f"코드가 읽지 않는 치명 env: {sorted(missing)} — "
        "이름이 바뀌었거나 오타면 워크플로우 주입이 무의미해진다"
    )


def test_workflow_envs_are_read_somewhere() -> None:
    """워크플로우가 주입하는 모든 env는 코드 어딘가에서 읽혀야 한다 (죽은 env 드리프트 방지)."""
    dead = _yml_env_keys() - _code_env_keys() - set(WORKFLOW_ONLY_ALLOWLIST)
    assert not dead, (
        f"ai_blog.yml에 있지만 어떤 코드도 읽지 않는 env: {sorted(dead)} — "
        "이름 변경 드리프트이거나 제거 대상. 의도적이면 WORKFLOW_ONLY_ALLOWLIST에 사유와 함께 등록"
    )
