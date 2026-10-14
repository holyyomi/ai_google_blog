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
    # 2026-07-18 실측 사고: 발행 후 감사(post_publish_audit_service)가 URL
    # 슬러그만으로 이 목록을 재검사하는데(원본 raw 메타데이터 없이), 아래
    # 브랜드가 빠져 있어 정상 AI 글(Grok 기사)이 "AI 주제 아님"으로 오판돼
    # 라이브 발행 직후 자동 삭제·재시도됐다(ai_topic_leaked_to_news_blog).
    "grok",
    "xai",
    "deepseek",
    "mistral",
    "llama",
    "cursor",
    "notebooklm",
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
    r"(?<![a-z0-9])(?:ai|chatgpt|openai|claude|gemini|copilot|perplexity|midjourney|elevenlabs|runway|sora|llm|gpt"
    r"|grok|xai|deepseek|mistral|llama|cursor|notebooklm)(?![a-z0-9])",
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
    # 영어 전환(2026-07-17) 추가 — 영어 소스에서의 정치/지정학 차단 신호.
    # _matched_terms는 ascii substring 매칭이라 AI 도구 기사에 오탐될 수 있는
    # 단어(bare "war", "president", "campaign")는 피하고 복합어/구체어만 쓴다.
    "election",
    "president trump",
    "white house",
    "congress",
    "senate",
    "parliament",
    "ceasefire",
    "airstrike",
    "sanctions",
    "war in",
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
    # 영어 전환(2026-07-17) 추가 — 영어 소스에서의 강력범죄/피해 차단 신호.
    # bare "killed"는 "skilled/reskilled"에 substring 오탐되므로 구 단위로만 등록.
    "murder",
    "was killed",
    "killed in",
    "shot dead",
    "stabbing",
    "assault",
    "suicide",
    "dead body",
    "homicide",
    "police investigation",
    "arrested",
    "kidnapping",
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
    ai_match_text = " ".join(
        str(part or "")
        for part in (
            topic,
            title,
            summary,
            payload.get("original_topic"),
            payload.get("search_demand_topic"),
        )
    )
    broad_today_issue = _is_broad_today_issue_candidate(payload)
    matched = _matched_ai_terms(ai_match_text)
    is_ai_metadata_topic = (
        topic_group == "ai_work"
        or content_type == "ai_work_tip"
        or evergreen_axis == "ai_automation"
    )
    is_ai_topic = (
        is_ai_metadata_topic
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
    # 2026-10-14: 영어 AI 블로그 뉴스 후보는 메타데이터(topic_group=ai_work)만으로
    # 통과시키지 않는다. 이 모드 후보는 사실상 전부 ai_work로 분류돼 아래 검사가
    # 무력했고, "Volvo EX40 …"·"Splunk earnings …" 같은 비AI 기사가 발행됐다.
    # 제목·요약·주제 자체에 AI 신호어가 하나도 없으면 막는다. 에버그린·클러스터·
    # 질문발굴 후보는 실측 검색어라 대상이 아니다.
    if (
        ai_blog_mode_from_env()
        and _requires_strict_ai_signal(payload)
        and not _has_strict_ai_signal(ai_match_text)
    ):
        return NewsFocusDecision(
            allowed=False,
            reason="non_ai_topic_blocked_no_ai_signal",
            matched_terms=(),
        )
    # In AI blog mode, the source query group alone is not enough. Broad search
    # APIs often return unrelated articles for an AI query, so require actual
    # AI terms or downstream AI taxonomy metadata.
    if ai_blog_mode_from_env() and not (is_ai_metadata_topic or bool(matched)):
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


# 영어 AI 블로그 후보의 AI 신호어(2026-10-14). _AI_TOPIC_TERMS에 더해 회사·도구·
# 개념어를 넓게 받는다 — 넓을수록 덜 막는다. 단 "model" 단독은 자동차 기사
# ("new EX40 model")에 흔해 AI 문맥 복합어로만 받는다.
_STRICT_AI_SIGNAL_RE = re.compile(
    r"(?<![a-z0-9])(?:a\.i\.|artificial intelligence|machine learning|deep learning|"
    r"neural (?:network|net)s?|llms?|large language models?|language models?|"
    r"(?:ai|foundation|frontier|reasoning|open[- ]weights?|open[- ]source|diffusion|vision|video|image|voice|coding)\s+models?|"
    r"agents?|agentic|chatbots?|generative|genai|gen ai|inference|transformers?|"
    r"prompts?|prompting|fine[- ]tun\w*|hallucinat\w*|context window|"
    r"anthropic|codex|hugging ?face|openrouter|ollama|langchain|qwen|windsurf|"
    r"stable diffusion|suno|runway ?ml|kimi|moonshot|agi|superintelligence)(?![a-z0-9])",
    flags=re.IGNORECASE,
)


def _requires_strict_ai_signal(payload: dict[str, Any]) -> bool:
    if os.getenv("AI_SIGNAL_FILTER", "on").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        from blogspot_automation.services.blog_language import is_english_mode
    except Exception:  # noqa: BLE001
        return False
    if not is_english_mode():
        return False  # 한국어 모드 동작은 그대로 둔다.
    if payload.get("evergreen_fallback") or payload.get("topic_cluster"):
        return False
    return True


def _has_strict_ai_signal(text: str) -> bool:
    value = " ".join((text or "").split())
    if not value:
        return True  # 판정 근거가 없으면 막지 않는다.
    return bool(_matched_ai_terms(value)) or bool(_STRICT_AI_SIGNAL_RE.search(value))


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
