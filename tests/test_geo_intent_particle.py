from __future__ import annotations

from blogspot_automation.services.geo_intent_service import GeoIntentService, _ga, _josa
from blogspot_automation.services.title_integrity_policy import _has_bad_subject_particle


def test_josa_handles_batchim() -> None:
    # 받침 있는 명사
    assert _josa("종합특검", "은", "는") == "종합특검은"
    assert _ga("종합특검") == "종합특검이"
    assert _josa("손흥민", "을", "를") == "손흥민을"
    # 받침 없는 명사
    assert _josa("전세사기 피해", "은", "는") == "전세사기 피해는"
    assert _ga("전세사기 피해") == "전세사기 피해가"
    # 영문(받침 없음으로 처리)
    assert _ga("LPGA") == "LPGA가"
    assert _josa("LPGA", "은", "는") == "LPGA는"


def test_today_issue_intent_answers_have_no_broken_subject_particle() -> None:
    svc = GeoIntentService()
    for subject in ("종합특검", "손흥민", "넷플릭스 참교육", "전세사기 피해"):
        questions = svc.generate_reader_intent_questions(
            topic=subject,
            content_type="today_issue_explainer",
            topic_group="today_issue",
            slots={},
        )
        answers = svc.generate_intent_answers(
            questions=questions,
            topic=subject,
            content_type="today_issue_explainer",
            slots={},
        )
        for text in list(questions) + [a.get("A", "") if isinstance(a, dict) else str(a) for a in answers]:
            # 받침 명사에 '가'(주격) 잘못 붙는 깨짐이 없어야 한다.
            assert not _has_bad_subject_particle(text), f"{subject} → {text}"
