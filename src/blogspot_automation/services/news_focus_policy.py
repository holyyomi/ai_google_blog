from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


_AI_TOPIC_TERMS: tuple[str, ...] = (
    "ai",
    "artificial intelligence",
    "chatgpt",
    "openai",
    "claude",
    "gemini",
    "copilot",
    "perplexity",
    "midjourney",
    "elevenlabs",
    "runway",
    "sora",
    "llm",
    "gpt",
    "인공지능",
    "챗GPT",
    "챗지피티",
    "오픈AI",
    "클로드",
    "제미나이",
    "코파일럿",
    "퍼플렉시티",
    "미드저니",
    "일레븐랩스",
    "생성형AI",
    "생성형 AI",
    "AI도구",
    "AI 도구",
    "AI자동화",
    "AI 자동화",
)

_AI_TOPIC_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:ai|chatgpt|openai|claude|gemini|copilot|perplexity|midjourney|elevenlabs|runway|sora|llm|gpt)(?![a-z0-9])",
    flags=re.IGNORECASE,
)

_POLITICAL_GEOPOLITICAL_TERMS: tuple[str, ...] = (
    "대통령",
    "전 대통령",
    "국회",
    "여당",
    "야당",
    "정당",
    "의원",
    "후보",
    "표심",
    "민심",
    "선거구",
    "한강벨트",
    "정치권",
    "서울시장",
    "시장 후보",
    "대선",
    "총선",
    "지방선거",
    "사전투표",
    "투표 포기",
    "정상회담",
    "외교",
    "휴전",
    "휴전안",
    "전쟁",
    "군사",
    "국방장관",
    "국방부",
    "방위비",
    "동맹국",
    "종전",
    "안보 회의",
    "핵합의",
    "레드라인",
    "트럼프",
    "바이든",
    "푸틴",
    "시진핑",
    "이재명",
    "윤석열",
    "한동훈",
    "조국",
    "국민의힘",
    "더불어민주당",
    "민주당",
    "장동혁",
    "오세훈",
)
_FOREIGN_ADMIN_TERMS: tuple[str, ...] = (
    "외국인 체류자격",
    "체류자격",
    "체류 자격",
    "비자 갱신",
    "비자 수수료",
    "영주권",
    "출입국",
    "입국관리",
    "일본 외국인",
)
_HARM_CRIME_TERMS: tuple[str, ...] = (
    "사망",
    "숨진",
    "숨졌다",
    "숨져",
    "살해",
    "살인",
    "폭행",
    "시신",
    "변사",
    "흉기",
    "극단적 선택",
    "일가족",
    "경찰 조사",
    "경찰,",
    "경찰 ",
    "압수수색",
    "수색",
    "수사 착수",
    "스토킹",
    "체포",
    "검거",
    "구속",
    "입건",
    "집 찾아가",
)
_EVERYDAY_EXCEPTION_TERMS: tuple[str, ...] = (
    "택배",
    "배송",
    "집화",
    "휴무",
    "반품",
    "배달",
    "마트",
    "은행",
    "병원",
    "학교",
    "교통",
)
# 대기업 노사·공시·총수 거버넌스 가십 차단 (사용자 선호: 대기업 노사·공시 싫음).
# 제품·서비스·게임 출시 뉴스는 막지 않도록 거버넌스/노사/공시 신호 기반으로만 차단.
_CORPORATE_GOVERNANCE_TERMS: tuple[str, ...] = (
    "재계",
    "총수",
    "오너일가",
    "오너 일가",
    "오너리스크",
    "오너 리스크",
    "지배구조",
    "경영권 분쟁",
    "경영권 승계",
    "경영승계",
    "지분 매각",
    "지분 인수",
    "노사",
    "노동조합",
    "임단협",
    "단체교섭",
    "임금 협상",
    "파업 결의",
    "주주총회",
    "자사주",
    "배임",
    "횡령",
    "분식회계",
    "공시 위반",
    "상속세",
    "지주사 전환",
    "계열 분리",
)
_CHAEBOL_GROUP_TERMS: tuple[str, ...] = (
    "삼성",
    "현대차",
    "현대자동차",
    "SK",
    "LG",
    "롯데",
    "한화",
    "GS",
    "CJ",
    "신세계",
    "두산",
    "HD현대",
    "포스코",
    "효성",
    "코오롱",
    "LS",
)
_CORPORATE_ROLE_TERMS: tuple[str, ...] = (
    "회장",
    "부회장",
    "총수",
    "오너",
)


@dataclass(frozen=True, slots=True)
class NewsFocusDecision:
    allowed: bool
    reason: str = ""
    matched_terms: tuple[str, ...] = ()


def allow_ai_news_topics_from_env() -> bool:
    default = "true" if ai_blog_mode_from_env() else "false"
    return os.getenv("ALLOW_AI_NEWS_TOPICS", default).strip().lower() in {"1", "true", "yes", "on"}


