from __future__ import annotations

from blogspot_automation.models.news_models import (
    NewsCandidate,
    ScoredNewsCandidate,
    SelectedNewsPlan,
    TitleCandidate,
)
from blogspot_automation.services.answer_engine_policy import ensure_answer_engine_optimized_html
from blogspot_automation.services.contrarian_content_service import ContrarianContentService
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.seo_policy import count_external_anchor_links, prepare_blogspot_html


def test_today_issue_explainer_fallback_uses_context_not_problem_solution() -> None:
    plan = _today_issue_plan()
    html = ContrarianContentService().generate_html(plan)

    # today_issue 템플릿 사용 증거는 구조 마커로 확인한다. 과거에는
    # "유형: today_issue_explainer" 내부 라벨 노출 라인이 이 역할을 겸했는데,
    # 그 라벨은 독자에게 보이면 안 되는 정보라 제거됐다.
    assert "variant-timeline" in html
    assert "확인된" in html
    assert "아직 확인" in html
    assert "관전 포인트" in html
    assert "신청 방법" not in html
    assert "환급" not in html
    assert "홈택스" not in html
    assert "blog.naver.com" not in html


def test_today_issue_explainer_publish_html_has_no_outbound_links_and_passes_audit() -> None:
    plan = _today_issue_plan()
    html = ContrarianContentService().generate_html(plan)
    prepared = prepare_blogspot_html(html, strip_document=True)
    prepared = ensure_answer_engine_optimized_html(
        prepared,
        title=plan.selected_title.title,
        topic=plan.selected_topic.candidate.topic,
        content_type="today_issue_explainer",
        topic_group="today_issue",
    )
    audit = audit_final_html_quality(
        prepared,
        topic=plan.selected_topic.candidate.topic,
        content_type="today_issue_explainer",
        topic_group="today_issue",
    )

    assert count_external_anchor_links(prepared) == 0
    assert audit["passed"], audit


def _today_issue_plan() -> SelectedNewsPlan:
    candidate = NewsCandidate(
        topic="한미 정상 통화 발언 해석 논란",
        category="today_issue",
        summary="공개 발언 이후 정치권과 온라인에서 해석이 갈린 이슈",
        raw={
            "topic_group": "today_issue",
            "content_angle": {
                "content_type": "today_issue_explainer",
                "reader_question": "무엇이 확인됐고 무엇이 해석일까?",
                "reader_loss": "초기 반응만 보면 사실과 주장이 섞일 수 있다.",
                "practical_value": "확인된 내용과 아직 확인할 쟁점을 분리한다.",
            },
        },
    )
    scored = ScoredNewsCandidate(
        candidate=candidate,
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="test",
    )
    title = TitleCandidate(
        title="한미 정상 통화 발언, 지금 확인된 것과 아직 모르는 것",
        hook_type="맥락정리",
        ctr_score=90,
        reason="test",
    )
    plan = SelectedNewsPlan(
        selected_topic=scored,
        title_candidates=[title],
        selected_title=title,
        contrarian_angle="확정 사실과 해석을 분리한다.",
        mainstream_view="반응만 빠르게 소비한다.",
        reader_benefit="흔들리지 않고 읽을 순서를 얻는다.",
        labels=["오늘이슈", "뉴스해설", "맥락정리"],
    )
    return plan
