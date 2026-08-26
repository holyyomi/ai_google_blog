from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.cluster_service import ClusterService, is_cluster_candidate
from blogspot_automation.services.seo_policy import build_internal_links_from_history


def _write_config(tmp_path: Path, *, slots: list[dict]) -> Path:
    payload = {
        "active_cluster": "demo",
        "clusters": [
            {
                "key": "demo",
                "name": "Demo cluster",
                "why": "because",
                "topic_group": "ai_work",
                "content_type": "ai_work_tip",
                "slots": slots,
            }
        ],
    }
    path = tmp_path / "clusters.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _slot(slot_id: str, *, pillar: bool = False) -> dict:
    return {
        "slot_id": slot_id,
        "topic": f"topic for {slot_id}",
        "search_demand_topic": f"{slot_id} search phrase",
        "questions": ["q1?", "q2?", "q3?"],
        "click_reason": "reason",
        "reader_benefit": "benefit",
        "content_promise": "promise",
        "angle_type": "money_compare",
        "is_pillar": pillar,
    }


def _published(slot_id: str, *, cluster_key: str = "demo") -> dict:
    return {
        "run_at": "2026-08-26T00:00:00+00:00",
        "date": "2026-08-26",
        "cluster_key": cluster_key,
        "cluster_slot": slot_id,
        "published": True,
        "dry_run": False,
        "status": "published",
    }


@pytest.fixture(autouse=True)
def _cluster_env(monkeypatch):
    monkeypatch.setenv("ENABLE_TOPIC_CLUSTER", "true")
    monkeypatch.delenv("ACTIVE_CLUSTER_KEY", raising=False)
    monkeypatch.delenv("CLUSTER_WEEKDAYS", raising=False)


def test_next_slot_follows_ledger_order(tmp_path):
    config = _write_config(tmp_path, slots=[_slot("a"), _slot("b"), _slot("hub", pillar=True)])
    service = ClusterService(config_path=config)

    progress = service.progress([])
    assert progress is not None
    assert progress.next_slot.slot_id == "a"

    progress = service.progress([_published("a")])
    assert progress.next_slot.slot_id == "b"


def test_pillar_comes_last_even_though_it_is_listed_last(tmp_path):
    config = _write_config(tmp_path, slots=[_slot("a"), _slot("hub", pillar=True), _slot("b")])
    service = ClusterService(config_path=config)

    # 허브는 자식이 전부 끝난 뒤에만 나온다 — 링크할 대상이 없는 허브는 의미가 없다.
    assert service.progress([_published("a")]).next_slot.slot_id == "b"
    progress = service.progress([_published("a"), _published("b")])
    assert progress.next_slot.slot_id == "hub"
    assert progress.next_slot.is_pillar is True


def test_complete_cluster_yields_no_candidate(tmp_path):
    config = _write_config(tmp_path, slots=[_slot("a"), _slot("hub", pillar=True)])
    service = ClusterService(config_path=config)
    records = [_published("a"), _published("hub")]

    assert service.progress(records).complete is True
    assert service.collect_candidates(records, ignore_schedule=True) == []


def test_unpublished_slot_record_does_not_count_as_done(tmp_path):
    """게이트에 막혀 발행 실패한 슬롯은 다음 클러스터 요일에 다시 나와야 한다."""
    config = _write_config(tmp_path, slots=[_slot("a"), _slot("b")])
    service = ClusterService(config_path=config)
    blocked = dict(_published("a"))
    blocked.update({"published": False, "status": "blocked_by_quality_gate"})

    assert service.progress([blocked]).next_slot.slot_id == "a"


def test_other_cluster_records_are_ignored(tmp_path):
    config = _write_config(tmp_path, slots=[_slot("a"), _slot("b")])
    service = ClusterService(config_path=config)

    records = [_published("a", cluster_key="some_other_cluster")]
    assert service.progress(records).next_slot.slot_id == "a"


