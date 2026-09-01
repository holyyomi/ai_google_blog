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
    # 자료 조달 확인은 실제 웹을 호출한다. 단위 테스트에서는 통과로 고정하고,
    # 그 동작 자체는 test_fact_availability_* 에서 따로 검증한다.
    monkeypatch.setattr(qd, "_has_enough_facts", lambda topic: True)


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


# ------------------------------------------------------- 일반 독자(consumer) 소스

def _patch_autocomplete(monkeypatch, mapping: dict[str, list[str]]):
    monkeypatch.setattr(qd, "_autocomplete", lambda seed: mapping.get(seed, []))


def test_consumer_source_is_tried_before_the_developer_source(monkeypatch):
    """일반 독자 질문이 1순위. 순서가 뒤집히면 글이 다시 어려워진다.

    2026-08-31 실측: 개발자 소스만 쓰던 시절 발행 글 첫 문장이
    "CC Switch issue 4627 (June 2026) confirms most NIM models fail in Claude Code"였다.
    """
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {
        "is chatgpt free": ["is chatgpt free", "is chatgpt free to use",
                            "is chatgpt free for students", "is chatgpt free and safe",
                            "is chatgpt free on iphone"],
    })
    # 개발자 소스가 응답해도 쓰이면 안 된다.
    _patch_requests(monkeypatch, [_item("OpenAI API 429 quota exceeded", 500_000)])
    monkeypatch.setattr(qd, "_passes_golden_pattern", lambda c: True)

    picked = qd.collect_candidates([], max_candidates=1)
    assert len(picked) == 1
    assert picked[0].raw["source"] == "consumer_demand"
    assert picked[0].raw["audience_level"] == "general"


def test_developer_source_is_the_fallback(monkeypatch):
    """일반 독자 후보가 전멸하면 개발자 질문으로 내려간다."""
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {})  # 자동완성 전멸
    _patch_requests(monkeypatch, [_item("OpenAI API 429 quota exceeded", 500_000)])
    monkeypatch.setattr(qd, "_passes_golden_pattern", lambda c: True)

    picked = qd.collect_candidates([], max_candidates=1)
    assert len(picked) == 1
    assert picked[0].raw["source"] == "question_demand"


def test_reddit_suffixed_suggestions_are_a_signal_not_a_target(monkeypatch):
    """'... reddit' 제안은 가산점 신호로만 쓰고 제목으로 삼지 않는다.

    2026-08-31 첫 실행에서 상위 8개가 전부 reddit 접미사로 채워졌다. 레딧 스레드를
    이길 수도 없고 글 제목으로도 이상하다.
    """
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {
        "is chatgpt free": ["is chatgpt free", "is chatgpt free reddit",
                            "is chatgpt free to use", "is chatgpt free for students",
                            "is chatgpt free and safe"],
    })
    found = qd.fetch_consumer_demand([])
    assert found, "후보가 있어야 한다"
    assert all("reddit" not in row["title"].lower() for row in found)
    # 형제 제안에 reddit이 있었으므로 신호는 켜져야 한다.
    assert found[0]["human_answer_wanted"] is True


def test_near_duplicate_consumer_topics_are_collapsed(monkeypatch):
    """'chatgpt free limits'와 'chatgpt free limits per day'는 같은 글이다."""
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {
        "chatgpt free limit": ["chatgpt free limits", "chatgpt free limits per day",
                               "chatgpt free limit", "chatgpt free limits today",
                               "chatgpt free limits explained"],
    })
    found = qd.fetch_consumer_demand([])
    assert len(found) == 1, f"근접 중복이 남았다: {[r['title'] for r in found]}"


def test_consumer_topic_already_covered_is_skipped(monkeypatch):
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {
        "is chatgpt free": ["is chatgpt free", "is chatgpt free to use",
                            "is chatgpt free for students", "is chatgpt free and safe",
                            "is chatgpt free on iphone"],
    })
    history = [{"title": "Is ChatGPT free to use", "published": True, "status": "published"}]
    found = qd.fetch_consumer_demand(history)
    assert all(not qd._is_near_duplicate(r["title"], "Is ChatGPT free to use") for r in found)


def test_one_tool_cannot_monopolize_the_shortlist(monkeypatch):
    """한 도구가 상위를 독식하면 매일 같은 도구 글만 나온다."""
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt,gemini")
    five = lambda base: [f"{base} {i}" for i in range(5)]
    _patch_autocomplete(monkeypatch, {
        "is chatgpt free": five("is chatgpt free option"),
        "chatgpt free limit": five("chatgpt free limit variant"),
        "is gemini free": five("is gemini free option"),
    })
    found = qd.fetch_consumer_demand([])
    from collections import Counter
    counts = Counter(r["tool"] for r in found)
    assert all(v <= 2 for v in counts.values()), counts


def test_consumer_candidate_marks_a_non_technical_reader(monkeypatch):
    candidate = qd.consumer_to_candidate({
        "title": "chatgpt free limits per day", "saturation": 10,
        "human_answer_wanted": True, "seed": "chatgpt free limit", "tool": "chatgpt",
    })
    raw = candidate.raw
    assert raw["source_type"] == "evergreen_fallback"
    assert raw["publish_allowed"] is True
    assert raw["audience_level"] == "general"
    assert "not programmers" in raw["target_reader"] or "프로그래머가 아닌" in raw["target_reader"]
    assert raw["consumer_demand_saturation"] == 10


# ------------------------------------------------- 자료 조달 가능성 확인

def test_topic_without_sourceable_facts_is_skipped(monkeypatch):
    """검색 수요가 커도 쓸 자료가 없으면 주제를 바꿔야 한다.

    2026-09-01 실측: 'chatgpt free limit for chats with attachments'는 자동완성
    10/10으로 뽑혔지만 수집된 팩트가 737자(헤드라인 수준)뿐이었다. 모델이 헤지로
    채웠고 헤지 포화 검증기가 두 번 거부해 그날 글이 통째로 안 나왔다.
    """
    monkeypatch.setattr(qd, "_gather_facts_for_probe", None, raising=False)
    monkeypatch.setenv("CONSUMER_DEMAND_TOOLS", "chatgpt")
    _patch_autocomplete(monkeypatch, {
        "is chatgpt free": ["is chatgpt free", "is chatgpt free to use",
                            "is chatgpt free for students", "is chatgpt free and safe",
                            "is chatgpt free on iphone"],
    })
    monkeypatch.setattr(qd, "_passes_golden_pattern", lambda c: True)
    monkeypatch.setattr(qd, "_has_enough_facts", lambda topic: False)
    assert qd.collect_candidates([], max_candidates=1) == []


def test_fact_probe_failure_does_not_block_publishing(monkeypatch):
    """조달 확인이 실패했다고 발행을 막으면 고치려던 문제보다 큰 문제가 된다."""
    import blogspot_automation.services.llm_content_service as llm

    class _Boom:
        def _gather_facts(self, topic):
            raise RuntimeError("network down")

    monkeypatch.setattr(llm, "LlmContentService", _Boom)
    assert qd._has_enough_facts("anything") is True
