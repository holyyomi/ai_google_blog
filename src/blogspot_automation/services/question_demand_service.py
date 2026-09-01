"""매 실행마다 '지금 사람들이 실제로 묻는 질문'을 새로 발굴한다.

왜 슬롯 뱅크가 아니라 매일 발굴인가 (2026-08-31 요미님 지시)
------------------------------------------------------------
"미리 채워놓고 하면 더 나쁜 글이 올라간다" — 실제 운영 경험이고, 이 프로젝트의
CLAUDE.md 주제 선정 정책과도 원래 같은 말이다: **"고정 주제 후보 금지. 매 실행마다
신선 발굴이 1순위, 뱅크는 폴백일 뿐."** 미리 적어둔 슬롯은 몇 주 전 판단을 그대로
굳혀버린다 — 가격이 바뀌고 모델명이 바뀌고 에러 문구가 바뀌어도 문안은 그대로고,
글쓰는 쪽은 오늘의 근거를 조사하는 대신 이미 정해진 각도에 맞춰 칸을 채우게 된다.

그래서 여기서는 **발행 시점에** 실측 수요를 다시 긁어 그날의 주제를 고른다.

일반 독자 질문이 1순위다 (2026-08-31 요미님 지시: "기존 글들이 너무 어렵다")
---------------------------------------------------------------------------
실측한 발행 글의 첫 문장이 이랬다: *"CC Switch issue 4627 (June 2026) confirms most
NIM models fail in Claude Code."* 깃허브 이슈 번호로 글을 시작하니 프로그래머가
아니면 둘째 줄에서 이탈한다. 원인은 글쓰기가 아니라 **주제 선택**이었다 — Stack
Overflow는 개발자 사이트라 거기서만 뽑으면 계속 개발자 글이 나온다. 아무리 쉽게
써도 "CC Switch 이슈"를 일반 독자에게 쉽게 만들 수는 없다.

같은 날 실측한 수요 차이가 결정적이다. 일반 독자 질문(is chatgpt free / chatgpt vs
gemini / why is chatgpt not working / chatgpt plus worth it / how to cancel chatgpt
…)은 **10개 전부 자동완성 만점(10/10)** 이었다. 개발자 에러 질문은 1~10개로 들쭉날쭉했다.
게다가 제안어에 `reddit`이 계속 붙는다 — 사람들이 벤더 홍보가 아니라 진짜 답을 찾는다는
신호다. 애드센스 관점에서도 개발자 트래픽은 광고 차단률이 높아 불리하다.

그래서 **CONSUMER(일반 독자) 소스를 1순위, 개발자 소스를 2순위**로 둔다.

수요 신호 두 가지 (tools/demand_mine.py에서 검증한 것과 같은 소스)
------------------------------------------------------------------
1. **Google Autocomplete (일반 독자)**: 제안 개수가 곧 그 질문의 포화도다. 10개면
   구글이 그 표현으로 검색이 충분히 많다고 보는 것. 절대 크기는 못 주지만 일반 대중이
   실제로 치는 말인지를 가장 잘 반영한다. 키 불필요.
2. **Stack Exchange (개발자)**: 유일하게 **질문당 절대 조회수**를 준다. 1순위가
   전멸했을 때만 쓴다 — 수요는 크지만 독자층이 좁고 글이 어려워진다.

에러 메시지·요금 질문을 노리는 공통 이유: 사람이 검색창에 치는 문장이자 LLM에게 그대로
복붙해 묻는 문장이고, 상위 결과가 포럼 스레드·GitHub 이슈뿐이라 제대로 답한 문서가 비어
있으며, 뉴스와 달리 1년 뒤에도 같은 수요가 있다.

안전 설계
---------
- 네트워크·쿼터 실패는 전부 비치명. 빈 리스트를 돌려주고 기존 경로가 그대로 돈다.
- 원장과 대조해 이미 다룬 주제는 제외한다.
- 니치 밖(패키지 설치 오류, 파인튜닝 등)과 잡음(불만글·특정 IDE 질문)은 걸러낸다.
  실측에서 벤더 포럼 상위에 "OPEN LETTER TO SUNDAR PICHAI" 같은 글이 조회수만 높게
  올라온 적이 있다 — 조회수만 보고 주제를 정하면 언젠가 그런 걸 쓴다.
- 골든 패턴 어휘(free tier/pricing/LLM/model/API/automation/workflow)를 후보 문안에
  심어 confidence 80 게이트를 통과시킨다. 이걸 안 하면 글은 다 써놓고
  `article_candidate_not_generated`로 발행만 막힌다(2026-08-26 실측).
"""
from __future__ import annotations