def test_candidate_carries_cluster_markers_and_publishable_source_type(tmp_path):
    config = _write_config(tmp_path, slots=[_slot("a")])
    service = ClusterService(config_path=config)

    candidates = service.collect_candidates([], ignore_schedule=True)
    assert len(candidates) == 1
    raw = candidates[0].raw
    assert is_cluster_candidate(raw) is True
    assert raw["cluster_key"] == "demo"
    assert raw["cluster_slot"] == "a"
    # 자동발행 게이트가 아는 source_type이어야 한다. 새 값을 쓰면 글은 생성되고
    # 발행만 안 되는 조용한 0건이 된다 (cluster_service 모듈 docstring 3번).
    assert raw["source_type"] == "evergreen_fallback"
    assert raw["content_angle"]["content_type"] == "ai_work_tip"
    assert raw["topic_group"] == "ai_work"
    assert candidates[0].topic == "a search phrase"


def test_schedule_limits_cluster_to_configured_weekdays(tmp_path, monkeypatch):
    config = _write_config(tmp_path, slots=[_slot("a")])
    service = ClusterService(config_path=config)
    monkeypatch.setenv("CLUSTER_WEEKDAYS", "0")

    monday, tuesday = date(2026, 8, 24), date(2026, 8, 25)
    assert ClusterService.is_cluster_day(monday) is True
    assert ClusterService.is_cluster_day(tuesday) is False
    assert len(service.collect_candidates([], today=monday)) == 1
    assert service.collect_candidates([], today=tuesday) == []


def test_disabled_flag_stops_everything(tmp_path, monkeypatch):
    config = _write_config(tmp_path, slots=[_slot("a")])
    monkeypatch.setenv("ENABLE_TOPIC_CLUSTER", "false")

    assert ClusterService(config_path=config).collect_candidates([], ignore_schedule=True) == []


def test_missing_or_broken_config_is_not_fatal(tmp_path):
    missing = ClusterService(config_path=tmp_path / "nope.json")
    assert missing.active_plan() is None
    assert missing.collect_candidates([], ignore_schedule=True) == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert ClusterService(config_path=broken).collect_candidates([], ignore_schedule=True) == []


def test_shipped_config_is_loadable_and_has_exactly_one_pillar():
    """실제 배포되는 config/clusters.json이 깨지면 클러스터가 조용히 꺼진다."""
    service = ClusterService(config_path=Path("config/clusters.json"))
    plan = service.active_plan()
    assert plan is not None, "config/clusters.json에서 활성 클러스터를 못 읽었다"
    assert len(plan.pillar_slots) == 1
    assert len(plan.child_slots) >= 5
    slot_ids = [slot.slot_id for slot in plan.slots]
    assert len(slot_ids) == len(set(slot_ids)), "slot_id 중복 — 진행 판정이 깨진다"
    for slot in plan.slots:
        assert slot.search_demand_topic, slot.slot_id
        assert len(slot.questions) >= 3, slot.slot_id


def test_every_shipped_slot_matches_a_golden_pattern():
    """패턴이 안 붙으면 article_candidate가 생성되지 않아 자동발행이 막힌다.

    2026-08-26 실측: 슬롯 7개 중 5개가 confidence 52(기준 80)였고, 드라이런에서
    글은 다 써놓고 `article_candidate_not_generated`로 발행만 안 되는 상태였다.
    파이프라인이 쓰는 것과 같은 방식으로 요약을 조립해 판정한다.
    """
    from blogspot_automation.services.golden_article_preview_service import (
        GoldenArticlePreviewService,
    )

    service = ClusterService(config_path=Path("config/clusters.json"))
    plan = service.active_plan()
    preview = GoldenArticlePreviewService()

    weak = []
    for slot in plan.slots:
        raw = ClusterService.to_candidate(plan, slot).raw
        # news_pipeline.build_preview 호출부와 동일한 요약 조립 순서.
        summary = " ".join(
            part
            for part in (
                str(raw.get("search_demand_topic") or ""),
                " ".join(list(raw.get("reader_search_questions") or [])[:2]),
                str((raw.get("content_angle") or {}).get("reader_question") or ""),
                " ".join(list(raw.get("sample_titles") or [])[:3]),
            )
            if part
        )
        result = preview.build_preview(
            topic=raw["search_demand_topic"],
            content_type=plan.content_type,
            topic_group=plan.topic_group,
            summary=summary,
            candidate_raw=raw,
        )
        match = result.get("pattern_match") or {}
        if not (match.get("matched") and result.get("ready_for_review")):
            weak.append(
                (slot.slot_id, match.get("confidence"), result.get("blocking_issues"))
            )

    assert not weak, f"골든 패턴 미매칭/미준비 슬롯: {weak}"