def ai_blog_mode_from_env() -> bool:
    return os.getenv("AI_BLOG_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}


def allow_political_today_issues_from_env() -> bool:
    return os.getenv("ALLOW_POLITICAL_TODAY_ISSUES", "false").strip().lower() in {"1", "true", "yes", "on"}


def allow_corporate_governance_topics_from_env() -> bool:
    return os.getenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", "false").strip().lower() in {"1", "true", "yes", "on"}


def evaluate_news_focus(
    *,
    topic: str = "",
    title: str = "",
    summary: str = "",
    raw: dict[str, Any] | None = None,
) -> NewsFocusDecision:
    """Keep the news blog focused by blocking off-scope automated news topics."""
    payload = raw or {}
    topic_group = str(payload.get("topic_group") or "")
    content_angle = payload.get("content_angle") if isinstance(payload.get("content_angle"), dict) else {}
    content_type = str(content_angle.get("content_type") or payload.get("content_type") or "")
    query_group = str(payload.get("query_group") or payload.get("source_query_group") or "")
    evergreen_axis = str(payload.get("evergreen_axis") or "")
    text = " ".join(
        str(part or "")
        for part in (
            topic,
            title,
            summary,
            payload.get("original_topic"),
            payload.get("search_demand_topic"),
            query_group,
            topic_group,
            content_type,
            evergreen_axis,
        )
    )
    broad_today_issue = _is_broad_today_issue_candidate(payload)
    matched = _matched_ai_terms(text)
    is_ai_topic = (
        topic_group == "ai_work"
        or content_type == "ai_work_tip"
        or evergreen_axis == "ai_automation"
        or query_group == "ai_work"
        or bool(matched)
    )
    harm_crime_matches = _matched_terms(text, _HARM_CRIME_TERMS)
    if harm_crime_matches:
        return NewsFocusDecision(
            allowed=False,
            reason="harm_crime_topic_blocked_for_news_focus",
            matched_terms=harm_crime_matches,
        )
    if not allow_corporate_governance_topics_from_env() and not _has_everyday_exception(text):
        corporate_matches = _matched_terms(text, _CORPORATE_GOVERNANCE_TERMS)
        if not corporate_matches:
            role_matches = _matched_terms(text, _CORPORATE_ROLE_TERMS)
            group_matches = _matched_terms(text, _CHAEBOL_GROUP_TERMS)
            if role_matches and group_matches:
                corporate_matches = tuple(dict.fromkeys(role_matches + group_matches))
        if corporate_matches:
            return NewsFocusDecision(
                allowed=False,
                reason="corporate_governance_topic_blocked_for_news_focus",
                matched_terms=corporate_matches,
            )
    political_matches = _matched_terms(text, _POLITICAL_GEOPOLITICAL_TERMS)
    if (
        political_matches
        and not _has_everyday_exception(text)
        and (not broad_today_issue or not allow_political_today_issues_from_env())
    ):
        return NewsFocusDecision(
            allowed=False,
            reason="political_geopolitical_topic_blocked_for_news_focus",
            matched_terms=political_matches,
        )
    foreign_admin_matches = _matched_terms(text, _FOREIGN_ADMIN_TERMS)
    if foreign_admin_matches and not broad_today_issue:
        return NewsFocusDecision(
            allowed=False,
            reason="foreign_admin_topic_blocked_for_news_focus",
            matched_terms=foreign_admin_matches,
        )
    if ai_blog_mode_from_env() and not is_ai_topic:
        return NewsFocusDecision(
            allowed=False,
            reason="non_ai_topic_blocked_for_ai_blog_mode",
            matched_terms=(),
        )
    if not allow_ai_news_topics_from_env() and not broad_today_issue and is_ai_topic:
        return NewsFocusDecision(
            allowed=False,
            reason="ai_topic_blocked_for_news_only_operation",
            matched_terms=matched,
        )
    return NewsFocusDecision(allowed=True)


def _is_broad_today_issue_candidate(payload: dict[str, Any]) -> bool:
    content_angle = payload.get("content_angle") if isinstance(payload.get("content_angle"), dict) else {}
    content_type = str(content_angle.get("content_type") or payload.get("content_type") or "")
    topic_group = str(payload.get("topic_group") or "")
    return content_type == "today_issue_explainer" or topic_group == "today_issue"


def _matched_ai_terms(text: str) -> tuple[str, ...]:
    raw = " ".join((text or "").split())
    if not raw:
        return ()
    lowered = raw.lower()
    matches: list[str] = []
    for term in _AI_TOPIC_TERMS:
        if term.isascii():
            term_l = term.lower()
            if " " in term_l:
                found = term_l in lowered
            else:
                found = bool(re.search(rf"(?<![a-z0-9]){re.escape(term_l)}(?![a-z0-9])", lowered))
            if found:
                matches.append(term)
        elif term in raw:
            matches.append(term)
    if _AI_TOPIC_PATTERN.search(raw):
        token = _AI_TOPIC_PATTERN.search(raw)
        if token:
            matches.append(token.group(0))
    return tuple(dict.fromkeys(matches))


def _matched_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    raw = " ".join((text or "").split())
    lowered = raw.lower()
    matches: list[str] = []
    for term in terms:
        term_l = term.lower()
        found = term_l in lowered if term.isascii() else term in raw
        if found:
            matches.append(term)
    return tuple(dict.fromkeys(matches))


def _has_everyday_exception(text: str) -> bool:
    raw = " ".join((text or "").split())
    return any(term in raw for term in _EVERYDAY_EXCEPTION_TERMS)