import html
import logging
import os
import re
from typing import Any

import requests

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.blog_language import is_english_mode

logger = logging.getLogger(__name__)

_SE_ENDPOINT = "https://api.stackexchange.com/2.3/search/advanced"
# view_count / score / answer_count / link 를 포함시키는 필터.
_SE_FILTER = "!nNPvSNdWme"
_TIMEOUT = 15
_UA = {"User-Agent": "holyyomiai-topic-research/1.0 (+https://holyyomiai.blogspot.com)"}

# 주의: `gemini-api`는 Stack Overflow에 존재하지 않는 태그라 조용히 0건을 돌려준다.
# 실제 태그는 `google-gemini`다 (2026-08-31 실측).
_DEFAULT_TAGS = ("openai-api", "google-gemini", "langchain", "ollama")

# 이 블로그의 니치: 무료 티어·한도·요금·API 에러·접근 문제.
_NICHE_RE = re.compile(
    r"\b(429|403|404|401|503|quota|rate.?limit|limit|free|billing|pricing|cost|"
    r"exceeded|context length|token|timeout|not found|permission|denied|"
    r"location|unavailable|overloaded|api key)\b",
    re.I,
)
# 니치처럼 보이지만 우리 독자의 질문이 아닌 것들.
_EXCLUDE_RE = re.compile(
    r"\b(importerror|modulenotfound|no module|sslerror|certificate|"
    r"pip install|conda|lora|peft|checkpoint|fine.?tun|embedding|tokenizer\.|"
    r"dataset|nsfw|trainer|dockerfile|kubernetes|android studio|unity)\b",
    re.I,
)

_MIN_VIEWS = 3000
_MAX_TITLE = 140

# ---------------------------------------------------------------- consumer 소스
_AUTOCOMPLETE = "https://suggestqueries.google.com/complete/search"

# 일반 독자가 실제로 쓰는 도구들. 새 도구가 뜨면 여기에 추가한다.
_CONSUMER_TOOLS = ("chatgpt", "gemini", "claude ai", "copilot", "perplexity")

# 일반 독자가 실제로 치는 질문 틀. 전부 2026-08-31 자동완성 실측으로 고른 것이고,
# 개발자 전용 표현(API/SDK/엔드포인트)은 일부러 하나도 넣지 않았다.
_CONSUMER_PATTERNS = (
    "is {tool} free",
    "{tool} free limit",
    "why is {tool} not working",
    "is {tool} worth it",
    "how to cancel {tool}",
    "{tool} vs",
    "how to use {tool} for free",
    "{tool} limit reached",
)

# 자동완성이 엉뚱한 데로 새는 것을 막는다. 실측에서 'free tier limit 0 gemini'가
# 체이스 신용카드 한도 제안을 끌고 온 적이 있다.
_CONSUMER_EXCLUDE_RE = re.compile(
    r"\b(credit limit|chase|loan|mortgage|insurance|casino|porn|nsfw|"
    r"janitor|crypto|stock|betting)\b",
    re.I,
)