# --------------------------------------------------------------- dedup / links


def _scored(raw: dict, *, topic: str) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(topic=topic, category="tech", summary=topic, raw=raw),
        freshness_score=0,
        search_demand_score=0,
        contrarian_gap_score=0,
        mass_impact_score=0,
        adsense_value_score=0,
        hook_score=0,
        risk_penalty=0,
        total_score=80,
        reason="",
    )


def test_cluster_candidate_survives_entity_cooldown(monkeypatch):
    """엔티티 쿨다운이 클러스터 슬롯을 막으면 그 슬롯은 영원히 안 나온다.

    실측(2026-08-26, 원장 614건): 'gemini free api limits' 슬롯은 최근 구글
    관련 발행 때문에 예외가 없으면 실제로 차단된다. 클러스터는 정의상 며칠에
    걸쳐 같은 영역을 훑는 기획이라, 이 규칙을 그대로 두면 기획 자체가 성립하지
    않는다.
    """
    from blogspot_automation.services.topic_dedup_service import TopicDedupService

    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.setenv("ENTITY_COOLDOWN_APPLIES_TO_AI_BLOG_MODE", "true")
    service = TopicDedupService()
    history = [
        {
            "run_at": "2026-08-26T00:00:00+00:00",
            "date": "2026-08-26",
            "title": "Google Gemini agentic updates",
            "selected_topic": "Google Gemini agentic updates",
            "published": True,
            "dry_run": False,
            "status": "published",
        }
    ]

    plain = _scored(
        {"source_type": "evergreen_fallback"}, topic="gemini free api limits"
    )
    clustered = _scored(
        {
            "source_type": "evergreen_fallback",
            "topic_cluster": True,
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "gemini_free_limits",
        },
        topic="gemini free api limits",
    )

    assert service.is_duplicate(plain, history) is True
    assert service.is_duplicate(clustered, history) is False


def test_cluster_candidate_still_blocked_on_exact_topic_repeat(monkeypatch):
    """예외는 키워드 중복까지다 — 같은 주제 재탕은 클러스터라도 막혀야 한다."""
    from blogspot_automation.services.topic_dedup_service import TopicDedupService

    monkeypatch.setenv("AI_BLOG_MODE", "true")
    service = TopicDedupService()
    history = [
        {
            "run_at": "2026-08-26T00:00:00+00:00",
            "date": "2026-08-26",
            "title": "openrouter free models limit",
            "selected_topic": "openrouter free models limit",
            "published": True,
            "dry_run": False,
            "status": "published",
        }
    ]
    clustered = _scored(
        {
            "source_type": "evergreen_fallback",
            "topic_cluster": True,
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "openrouter_free_limits",
        },
        topic="openrouter free models limit",
    )

    assert service.is_duplicate(clustered, history) is True


def test_cluster_candidate_wins_selection_even_with_a_lower_score():
    """점수 경쟁으로는 순위를 보장할 수 없다 — 확정 선택이어야 한다.

    실측(2026-08-26 드라이런): 커뮤니티 뉴스 후보가 수요 가산으로 100점까지
    올라가 96점 클러스터 후보를 이겼다. 부스트 숫자를 상한에 맞춰 올리는 방식은
    상한이 바뀌면 조용히 깨지므로, 선택 자체를 확정한다.
    """
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline

    news = _scored({"source_type": "community_hackernews"}, topic="some hot ai news")
    news.total_score = 100
    clustered = _scored(
        {
            "source_type": "evergreen_fallback",
            "topic_cluster": True,
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "openrouter_free_limits",
        },
        topic="openrouter free models limit",
    )
    clustered.total_score = 96

    pipeline = NewsPipeline.__new__(NewsPipeline)  # 무거운 __init__ 없이 선택 로직만 검증
    chosen = pipeline._choose_selected_candidate([news, clustered], {})

    assert chosen is clustered


