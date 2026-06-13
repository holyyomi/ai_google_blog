from __future__ import annotations

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


def test_same_story_repeat_is_blocked() -> None:
    # 키워드 + 부주제 2개 겹침 = 같은 사건 재탕 → 차단
    cand = {"손흥민", "이적설", "토트넘"}
    recent = [{"손흥민", "이적설에", "이적설", "침묵하는", "토트넘이", "토트넘"}]
    assert NewsPipeline._matches_recent_issue(cand, "손흥민", recent) is True


def test_new_development_of_same_entity_is_allowed() -> None:
    # 같은 인물이라도 새 사건(겹침 1개)은 허용 — 후속편이 조회수 기회
    cand = {"손흥민", "결승골", "브렌트포드"}
    recent = [{"손흥민", "이적설", "토트넘"}]
    assert NewsPipeline._matches_recent_issue(cand, "손흥민", recent) is False


def test_poor_signal_candidate_blocked_on_exact_keyword() -> None:
    # 토큰 2개 이하 빈약 후보는 보수적으로 키워드 일치 차단
    cand = {"손흥민"}
    recent = [{"손흥민", "이적설", "토트넘"}]
    assert NewsPipeline._matches_recent_issue(cand, "손흥민", recent) is True


def test_unrelated_issue_passes() -> None:
    cand = {"장마", "정의", "기상학계"}
    recent = [{"손흥민", "이적설", "토트넘"}, {"넷플릭스", "요금제", "인상"}]
    assert NewsPipeline._matches_recent_issue(cand, "장마", recent) is False


def test_empty_history_allows_everything() -> None:
    assert NewsPipeline._matches_recent_issue({"손흥민", "이적설"}, "손흥민", []) is False


def test_stop_tokens_do_not_inflate_overlap() -> None:
    # "오늘/이슈/뉴스" 같은 범용 토큰은 시그니처에서 제외되어야 한다
    toks = NewsPipeline._issue_tokens("오늘 이슈 뉴스 손흥민 결승골 정리")
    assert toks == {"손흥민", "결승골"}