# 형제 제안에 이 말이 섞여 있으면 "사람들이 벤더 홍보 말고 진짜 답을 찾는 주제"라는
# 신호다 — 그 씨앗에서 나온 다른 후보들에 가산점을 준다.
#
# 단, 이 말이 붙은 제안 자체를 후보로 삼지는 않는다. "chatgpt free limits reddit"으로는
# 레딧 스레드를 이길 수 없고 글 제목으로도 이상하다. 2026-08-31 첫 실행에서 상위 8개가
# 전부 reddit 접미사로 채워져서 발견한 문제다 — 신호와 타깃을 구분해야 한다.
_HUMAN_ANSWER_SIGNAL_RE = re.compile(r"\b(reddit|quora|forum)\b", re.I)
# 후보 제목에서 아예 배제할 접미사·군더더기.
_TITLE_REJECT_RE = re.compile(r"\b(reddit|quora|forum|youtube|tiktok)\b", re.I)


def _autocomplete(query: str) -> list[str]:
    """구글 자동완성 제안. 실패하면 빈 리스트(비치명)."""
    try:
        response = requests.get(
            _AUTOCOMPLETE,
            params={"client": "firefox", "hl": "en", "gl": "us", "q": query},
            headers=_UA, timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
        return [str(s) for s in (payload[1] if len(payload) > 1 else [])]
    except Exception:  # noqa: BLE001 — 수요 발굴 실패가 발행을 막으면 안 된다
        return []


def _consumer_tools() -> tuple[str, ...]:
    raw = (os.getenv("CONSUMER_DEMAND_TOOLS", "") or "").strip()
    if not raw:
        return _CONSUMER_TOOLS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or _CONSUMER_TOOLS


def fetch_consumer_demand(
    history_records: list[dict[str, Any]] | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """일반 독자가 실제로 검색하는 질문. 자동완성 포화도로 순위를 매긴다.

    개발자 소스와 달리 절대 조회수는 없다. 대신 제안 개수(0~10)가 포화도이고,
    10이면 구글이 그 표현으로 검색이 충분히 많다고 보는 것이다. 실측에서 일반
    독자 질문 10개가 전부 10/10이었다.
    """
    if not _enabled():
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    for tool in _consumer_tools():
        for pattern in _CONSUMER_PATTERNS:
            seed = pattern.format(tool=tool)
            suggestions = _autocomplete(seed)
            if len(suggestions) < 5:
                # 포화도가 낮으면 그 표현은 대중이 잘 안 친다는 뜻.
                continue
            # 형제 제안에 reddit/quora가 섞여 있으면 "진짜 답을 찾는 주제"라는 신호.
            wants_human = any(_HUMAN_ANSWER_SIGNAL_RE.search(s) for s in suggestions)
            for suggestion in suggestions:
                title = suggestion.strip()
                if not title or len(title) > _MAX_TITLE:
                    continue
                if _CONSUMER_EXCLUDE_RE.search(title) or _TITLE_REJECT_RE.search(title):
                    continue
                # 도구 이름이 빠진 제안은 주제가 흐려진다.
                if tool.split()[0] not in title.lower():
                    continue
                norm = _normalize(title)
                if norm in seen:
                    continue
                if _already_covered(title, history_records):
                    continue
                seen.add(norm)
                found.append({
                    "title": title,
                    "saturation": len(suggestions),
                    "human_answer_wanted": wants_human,
                    "seed": seed,
                    "tool": tool,
                })

    # 포화도 우선, '진짜 사람 답을 찾는' 주제에 가산점.
    found.sort(
        key=lambda r: r["saturation"] * (1.2 if r["human_answer_wanted"] else 1.0),
        reverse=True,
    )
    # 한 도구가 상위를 독식하면 매일 ChatGPT 글만 나온다. 도구당 2개로 제한해
    # 순환시킨다(2026-08-31 첫 실행에서 상위 8개가 전부 chatgpt였다).
    per_tool: dict[str, int] = {}
    diversified: list[dict[str, Any]] = []
    for row in found:
        used = per_tool.get(row["tool"], 0)
        if used >= 2:
            continue
        # 같은 실행 안에서도 사실상 같은 글이 두 번 뽑히지 않게 한다.
        if any(_is_near_duplicate(row["title"], kept["title"]) for kept in diversified):
            continue
        per_tool[row["tool"]] = used + 1
        diversified.append(row)
    return diversified[:limit]


def _enabled() -> bool:
    return str(os.getenv("ENABLE_QUESTION_DEMAND", "true")).strip().lower() not in {
        "false", "0", "no", "off",
    }


def _tags() -> tuple[str, ...]:
    raw = (os.getenv("QUESTION_DEMAND_TAGS", "") or "").strip()
    if not raw:
        return _DEFAULT_TAGS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or _DEFAULT_TAGS


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _slot_id(title: str) -> str:
    """후보의 cluster_slot 값. 절대 빈 문자열이면 안 된다.

    is_cluster_candidate()는 topic_cluster 뿐 아니라 cluster_slot이 비어있지
    않은지도 본다. 여기가 비면 그 후보는 클러스터 후보로 인정받지 못해
    (a) 뉴스 후보가 있는 날 후보 풀 좁히기에서 통째로 버려지고
    (b) _choose_selected_candidate의 확정 선택도 못 받는다 —
    로그상 "주입은 됐는데 선택이 안 되는" 조용한 실패가 된다.
    제목이 기호뿐이라 정규화 결과가 비는 경우를 대비한 폴백이다.
    """
    slug = _normalize(title)[:60].strip().replace(" ", "_")
    return slug or "live_demand_topic"


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "do", "does", "how", "what", "why", "to",
    "for", "of", "on", "in", "it", "my", "your", "and", "or", "with", "get",
})