def test_cluster_titles_do_not_reuse_a_stock_suffix_twice(tmp_path):
    """실측(2026-08-26): 슬롯 7개 중 4개가 'limit' 때문에 같은 제목 꼬리를 받는다.

    한 클러스터에서 제목 네 개가 ': What Actually Works'면 전문성이 아니라
    양산형으로 읽힌다.
    """
    from types import SimpleNamespace

    from blogspot_automation.pipelines.news_pipeline import NewsPipeline
    from blogspot_automation.services.publish_history_service import PublishHistoryService

    ledger = tmp_path / "history.json"
    ledger.write_text(
        json.dumps([
            {
                "run_at": "2026-08-26T00:00:00+00:00", "date": "2026-08-26",
                # 발행 제목은 후보 선정 "이후" 다시 쓰인다 — 2026-08-26 GHA 리허설에서
                # 후보 "…: What Actually Works (2026)"가 "…: What Works 2026"으로 나갔다.
                # 문자열 일치로 보면 같은 꼬리를 못 알아본다.
                "title": "OpenRouter Free Models Limit Reset: What Works 2026",
                "cluster_key": "free_ai_api_reality", "cluster_slot": "openrouter_free_limits",
                "published": True, "dry_run": False, "status": "published",
            }
        ]),
        encoding="utf-8",
    )

    pipeline = NewsPipeline.__new__(NewsPipeline)
    pipeline.publish_history_service = PublishHistoryService(history_path=ledger)
    clustered = _scored(
        {
            "source_type": "evergreen_fallback",
            "topic_cluster": True,
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "gemini_free_limits",
        },
        topic="gemini free api limits",
    )
    titles = [
        SimpleNamespace(title="Gemini Free API Limits: What Actually Works (2026)"),
        SimpleNamespace(title="Gemini Free API Limits: Causes and Fixes"),
    ]

    kept = pipeline._drop_titles_reusing_cluster_phrasing(clustered, titles)
    assert [t.title for t in kept] == ["Gemini Free API Limits: Causes and Fixes"]

    # 후보가 전부 걸리면 제목을 0개로 만들지 않고 원본을 유지한다.
    only_stock = [SimpleNamespace(title="Gemini Free API Limits: What Actually Works (2026)")]
    assert pipeline._drop_titles_reusing_cluster_phrasing(clustered, only_stock) == only_stock

    # 클러스터 글이 아니면 아무것도 건드리지 않는다.
    plain = _scored({"source_type": "community_hackernews"}, topic="hot ai news")
    assert pipeline._drop_titles_reusing_cluster_phrasing(plain, titles) == titles


def test_cluster_candidate_survives_real_news_narrowing():
    """실뉴스 필터가 클러스터를 버리면 '주입은 됐는데 발행은 안 되는' 조용한 실패가 된다.

    2026-08-26 드라이런에서 실제로 발생: 클러스터 후보가 scored=1 publishable=0으로
    사라졌고, 로그에는 주입·부스트만 찍혀 원인이 안 보였다.
    """
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline

    news = _scored({"source_type": "community_hackernews"}, topic="hot ai news")
    clustered = _scored(
        {
            "source_type": "evergreen_fallback",
            "topic_cluster": True,
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "openrouter_free_limits",
        },
        topic="openrouter free models limit",
    )
    pipeline = NewsPipeline.__new__(NewsPipeline)

    narrowed = pipeline._narrow_publishable_to_real_news(
        publishable=[clustered, news], real_news_publishable=[news],
    )
    assert clustered in narrowed
    assert news in narrowed

    # 클러스터가 없는 날은 기존 동작 그대로 — 실뉴스만 남는다.
    plain_evergreen = _scored({"source_type": "evergreen_fallback"}, topic="evergreen topic")
    assert pipeline._narrow_publishable_to_real_news(
        publishable=[plain_evergreen, news], real_news_publishable=[news],
    ) == [news]


def test_selection_falls_back_to_normal_path_without_cluster_candidate(monkeypatch):
    """클러스터가 없는 날은 기존 선택 로직을 그대로 타야 한다."""
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline

    news = _scored({"source_type": "community_hackernews"}, topic="some hot ai news")
    pipeline = NewsPipeline.__new__(NewsPipeline)
    calls: list = []

    def fake_select(deduped, history):
        calls.append((deduped, history))
        return news

    monkeypatch.setattr(pipeline, "_select_diverse_candidate", fake_select, raising=False)
    assert pipeline._choose_selected_candidate([news], {}) is news
    assert len(calls) == 1


