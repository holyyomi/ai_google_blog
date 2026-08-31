"""매 실행마다 '지금 사람들이 실제로 묻는 질문'을 새로 발굴한다.

왜 슬롯 뱅크가 아니라 매일 발굴인가 (2026-08-31 요미님 지시)
------------------------------------------------------------
"미리 채워놓고 하면 더 나쁜 글이 올라간다" — 실제 운영 경험이고, 이 프로젝트의
CLAUDE.md 주제 선정 정책과도 원래 같은 말이다: **"고정 주제 후보 금지. 매 실행마다
신선 발굴이 1순위, 뱅크는 폴백일 뿐."** 미리 적어둔 슬롯은 몇 주 전 판단을 그대로
굳혀버린다 — 가격이 바뀌고 모델명이 바뀌고 에러 문구가 바뀌어도 문안은 그대로고,
글쓰는 쪽은 오늘의 근거를 조사하는 대신 이미 정해진 각도에 맞춰 칸을 채우게 된다.

그래서 여기서는 **발행 시점에** 실측 수요를 다시 긁어 그날의 주제를 고른다.

수요 신호 (tools/demand_mine.py에서 검증한 것과 같은 소스)
-----------------------------------------------------------
Stack Exchange API가 유일하게 **질문당 절대 조회수**를 준다. Google Autocomplete는
"이 말이 검색되긴 하는가"만 알려줄 뿐 크기를 모르고, 긴 질문형에는 아예 빈 배열을
돌려준다(실측). 그래서 크기 판정은 Stack Overflow 조회수로 한다.

에러 메시지를 노리는 이유: 사람이 검색창에 치는 문장이자 LLM에게 그대로 복붙해
묻는 문장이고, 상위 결과가 포럼 스레드·GitHub 이슈뿐이라 제대로 답한 문서가 비어
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
    if not codes and not vendors:
        return False
    for record in history_records:
        text = " ".join(str(record.get(k) or "") for k in
                        ("title", "selected_title", "selected_topic", "topic", "search_demand_topic"))
        hist = set(_normalize(text).split())
        if not hist:
            continue
        if codes and vendors and (codes & hist) and (vendors & hist):
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
            "cluster_slot": _normalize(title)[:60].replace(" ", "_"),
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
    """오늘의 질문 후보. 실패·전멸 시 빈 리스트를 돌려주고 기존 경로가 돈다."""
    try:
        questions = fetch_question_demand(history_records)
    except Exception as exc:  # noqa: BLE001
        logger.warning("question_demand failed (무시): %s", exc)
        return []
    if not questions:
        logger.info("question_demand: 오늘 새로 발굴된 질문 없음 — 기존 경로로 간다")
        return []

    accepted: list[NewsCandidate] = []
    skipped = 0
    for question in questions:
        if len(accepted) >= max_candidates:
            break
        candidate = to_candidate(question)
        if not _passes_golden_pattern(candidate):
            skipped += 1
            logger.info(
                "question_demand: 골든패턴 미달로 건너뜀 — '%s'", question["title"][:70]
            )
            continue
        logger.info(
            "question_demand: '%s' (views=%s, answered=%s, tag=%s)",
            question["title"][:70], question["views"], question["answered"], question["tag"],
        )
        accepted.append(candidate)

    if skipped:
        logger.info("question_demand: %d개는 골든패턴 미달로 제외됨", skipped)
    return accepted