def _significant_tokens(text: str) -> frozenset[str]:
    """의미 단어만. 복수형은 단수로 눕혀서 'limits'와 'limit'을 같게 본다.

    이 어간 처리가 없으면 'chatgpt free limits'와 'chatgpt free limit'이 서로
    다른 주제로 통과해 사실상 같은 글이 두 번 나간다(테스트가 실제로 잡아냈다).
    """
    tokens = set()
    for raw in _normalize(text).split():
        if len(raw) <= 1 or raw in _STOPWORDS:
            continue
        if len(raw) > 3 and raw.endswith("es") and not raw.endswith("ses"):
            raw = raw[:-2]
        elif len(raw) > 3 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        tokens.add(raw)
    return frozenset(tokens)


def _is_near_duplicate(title: str, other: str) -> bool:
    """두 제목이 사실상 같은 글인지.

    'chatgpt free limits'와 'chatgpt free limits per day'는 자동완성에서는 다른
    제안이지만 같은 글이 된다. 한쪽의 핵심 단어가 다른 쪽에 전부 들어있으면
    같은 것으로 본다 (2026-08-31 실측: 첫 실행 후보 8개가 도구별 free limits /
    free limit per day 쌍이었다).
    """
    a, b = _significant_tokens(title), _significant_tokens(other)
    if not a or not b:
        return False
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    if len(smaller) < 2:
        return False
    return len(smaller & larger) / len(smaller) >= 0.85


def _already_covered(title: str, history_records: list[dict[str, Any]] | None) -> bool:
    """원장에 이미 다룬 주제인지. 에러 코드 + 벤더 조합으로 대조한다."""
    if not history_records:
        return False
    norm = _normalize(title)
    tokens = {t for t in norm.split() if len(t) > 2}
    # 판정에 쓰는 것은 '무엇에 대한 무슨 에러인가' 두 축이다.
    codes = {t for t in tokens if t.isdigit() and len(t) == 3}
    vendors = tokens & {
        "openai", "chatgpt", "gpt", "gemini", "google", "claude", "anthropic",
        "openrouter", "ollama", "huggingface", "mistral", "llama", "groq",
    }
    for record in history_records:
        fields = [str(record.get(k) or "") for k in
                  ("title", "selected_title", "selected_topic", "topic", "search_demand_topic")]
        text = " ".join(f for f in fields if f)
        if not text.strip():
            continue
        # 1) 같은 벤더 + 같은 에러 코드 = 같은 글 (개발자 주제).
        hist = set(_normalize(text).split())
        if codes and vendors and (codes & hist) and (vendors & hist):
            return True
        # 2) 핵심 단어가 거의 겹치면 같은 글 (일반 독자 주제).
        for field in fields:
            if field and _is_near_duplicate(title, field):
                return True
    return False


