"""매일 실측 질문 발굴 서비스 — 계약과 실패 모드 고정.

2026-08-31 요미님 지시로 도입: "미리 채워놓고 하면 더 나쁜 글이 올라간다."
슬롯 뱅크 대신 발행 시점에 수요를 다시 재서 그날의 주제를 고른다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services import question_demand_service as qd


def _item(title: str, views: int, *, answered: bool = True) -> dict:
    return {
        "title": title,
        "view_count": views,
        "is_answered": answered,
        "link": "https://stackoverflow.com/q/1",
    }


class _FakeResponse:
    def __init__(self, items: list[dict], status: int = 200) -> None:
        self._items = items
        self.status_code = status

    def json(self) -> dict:
        return {"items": self._items, "quota_remaining": 250}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ENABLE_QUESTION_DEMAND", "true")
    monkeypatch.setenv("QUESTION_DEMAND_TAGS", "openai-api")


def _patch_requests(monkeypatch, items: list[dict], *, status: int = 200):
    monkeypatch.setattr(qd.requests, "get",
                        lambda *a, **k: _FakeResponse(items, status))


def test_picks_the_highest_demand_niche_question(monkeypatch):
    _patch_requests(monkeypatch, [
        _item("OpenAI API giving error: 429 Too Many Requests", 100_000),
        _item("OpenAI API rate limit exceeded on free tier", 5_000),
    ])
    found = qd.fetch_question_demand([])
    assert found
    assert found[0]["views"] == 100_000


def test_unanswered_questions_get_a_bonus(monkeypatch):
    """답이 없는 질문 = 콘텐츠 공백. 조회수가 조금 낮아도 앞선다."""
    _patch_requests(monkeypatch, [
        _item("OpenAI API 429 quota exceeded", 100_000, answered=True),
        _item("OpenAI API 403 permission denied on free tier", 90_000, answered=False),
    ])
    found = qd.fetch_question_demand([])
    assert found[0]["answered"] is False, "가산점 적용 시 미답변이 앞서야 한다"


def test_off_niche_and_noise_are_filtered(monkeypatch):
    """패키지 설치 오류·파인튜닝은 이 블로그 주제가 아니다."""
    _patch_requests(monkeypatch, [
        _item("ImportError: cannot import name from openai", 500_000),
        _item("How to fine-tune with LoRA target modules", 400_000),
        _item("OpenAI API 429 quota exceeded on free tier", 10_000),
    ])
    found = qd.fetch_question_demand([])
    assert len(found) == 1
    assert "429" in found[0]["title"]


def test_low_view_questions_are_dropped(monkeypatch):
    _patch_requests(monkeypatch, [_item("OpenAI API 429 rate limit", 100)])
    assert qd.fetch_question_demand([]) == []


def test_already_covered_topics_are_skipped(monkeypatch):
    """원장에 같은 벤더+에러코드 조합이 있으면 다시 쓰지 않는다."""
    _patch_requests(monkeypatch, [
        _item("OpenAI API giving error: 429 Too Many Requests", 100_000),
    ])
    history = [{
        "title": "OpenAI 429 exceeded your current quota explained",
        "published": True,
        "status": "published",
    }]
    assert qd.fetch_question_demand(history) == []


def test_network_failure_is_non_fatal(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(qd.requests, "get", _boom)
    assert qd.fetch_question_demand([]) == []
    assert qd.collect_candidates([]) == []


def test_http_error_is_non_fatal(monkeypatch):
    _patch_requests(monkeypatch, [], status=429)
    assert qd.fetch_question_demand([]) == []


def test_disabled_flag_stops_everything(monkeypatch):
    monkeypatch.setenv("ENABLE_QUESTION_DEMAND", "false")
    _patch_requests(monkeypatch, [_item("OpenAI API 429 quota", 100_000)])
    assert qd.fetch_question_demand([]) == []


def test_candidate_carries_the_publishable_contract(monkeypatch):
    """source_type은 evergreen_fallback을 재사용해야 한다.

    새 값을 만들면 신선도·자동발행 허용·골든패턴 분기를 전부 다시 통과시켜야 하고,
    하나만 놓쳐도 '글은 썼는데 발행만 안 되는' 조용한 0건이 된다.
    """
    candidate = qd.to_candidate({
        "title": "OpenAI API giving error: 429 Too Many Requests",
        "views": 114_054, "answered": True,
        "url": "https://stackoverflow.com/q/1", "tag": "openai-api",
    })
    raw = candidate.raw
    assert raw["source_type"] == "evergreen_fallback"
    assert raw["publish_allowed"] is True
    assert raw["evergreen_fallback"] is True
    assert raw["is_stale"] is False
    # 클러스터와 같은 dedup/쿨다운 면제를 받기 위한 마커.
    assert raw["topic_cluster"] is True
    assert raw["cluster_key"] == "question_demand_live"
    assert raw["cluster_slot"]
    assert raw["question_demand_views"] == 114_054
    # 골든패턴 매칭에 실제로 쓰이는 필드들이 비어있으면 안 된다.
    assert raw["sample_titles"] and raw["sample_titles"][0]
    assert len(raw["reader_search_questions"]) >= 2


def test_golden_pattern_reject_is_skipped_not_published(monkeypatch):
    """게이트 미달 후보는 내보내지 않고 다음 후보로 넘어간다.

    실측(2026-08-31): 발굴 8개 중 2개가 confidence 25로 기준(80) 미달이었다.
    그대로 내보내면 글은 다 써놓고 article_candidate_not_generated로 발행만
    막히는 조용한 실패가 된다. 슬롯 뱅크와 달리 제목을 미리 알 수 없으므로
    서비스가 스스로 걸러야 한다.
    """
    _patch_requests(monkeypatch, [
        _item("OpenAI API 429 quota exceeded first", 200_000),
        _item("OpenAI API 429 rate limit second", 100_000),
    ])
    calls = {"n": 0}

    def _fake_gate(candidate):
        calls["n"] += 1
        return calls["n"] > 1  # 첫 번째만 탈락

    monkeypatch.setattr(qd, "_passes_golden_pattern", _fake_gate)
    picked = qd.collect_candidates([], max_candidates=1)
    assert len(picked) == 1
    assert "second" in picked[0].topic