def test_internal_link_count_grows_with_the_cluster():
    """3개로 고정하면 클러스터가 6편이 돼도 절반은 아무 데서도 링크받지 못한다."""
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline

    def sibling(index: int) -> dict:
        return {
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": f"slot{index}",
            "published": True,
            "dry_run": False,
            "status": "published",
        }

    cluster_raw = {"cluster_key": "free_ai_api_reality"}
    # 형제가 없는 첫 글은 기존과 같은 3개 — 관련 없는 최근 글로 자리를 채우지 않는다.
    assert NewsPipeline._internal_link_limit(cluster_raw, []) == 3
    assert NewsPipeline._internal_link_limit(cluster_raw, [sibling(i) for i in range(2)]) == 3
    assert NewsPipeline._internal_link_limit(cluster_raw, [sibling(i) for i in range(5)]) == 5
    # 허브 시점(자식 6편)에는 6개 전부.
    assert NewsPipeline._internal_link_limit(cluster_raw, [sibling(i) for i in range(6)]) == 6
    # 상한을 넘지 않는다.
    assert NewsPipeline._internal_link_limit(cluster_raw, [sibling(i) for i in range(20)]) == 6

    # 미발행(게이트 탈락) 형제는 세지 않는다 — 링크할 URL이 없다.
    blocked = dict(sibling(9))
    blocked.update({"published": False, "status": "blocked_by_quality_gate"})
    assert NewsPipeline._internal_link_limit(
        cluster_raw, [sibling(i) for i in range(4)] + [blocked]
    ) == 4

    # 클러스터가 아닌 글은 기존 동작 그대로.
    assert NewsPipeline._internal_link_limit({}, [sibling(i) for i in range(6)]) == 3


def test_internal_links_prefer_same_cluster(monkeypatch):
    monkeypatch.setenv("ENABLE_INTERNAL_LINK_LIVENESS_CHECK", "false")
    base = {
        "published": True,
        "dry_run": False,
        "status": "published",
        "topic_group": "ai_work",
        "content_type": "ai_work_tip",
    }
    records = []
    # 대조군은 "더 최신이고 제목 단어도 더 겹치는" 글들이다. 클러스터 가중이
    # 없으면 이쪽이 이겨야 테스트가 가중치를 실제로 검증하는 게 된다.
    for index in range(6):
        records.append(
            {
                **base,
                "run_at": f"2026-08-2{index}T00:00:00+00:00",
                "date": f"2026-08-2{index}",
                "title": f"Gemini agentic updates roundup number {index}",
                "url": f"https://holyyomiai.blogspot.com/2026/08/gemini-agentic-updates-{index}.html",
            }
        )
    records.insert(
        0,
        {
            **base,
            "run_at": "2026-08-10T00:00:00+00:00",
            "date": "2026-08-10",
            "title": "OpenRouter free model limits explained",
            "url": "https://holyyomiai.blogspot.com/2026/08/openrouter-free-model-limits.html",
            "cluster_key": "free_ai_api_reality",
            "cluster_slot": "openrouter_free_limits",
        },
    )

    links = build_internal_links_from_history(
        records,
        current_title="Gemini free API limits",
        current_topic="gemini free api limits",
        current_topic_group="ai_work",
        current_content_type="ai_work_tip",
        current_cluster_key="free_ai_api_reality",
        limit=3,
    )
    assert links, "링크가 하나도 안 나왔다"
    assert "openrouter-free-model-limits" in links[0][1]

    # 클러스터 키를 안 주면 기존 동작(최근 글 우선) 그대로여야 한다.
    without_cluster = build_internal_links_from_history(
        records,
        current_title="Gemini free API limits",
        current_topic="gemini free api limits",
        current_topic_group="ai_work",
        current_content_type="ai_work_tip",
        limit=3,
    )
    assert "openrouter-free-model-limits" not in without_cluster[0][1]