def fetch_question_demand(
    history_records: list[dict[str, Any]] | None = None,
    *,
    tags: tuple[str, ...] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """오늘 쓸 만한 질문들을 수요 순으로. 실패하면 빈 리스트(비치명)."""
    if not _enabled():
        return []
    found: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for tag in (tags or _tags()):
        try:
            response = requests.get(
                _SE_ENDPOINT,
                params={
                    "site": "stackoverflow", "tagged": tag, "sort": "votes",
                    "order": "desc", "pagesize": 30, "filter": _SE_FILTER,
                },
                headers=_UA, timeout=_TIMEOUT,
            )
            if response.status_code != 200:
                logger.info("question_demand: %s HTTP %s (skip)", tag, response.status_code)
                continue
            items = response.json().get("items") or []
        except Exception as exc:  # noqa: BLE001 — 수요 발굴 실패가 발행을 막으면 안 된다
            logger.info("question_demand: %s failed (skip): %s", tag, exc)
            continue

        for item in items:
            title = html.unescape(str(item.get("title") or "")).strip()
            views = item.get("view_count") or 0
            if not title or len(title) > _MAX_TITLE or views < _MIN_VIEWS:
                continue
            if not _NICHE_RE.search(title) or _EXCLUDE_RE.search(title):
                continue
            norm = _normalize(title)
            if norm in seen_titles:
                continue
            if _already_covered(title, history_records):
                continue
            seen_titles.add(norm)
            found.append({
                "title": title,
                "views": int(views),
                "answered": bool(item.get("is_answered")),
                "url": str(item.get("link") or ""),
                "tag": tag,
            })

    # 수요가 큰 순. 답이 없는 질문(=공백)에 가산점.
    found.sort(key=lambda r: r["views"] * (1.25 if not r["answered"] else 1.0), reverse=True)
    return found[:limit]


def to_candidate(question: dict[str, Any]) -> NewsCandidate:
    """발굴한 질문 하나를 발행 후보로. 클러스터 후보와 같은 계약을 따른다."""
    title = question["title"]
    # 골든 패턴 어휘를 실어 confidence 80 게이트를 넘긴다. 이 문구들이 곧
    # 매칭 텍스트(topic + search_demand_topic + 질문 2개 + sample_titles)가 된다.
    questions = [
        f"What does this mean: {title}?",
        f"How do you fix it on a free tier LLM API model?",
        "Which AI API errors should an automation workflow retry?",
    ]
    descriptive = f"{title} — what the AI model error means on free tier LLM APIs and how to fix it"
    search_angle: dict[str, Any] = {
        "original_topic": title,
        "search_demand_topic": title,
        "reader_search_questions": questions,
        "click_reason": (
            "People paste this exact error into Google and into an LLM, and the top "
            "results are forum threads and issue trackers rather than an answer."
        ),
        "reader_benefit": "What actually causes it, how to confirm which cause you have, and the fix for each.",
        "urgency_reason": "Free-tier limits and model availability change without notice; a current answer wins the click.",
        "content_promise": "Name the causes, show how to tell them apart, and give the fix for each.",
        "angle_type": "how_to",
        "should_transform_title": True,
        "commercial_support_signal": False,
        "generic_support_keyword": "",
        "public_benefit_keyword": "",
        "public_benefit_confidence": "none",
        "public_benefit_promotion_blocked": False,
    }
    content_angle = {
        "content_type": "ai_work_tip",
        "reader_question": questions[0],
        "reader_loss": search_angle["click_reason"],
        "practical_value": search_angle["reader_benefit"],
        "example_needed": True,
    }
    return NewsCandidate(
        topic=title,
        category="tech",
        summary=f"{descriptive}. Measured demand: {question['views']:,} views on Stack Overflow.",
        source_hint="evergreen_fallback",
        published_at=None,
        url=None,
        raw={
            # cluster_service와 같은 이유로 source_type은 evergreen_fallback을 재사용한다
            # (새 값을 만들면 신선도·자동발행 허용·골든패턴 분기를 전부 다시 통과시켜야 하고
            #  하나만 놓쳐도 "글은 썼는데 발행만 안 되는" 조용한 0건이 된다).
            "source": "question_demand",
            "source_type": "evergreen_fallback",
            "is_test_candidate": False,
            "publish_allowed": True,
            "evergreen_axis": "ai_automation",
            "evergreen_reason": (
                f"Live-measured question demand ({question['views']:,} views"
                f"{', unanswered' if not question['answered'] else ''})."
            ),
            "evergreen_fallback": True,
            "is_stale": False,
            # 클러스터와 같은 면제를 받기 위한 마커. cluster_slot은 주제 자체를 쓴다 —
            # 원장 진행 판정이 아니라 중복 방지 표식으로만 쓰인다.
            "topic_cluster": True,
            "cluster_key": "question_demand_live",
            "cluster_slot": _slot_id(title),
            "cluster_is_pillar": False,
            "cluster_name": "Live question demand",
            "question_demand_views": question["views"],
            "question_demand_answered": question["answered"],
            "question_demand_source_url": question["url"],
            "target_reader": (
                "developers and solo builders running small automated jobs (US/UK/CA/IN)"
                if is_english_mode()
                else "직접 자동화를 돌리는 개발자·1인 운영자"
            ),
            "query_group": "ai_automation",
            "topic_group": "ai_work",
            "content_angle": content_angle,
            "search_angle": search_angle,
            "search_demand_topic": title,
            "sample_titles": [descriptive],
            "reader_search_questions": questions,
            "click_reason": search_angle["click_reason"],
            "reader_benefit": search_angle["reader_benefit"],
            "urgency_reason": search_angle["urgency_reason"],
            "content_promise": search_angle["content_promise"],
            "angle_type": "how_to",
        },
    )


def consumer_to_candidate(question: dict[str, Any]) -> NewsCandidate:
    """일반 독자 질문 하나를 발행 후보로.

    개발자 후보와 문안 자체가 다르다 — 여기서는 독자가 프로그래머가 아니라고
    가정하고, 글이 답해야 할 질문도 평범한 말로 적는다. 이 문안이 그대로 글의
    각도가 되므로, 여기서 어려운 말을 쓰면 어려운 글이 나온다.
    """
    title = question["title"].strip()
    display = title[0].upper() + title[1:] if title else title
    questions = [
        f"{display}?",
        "What do you actually get on the free plan, and what needs paying?",
        "Which option is the better pick for everyday use?",
    ]
    descriptive = (
        f"{display} - a plain-English answer with current pricing, free tier limits, "
        f"and what most people should pick"
    )
    search_angle: dict[str, Any] = {
        "original_topic": display,
        "search_demand_topic": title,
        "reader_search_questions": questions,
        "click_reason": (
            "Search results for this are vendor marketing pages and outdated posts, "
            "so people add 'reddit' to the query just to find a straight answer."
        ),
        "reader_benefit": "A straight answer with the current numbers and a clear recommendation.",
        "urgency_reason": "AI tool pricing and free limits change often; a current answer wins the click.",
        "content_promise": "Answer the question directly, show the current numbers, and say who should pick what.",
        "angle_type": "money_compare",
        "should_transform_title": True,
        "commercial_support_signal": False,
        "generic_support_keyword": "",
        "public_benefit_keyword": "",
        "public_benefit_confidence": "none",
        "public_benefit_promotion_blocked": False,
    }
    content_angle = {
        "content_type": "ai_work_tip",
        "reader_question": questions[0],
        "reader_loss": search_angle["click_reason"],
        "practical_value": search_angle["reader_benefit"],
        "example_needed": True,
    }
    return NewsCandidate(
        topic=title,
        category="tech",
        summary=f"{descriptive}. Measured demand: {question['saturation']}/10 autocomplete saturation.",
        source_hint="evergreen_fallback",
        published_at=None,
        url=None,
        raw={
            "source": "consumer_demand",
            "source_type": "evergreen_fallback",
            "is_test_candidate": False,
            "publish_allowed": True,
            "evergreen_axis": "ai_automation",
            "evergreen_reason": (
                f"Live-measured consumer search demand "
                f"({question['saturation']}/10 autocomplete saturation)."
            ),
            "evergreen_fallback": True,
            "is_stale": False,
            "topic_cluster": True,
            "cluster_key": "consumer_demand_live",
            "cluster_slot": _slot_id(title),
            "cluster_is_pillar": False,
            "cluster_name": "Live consumer demand",
            "consumer_demand_saturation": question["saturation"],
            "consumer_demand_seed": question["seed"],
            # 이 후보는 일반 독자용이다. 글쓰기 쪽이 이 표시를 보고 눈높이를 맞춘다.
            "audience_level": "general",
            "target_reader": (
                "everyday AI tool users who are not programmers (US/UK/CA/IN)"
                if is_english_mode()
                else "프로그래머가 아닌 일반 AI 도구 사용자"
            ),
            "query_group": "ai_automation",
            "topic_group": "ai_work",
            "content_angle": content_angle,
            "search_angle": search_angle,
            "search_demand_topic": title,
            "sample_titles": [descriptive],
            "reader_search_questions": questions,
            "click_reason": search_angle["click_reason"],
            "reader_benefit": search_angle["reader_benefit"],
            "urgency_reason": search_angle["urgency_reason"],
            "content_promise": search_angle["content_promise"],
            "angle_type": "money_compare",
        },
    )


# 이 글자 수 미만의 팩트만 모이는 주제는 쓸 자료가 없다는 뜻이다.
# 기준선 근거(2026-09-01 실측): Exa 본문 수집을 정상화한 뒤 멀쩡한 주제는
# 6,000자 이상을 가져온다. 헤드라인만 잡히는 주제는 700~750자에 머문다.
# 그 사이인 1,500자를 경계로 둔다 — 헤드라인만 있는 주제는 확실히 걸러내되,
# 자료가 적당한 주제까지 버리지는 않는다.
_MIN_SOURCEABLE_FACT_CHARS = 1500


def _has_enough_facts(topic: str) -> bool:
    """이 주제로 실제 자료를 구할 수 있는지 미리 확인한다.

    2026-09-01 드라이런 실측: 'chatgpt free limit for chats with attachments'는
    자동완성 포화도 10/10으로 뽑혔지만 실제 수집된 팩트가 737자(Exa 2건)뿐이었다.
    모델은 쓸 게 없으니 헤지로 채웠고, 헤지 포화 검증기가 두 번 연속 거부해
    결국 그날 글이 통째로 안 나왔다.

    검색 수요가 크다고 답할 거리가 있는 건 아니다 — 세부 주제일수록 검색은
    되는데 공개된 자료는 없다. 그래서 수요와 별개로 '조달 가능성'을 따로 잰다.
    실패(네트워크·쿼터)는 통과로 처리한다. 자료 조회가 안 된다는 이유로 발행을
    막으면, 고치려던 문제보다 큰 문제를 만든다.
    """
    try:
        from blogspot_automation.services.llm_content_service import LlmContentService

        facts = LlmContentService()._gather_facts(topic) or ""
        enough = len(facts.strip()) >= _MIN_SOURCEABLE_FACT_CHARS
        if not enough:
            logger.info(
                "question_demand: 자료 부족으로 후보 제외 — '%s' (팩트 %d자)",
                topic[:60], len(facts.strip()),
            )
        return enough
    except Exception as exc:  # noqa: BLE001 — 조달 확인 실패는 비치명
        logger.info("question_demand: 자료 확인 실패 (통과로 간주) — %s", exc)
        return True


def _passes_golden_pattern(candidate: NewsCandidate) -> bool:
    """이 후보가 골든 패턴 게이트를 통과하는지 미리 확인한다.

    슬롯 뱅크였다면 사람이 손으로 문안을 고쳐 confidence를 올릴 수 있었지만,
    매일 발굴은 제목을 미리 알 수 없다. 실측(2026-08-31): 발굴된 8개 중 2개가
    confidence 25로 기준(80) 미달이었다. 그대로 내보내면 글은 다 써놓고
    `article_candidate_not_generated`로 발행만 막히는 조용한 실패가 된다.

    그래서 **통과하는 후보만 내보낸다**. 게이트 판정은 파이프라인이 나중에 쓰는
    것과 같은 서비스로 하므로 두 판정이 어긋날 수 없다.
    """
    try:
        from blogspot_automation.services.golden_article_preview_service import (
            GoldenArticlePreviewService,
        )

        raw = candidate.raw
        summary = " ".join(
            part for part in (
                str(raw.get("search_demand_topic") or ""),
                " ".join(list(raw.get("reader_search_questions") or [])[:2]),
                str((raw.get("content_angle") or {}).get("reader_question") or ""),
                " ".join(list(raw.get("sample_titles") or [])[:3]),
            ) if part
        )
        result = GoldenArticlePreviewService().build_preview(
            topic=str(raw.get("search_demand_topic") or ""),
            content_type="ai_work_tip",
            topic_group="ai_work",
            summary=summary,
            candidate_raw=raw,
        )
        match = result.get("pattern_match") or {}
        return bool(match.get("matched") and result.get("ready_for_review"))
    except Exception as exc:  # noqa: BLE001 — 확인 실패가 발행을 막으면 안 된다
        logger.info("question_demand: 골든패턴 사전확인 실패 (통과로 간주): %s", exc)
        return True


def collect_candidates(
    history_records: list[dict[str, Any]] | None = None,
    *,
    max_candidates: int = 1,
) -> list[NewsCandidate]:
    """오늘의 질문 후보. 실패·전멸 시 빈 리스트를 돌려주고 기존 경로가 돈다.

    일반 독자(consumer) 질문을 먼저 시도하고, 없을 때만 개발자(Stack Overflow)
    질문으로 내려간다. 순서를 바꾸면 글이 다시 어려워진다 — 2026-08-31에 실제로
    그랬다(발행 글 첫 줄이 깃허브 이슈 번호였다).
    """
    accepted: list[NewsCandidate] = []
    skipped = 0

    def _take(questions: list[dict[str, Any]], builder, label: str) -> None:
        nonlocal skipped
        for question in questions:
            if len(accepted) >= max_candidates:
                return
            candidate = builder(question)
            if not _passes_golden_pattern(candidate):
                skipped += 1
                logger.info("%s: 골든패턴 미달로 건너뜀 — '%s'", label, question["title"][:70])
                continue
            # 자료 조달 확인은 골든패턴 뒤에 둔다 — 이쪽이 네트워크를 쓰므로
            # 어차피 탈락할 후보에 API 호출을 낭비하지 않는다.
            if not _has_enough_facts(question["title"]):
                skipped += 1
                continue
            logger.info("%s: '%s' 선택", label, question["title"][:70])
            accepted.append(candidate)

    # 1순위 — 일반 독자.
    try:
        _take(fetch_consumer_demand(history_records), consumer_to_candidate, "consumer_demand")
    except Exception as exc:  # noqa: BLE001
        logger.warning("consumer_demand failed (무시): %s", exc)

    # 2순위 — 개발자. 1순위가 전멸했을 때만.
    if not accepted:
        try:
            _take(fetch_question_demand(history_records), to_candidate, "question_demand")
        except Exception as exc:  # noqa: BLE001
            logger.warning("question_demand failed (무시): %s", exc)

    if not accepted:
        logger.info("question_demand: 오늘 새로 발굴된 질문 없음 — 기존 경로로 간다")
    if skipped:
        logger.info("question_demand: %d개는 골든패턴 미달로 제외됨", skipped)
    return accepted
