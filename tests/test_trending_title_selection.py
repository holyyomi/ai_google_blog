from __future__ import annotations

from blogspot_automation.services.trending_article_service import TrendingArticleService

_TOKENS = ["손흥민", "토트넘", "이적설"]


def test_select_best_title_prefers_specific_hooked_candidate() -> None:
    title = TrendingArticleService._select_best_title(
        [
            "손흥민 이적설 관련 소식",  # 짧고 평범
            "손흥민 이적설에 토트넘이 침묵하는 동안 움직인 세 가지",  # entity+숫자+길이 적정
        ],
        primary_tokens=_TOKENS,
    )
    assert title == "손흥민 이적설에 토트넘이 침묵하는 동안 움직인 세 가지"


def test_select_best_title_penalizes_cliche() -> None:
    title = TrendingArticleService._select_best_title(
        [
            "손흥민 이적설 충격 총정리, 역대급 상황 모든 것",
            "손흥민 이적설, 토트넘 공식 입장 전에 확인된 3가지 정황",
        ],
        primary_tokens=_TOKENS,
    )
    assert "총정리" not in title
    assert title.startswith("손흥민 이적설, 토트넘")


def test_select_best_title_skips_integrity_blocked() -> None:
    # 받침 명사 + '가' = bad_subject_particle → integrity 차단되어야 함
    title = TrendingArticleService._select_best_title(
        [
            "종합특검가 시작된 이유와 다음 수순",
            "종합특검이 겨누는 곳, 수사 대상과 일정으로 본 다음 수순",
        ],
        primary_tokens=["종합특검"],
    )
    assert title == "종합특검이 겨누는 곳, 수사 대상과 일정으로 본 다음 수순"


def test_select_best_title_falls_back_to_first_when_all_blocked() -> None:
    title = TrendingArticleService._select_best_title(
        ["종합특검가 시작", "종합특검가 출범"],
        primary_tokens=[],
    )
    assert title == "종합특검가 시작"


def test_select_best_title_dedupes_and_handles_empty() -> None:
    assert TrendingArticleService._select_best_title([], primary_tokens=[]) == ""
    title = TrendingArticleService._select_best_title(
        ["같은 제목 후보입니다 오늘 이슈 기준으로 확인", "같은 제목 후보입니다 오늘 이슈 기준으로 확인"],
        primary_tokens=[],
    )
    assert title == "같은 제목 후보입니다 오늘 이슈 기준으로 확인"
