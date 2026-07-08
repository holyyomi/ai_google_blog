"""수동 publish 리허설을 Blogger 초안으로 보내는 플래그 테스트.

배경: ai_blog.yml의 수동 publish 모드가 스케줄과 똑같이 라이브에 발행해,
PR 개발 중 "리허설"들이 라이브에 실제 글을 쌓아 중복을 만들었음.
NEWS_PUBLISH_AS_DRAFT=true면 파이프라인이 is_draft=True로 발행해 초안만 남긴다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("", False),
        ("no", False),
    ],
)
def test_publish_as_draft_reads_env(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("NEWS_PUBLISH_AS_DRAFT", value)
    assert NewsPipeline().publish_as_draft is expected


def test_publish_as_draft_defaults_false_when_env_absent(monkeypatch) -> None:
    monkeypatch.delenv("NEWS_PUBLISH_AS_DRAFT", raising=False)
    assert NewsPipeline().publish_as_draft is False


def test_publish_calls_thread_the_draft_flag() -> None:
    """발행 흐름이 하드코딩된 is_draft=False 대신 self.publish_as_draft를 쓴다.

    로드맵 5(발행 경로 3→1 통합) 이후 발행 호출부는 _execute_publish_flow
    하나뿐이므로 draft 플래그 전달도 정확히 1곳이어야 한다.
    """
    import inspect

    source = inspect.getsource(NewsPipeline)
    assert "is_draft=False" not in source, "발행 호출부에 하드코딩된 is_draft=False가 남아있음"
    assert source.count("is_draft=self.publish_as_draft") == 1


def test_pipeline_has_single_publish_call_site() -> None:
    """구조 가드(로드맵 5): 발행 메커니즘은 _execute_publish_flow 하나여야 한다.

    과거 3벌 복제(main/clean_trending/today_issue)는 경로 간 표류(감사 유무·
    초안 처리 차이)를 만들었고 한 곳 수정이 세 곳 패치를 요구했다. 이 테스트가
    복제 재발을 막는다 — publish 호출을 추가하려면 헬퍼를 경유하라.
    """
    import inspect

    source = inspect.getsource(NewsPipeline)
    assert source.count("publish_service.publish(") == 1, (
        "publish_service.publish 직접 호출이 늘었다 — _execute_publish_flow를 경유할 것"
    )
