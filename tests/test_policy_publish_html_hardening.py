from __future__ import annotations

import json
from pathlib import Path
import tempfile

from blogspot_automation.services.answer_engine_policy import ensure_answer_engine_optimized_html
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.geo_intent_service import GeoIntentService
from blogspot_automation.services.run_artifact_service import RunArtifactService


def test_policy_intent_answers_are_topic_specific_and_unique() -> None:
    service = GeoIntentService()
    topic = "고유가 피해지원금 지급일과 신청방법 정리"
    questions = service.generate_reader_intent_questions(
        topic=topic,
        content_type="policy_deadline",
        topic_group="policy_benefit",
        slots={},
    )

    answers = service.generate_intent_answers(
        questions=questions,
        topic=topic,
        content_type="policy_deadline",
        slots={
            "faq": [
                {"Q": "신청 대상은 누구인가요?", "A": "공식 안내에서 대상 조건을 확인해야 합니다."},
                {"Q": "필요 서류는 어디서 발급하나요?", "A": "공식 안내에서 대상 조건을 확인해야 합니다."},
            ]
        },
    )

    assert len(answers) >= 5
    assert sum(1 for item in answers if "고유가 피해지원금" in item["Q"]) >= 3
    normalized_answers = {" ".join(item["A"].split()) for item in answers}
    assert len(normalized_answers) == len(answers)


def test_answer_engine_normalizes_duplicate_lede_after_aeo_insert() -> None:
    html = """
    <article class="yomi-clean-post">
      <div class="yomi-lede"><p>정책 지원금은 대상 조건과 신청 기간을 먼저 봐야 합니다.</p></div>
      <div class="yomi-thesis"><div><b>확정</b>공식 공고 확인 필요</div><div><b>확인</b>개인 조건 확인 필요</div></div>
      <ul class="yomi-list"><li data-step="1">신청 페이지를 확인합니다.</li></ul>
    </article>
    """

    result = ensure_answer_engine_optimized_html(
        html,
        title="고유가 피해지원금 지급일과 신청방법 정리",
        topic="고유가 피해지원금 지급일과 신청방법 정리",
        content_type="policy_deadline",
        topic_group="policy_benefit",
    )
    audit = audit_final_html_quality(
        result,
        topic="고유가 피해지원금 지급일과 신청방법 정리",
        content_type="policy_deadline",
        topic_group="policy_benefit",
    )

    assert 'id="AI_OVERVIEW_TARGET_ANSWER"' in result
    assert audit["metrics"]["yomi_clean_layout"]["lede_count"] == 1
    assert "yomi_clean_layout_lede_count:2" not in audit["issues"]


def test_run_artifact_service_updates_promoted_publish_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RunArtifactService(runs_dir=Path(temp_dir))
        run_path = service.save_dry_run_result(
            html="<article>draft</article>",
            selected_topic={"topic": "고유가 피해지원금"},
            title_candidates=[],
            scoring={"publish_quality_gate": {"passed": False}},
            run_meta={"publish_quality_gate": {"passed": False}},
        )

        promoted_gate = {
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
            "publish_preview_scorecard": {"status": "pass", "score": 100},
        }
        service.update_publish_artifacts(
            run_path,
            html="<article>promoted</article>",
            publish_quality_gate=promoted_gate,
            run_meta_updates={"final_publish_html_source": "article_candidate"},
            scoring_updates={"selected_title": "고유가 피해지원금 지급일과 신청방법 정리"},
        )

        assert (run_path / "article.html").read_text(encoding="utf-8") == "<article>promoted</article>"
        run_meta = json.loads((run_path / "run_meta.json").read_text(encoding="utf-8"))
        scoring = json.loads((run_path / "scoring.json").read_text(encoding="utf-8"))
        assert run_meta["publish_quality_gate"]["passed"] is True
        assert run_meta["final_publish_html_source"] == "article_candidate"
        assert scoring["publish_quality_gate"]["passed"] is True
        assert scoring["selected_title"] == "고유가 피해지원금 지급일과 신청방법 정리"
        assert (run_path / "publish_preview_scorecard.json").exists()
