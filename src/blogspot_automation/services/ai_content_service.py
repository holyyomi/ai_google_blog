# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any

from blogspot_automation.config import Settings
from blogspot_automation.services.topic_selection_service import SelectedTopicResult
from blogspot_automation.storage import (
    BlogWorkItem,
    BlogWorkItemRepository,
    BriefRecord,
    BriefRecordRepository,
    PublishStatus,
)
from blogspot_automation.services.qa_service import _strip_html
from blogspot_automation.services.seo_policy import (
    has_unverified_experience_or_income_claim,
    normalize_hashtags,
    normalize_labels,
    prepare_blogspot_html,
)
from blogspot_automation.utils.network import post_json_with_retry

logger = logging.getLogger(__name__)

_CONTENT_TYPE_CYCLE = ["A", "B", "C", "D"]
READER_LEVELS = ["beginner", "intermediate", "advanced"]

# data/ 디렉토리는 프로젝트 루트 기준
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_TOOLS_DB_PATH = _DATA_DIR / "tools_database.json"
_HISTORY_PATH = _DATA_DIR / "published_history.json"


def _load_tools_db() -> list[dict[str, Any]]:
    """tools_database.json에서 도구 목록을 로드한다. 실패 시 빈 리스트 반환."""
    try:
        return json.loads(_TOOLS_DB_PATH.read_text(encoding="utf-8")).get("tools", [])
    except Exception as exc:
        logger.warning("tools_database.json 로드 실패: %s", exc)
        return []


def _select_tool_for_today(reader_level: str = "", content_type: str = "") -> dict[str, Any] | None:
    """최근 7일 사용 도구 제외 + 30일 내 동일 (tool+레벨+타입) 조합 제외 후 랜덤 선택."""
    tools = _load_tools_db()
    if not tools:
        return None

    recently_used_7d: set[str] = set()
    recent_combos_30d: set[tuple[str, str, str]] = set()
    try:
        history: list[dict[str, str]] = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        cutoff_7 = date.today() - timedelta(days=7)
        cutoff_30 = date.today() - timedelta(days=30)
        for entry in history:
            entry_date = _safe_parse_date(entry.get("date", ""))
            if entry_date >= cutoff_7:
                recently_used_7d.add(entry.get("tool_id", ""))
            if entry_date >= cutoff_30:
                recent_combos_30d.add((
                    entry.get("tool_id", ""),
                    entry.get("reader_level", ""),
                    entry.get("content_type", ""),
                ))
    except Exception:
        pass

    # 우선: 7일 미사용 + 30일 내 combo 없는 도구
    candidates = [
        t for t in tools
        if t.get("id") not in recently_used_7d
        and (t.get("id"), reader_level, content_type) not in recent_combos_30d
    ]
    if not candidates:
        # fallback: combo만 체크
        candidates = [
            t for t in tools
            if (t.get("id"), reader_level, content_type) not in recent_combos_30d
        ]
    if not candidates:
        candidates = tools  # 모두 사용된 경우 전체에서 선택

    selected = random.choice(candidates)
    logger.info(
        "오늘의 AI 도구 선택: %s (%s) [level=%s type=%s]",
        selected.get("id"), selected.get("name_ko"), reader_level, content_type,
    )
    return selected


def _record_tool_used(tool_id: str, *, content_type: str = "", reader_level: str = "", section_combo: str = "") -> None:
    """발행 성공 후 published_history.json에 기록을 추가하고 30일 이전 항목을 정리한다."""
    try:
        try:
            history: list[dict[str, str]] = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = []

        history.append({
            "tool_id": tool_id,
            "date": date.today().isoformat(),
            "content_type": content_type,
            "reader_level": reader_level,
            "section_combo": section_combo,
        })

        # 30일 이전 기록 정리
        cutoff = date.today() - timedelta(days=30)
        history = [
            e for e in history
            if _safe_parse_date(e.get("date", "")) >= cutoff
        ]

        _HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "published_history.json 업데이트: tool_id=%s level=%s type=%s, 총 %d건",
            tool_id, reader_level, content_type, len(history),
        )
    except Exception as exc:
        logger.warning("published_history.json 업데이트 실패: %s", exc)


def _safe_parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.min


def _select_reader_level() -> str:
    """최근 3회 연속 같은 레벨 방지 후 reader_level 랜덤 선택."""
    try:
        history: list[dict[str, str]] = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        # 최근 항목부터 최대 3개의 레벨 추출
        recent = [
            e.get("reader_level", "")
            for e in reversed(history)
            if e.get("reader_level")
        ][:3]
        # 최근 3개가 모두 같은 레벨이면 해당 레벨 제외
        if len(recent) == 3 and len(set(recent)) == 1:
            blocked = recent[0]
            candidates = [lv for lv in READER_LEVELS if lv != blocked]
        else:
            candidates = READER_LEVELS
    except Exception:
        candidates = READER_LEVELS

    selected = random.choice(candidates)
    logger.info("독자 레벨 선택: %s", selected)
    return selected


def _load_tag_lists() -> tuple[list[str], list[str]]:
    """tools_database.json에서 (allowed_tags_whitelist, banned_tags) 반환."""
    try:
        db = json.loads(_TOOLS_DB_PATH.read_text(encoding="utf-8"))
        return db.get("allowed_tags_whitelist", []), db.get("banned_tags", [])
    except Exception as exc:
        logger.warning("태그 목록 로드 실패: %s", exc)
        return [], []


def filter_tags(
    generated_tags: list[str],
    whitelist: list[str],
    banned: list[str],
    fallback_tags: list[str],
) -> list[str]:
    """LLM 생성 태그를 필터링한다.
    banned 제거 → whitelist 교집합 → 비어있으면 fallback → 최대 15개.
    """
    filtered = [t for t in generated_tags if t not in banned and (not whitelist or t in whitelist)]
    if not filtered:
        filtered = [t for t in fallback_tags if t not in banned]
    return normalize_labels(filtered)


def post_process_html(html: str) -> str:
    """LLM 생성 HTML 후처리: 이미지 제거, 줄바꿈 정리, 금지 텍스트 제거."""
    import re as _re

    # ── 이미지 완전 제거 (Blogger 자동 래퍼 방지) ─────────────────
    # <img> 태그 자체 제거 → Blogger imageanchor 래핑 원천 차단
    html = _re.sub(r'<img[^>]*/?>',  '', html, flags=_re.IGNORECASE)
    # <a imageanchor="1">...</a> → 내부 내용만 유지
    html = _re.sub(r'<a[^>]*imageanchor[^>]*>(.*?)</a>', r'\1', html, flags=_re.DOTALL | _re.IGNORECASE)
    # <figcaption> 전체 제거
    html = _re.sub(r'<figcaption[^>]*>.*?</figcaption>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    # <figure>...</figure> → 내부 내용만 유지
    html = _re.sub(r'<figure[^>]*>(.*?)</figure>', r'\1', html, flags=_re.DOTALL | _re.IGNORECASE)
    # imageanchor, caption 속성 포함 태그 제거
    html = _re.sub(r'<[^>]*(imageanchor|data-caption)[^>]*>', '', html, flags=_re.IGNORECASE)

    # ── 금지 텍스트 — 링크로 감싸진 경우까지 제거 ───────────────
    _banned_phrases = [
        '머신러닝 및 인공지능', '머신러닝및인공지능',
        '혁신적입니다', '주목받고 있습니다', '각광받고 있습니다',
        '눈에 띄게 발전', '급속한 발전', '놀라운 발전',
    ]
    for phrase in _banned_phrases:
        # <a ...>phrase</a> 형태로 감싸진 링크 태그째 제거
        html = _re.sub(
            rf'<a[^>]*>\s*{_re.escape(phrase)}\s*</a>',
            '', html, flags=_re.IGNORECASE
        )
        # 평문 텍스트 제거
        html = html.replace(phrase, '')

    # ── 고립 카테고리/라벨 텍스트 제거 ──────────────────────────
    # LLM이 문장 끝에 붙이는 카테고리 잔재 텍스트 (예: "비즈니스 프로세스", "AI자동화" 등)
    # 패턴: 태그 닫힘 직후 또는 문장 끝에 단독으로 붙은 2~10자 한글 명사 덩어리
    _isolated_labels = [
        '비즈니스 프로세스', '비즈니스프로세스',
        'AI자동화', 'AI글쓰기', 'AI이미지', 'AI코딩', 'AI영상편집', 'AI음성', 'AI프레젠테이션', 'AI생산성',
        '워크플로우', '노코드자동화',
    ]
    for label in _isolated_labels:
        html = _re.sub(
            rf'(?<=[.!?])\s*{_re.escape(label)}(?=\s*(<|$))',
            '', html, flags=_re.IGNORECASE
        )
        # 태그 사이에 단독으로 끼어있는 경우도 제거
        html = _re.sub(
            rf'(</\w+>)\s*{_re.escape(label)}\s*(<\w)',
            r'\1\2', html, flags=_re.IGNORECASE
        )

    # ── 영문 지시문/메타 코멘트 노출 방지 ────────────────────────
    _meta_patterns = [
        r'Example\s+explainer\s+block:.*?(?=<|$)',
        r'Example\s+checklist\s+block:.*?(?=<|$)',
        r'Example\s+practical\s+block:.*?(?=<|$)',
        r'주제의\s+정의와\s+범위를\s+.*?설명한다\.?',
        r'최근\s+맥락과\s+실무\s+영향도를\s+.*?설명한다\.?',
        r'초보자와\s+실무자가\s+.*?제시한다\.?',
        r'과장\s+없이\s+제약\s+조건과\s+.*?설명한다\.?',
        r'반복\s+가능한\s+워크플로와\s+.*?설명한다\.?',
        r'Emphasize\s+trigger-action.*?(?=<|$)',
        r'define\s+\w+\s+in\s+one\s+clear\s+paragraph.*?(?=<|$)',
    ]
    for pattern in _meta_patterns:
        html = _re.sub(pattern, '', html, flags=_re.IGNORECASE)

    # ── 마크다운 잔재 → HTML 변환 (LLM이 실수로 출력한 경우) ─────────
    # ### 제목 → <h2>
    html = _re.sub(r'^#{3,6}\s+(.+)$', r'<h2>\1</h2>', html, flags=_re.MULTILINE)
    # ## 제목 → <h2>
    html = _re.sub(r'^#{2}\s+(.+)$', r'<h2>\1</h2>', html, flags=_re.MULTILINE)
    # # 제목 → <h2> (단독 줄의 경우만)
    html = _re.sub(r'^#\s+(.+)$', r'<h2>\1</h2>', html, flags=_re.MULTILINE)
    # **볼드** → <strong>
    html = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    # *이탤릭* → <em>
    html = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # --- 수평선 → <hr>
    html = _re.sub(r'^-{3,}\s*$', r'<hr style="border:none;border-top:2px solid #E5E7EB;margin:28px 0;">', html, flags=_re.MULTILINE)
    # CHECKLIST - 제목 → <h3>
    html = _re.sub(r'^CHECKLIST\s*[-—]\s*(.+)$', r'<h3>\1</h3>', html, flags=_re.MULTILINE)

    # ── h2/h3/strong/table/FAQ 인라인 스타일 주입 (style 없는 태그만) ─
    html = _re.sub(
        r'<h2(?![^>]*style)([^>]*)>',
        r'<h2\1 style="font-size:21px;font-weight:800;color:#111;margin:36px 0 14px 0;padding-bottom:8px;border-bottom:2px solid #E85D04;">',
        html, flags=_re.IGNORECASE,
    )
    html = _re.sub(
        r'<h3(?![^>]*style)([^>]*)>',
        r'<h3\1 style="font-size:18px;font-weight:700;color:#1a1a1a;margin:24px 0 10px 0;">',
        html, flags=_re.IGNORECASE,
    )
    html = _re.sub(
        r'<strong(?![^>]*style)([^>]*)>',
        r'<strong\1 style="color:#E85D04;">',
        html, flags=_re.IGNORECASE,
    )
    html = _re.sub(
        r'<table(?![^>]*border-collapse)([^>]*)>',
        r'<table\1 style="width:100%;border-collapse:collapse;margin:18px 0;font-size:15px;">',
        html, flags=_re.IGNORECASE,
    )
    html = _re.sub(
        r'<th(?![^>]*background)([^>]*)>',
        r'<th\1 style="background:#F3F4F6;padding:10px 14px;border:1px solid #E2E8F0;font-weight:700;">',
        html, flags=_re.IGNORECASE,
    )
    # ul li: ✔ 접두사 (이미 특수문자로 시작하는 항목 제외)
    html = _re.sub(
        r'<li([^>]*)>(?!\s*(?:✔|✘|☐|☑|✅|⛔|→|📌|💡|🔍))',
        r'<li\1>✔ ',
        html, flags=_re.IGNORECASE,
    )

    # ── 중복 단락 제거 ────────────────────────────────────────────
    _paragraphs = _re.findall(r'<p[^>]*>(.*?)</p>', html, flags=_re.DOTALL)
    _seen_paragraphs: set[str] = set()
    for para_content in _paragraphs:
        _clean = _re.sub(r'\s+', ' ', para_content).strip()
        if len(_clean) < 30:
            continue
        if _clean in _seen_paragraphs:
            # 두 번째 이후 등장하는 중복 단락 제거
            html = html.replace(f'<p>{para_content}</p>', '', 1) if f'<p>{para_content}</p>' in html else html
        else:
            _seen_paragraphs.add(_clean)

    # ── 줄바꿈 정리 ───────────────────────────────────────────────
    html = _re.sub(r'(<br\s*/?>[\s]*){3,}', '<br><br>', html, flags=_re.IGNORECASE)
    html = _re.sub(r'(<br\s*/?>[\s]*){2,}(?=\s*<h[23])', '', html, flags=_re.IGNORECASE)
    html = _re.sub(r'([^>\n])(→)', r'\1<br>\2', html)

    # Keep Blogspot readers on-site. prepare_blogspot_html() appends internal links.

    # HTML entity artifact 정제 (LLM이 &#숫자 형태로 삽입한 코드를 unicode로 변환)
    from blogspot_automation.services.llm_content_service import _clean_entity_artifacts as _clean_ent
    html = _clean_ent(html)

    return prepare_blogspot_html(html)


def validate_content(
    title: str,
    content: str,
    tags: list[str],
    tool: dict[str, Any],
    banned_tags: list[str],
) -> dict[str, Any]:
    """생성된 콘텐츠가 품질 기준을 충족하는지 검증한다."""
    import re as _re

    errors: list[str] = []

    # 1. 제목에 도구명 포함
    name_ko = tool.get("name_ko", "") if tool else ""
    name_en = tool.get("name_en", "") if tool else ""
    if name_ko not in title and name_en not in title:
        errors.append("TITLE_MISSING_TOOL_NAME")

    # 2. "AI 도구" 단독 사용 과다 vs 도구명 언급 부족
    generic_count = len(_re.findall(r'AI\s*도구', content))
    specific_count = len(_re.findall(_re.escape(name_ko), content)) if name_ko else 0
    if generic_count > 3 and specific_count < generic_count:
        errors.append(f"TOO_GENERIC: AI도구 {generic_count}회 vs {name_ko} {specific_count}회")

    # 3. 본문 순수 텍스트 2500자 이상
    # 사유: 시스템 프롬프트가 3500자를 요구하는데 1200자만 통과시키면 LLM이 짧게 만들어도
    # 검증 통과 → "공부가 안 되는 짧은 글" 양산. 2500자로 상향해 LLM이 분량 채우도록 강제.
    text_only = _strip_html(content)
    if len(text_only) < 2500:
        errors.append(f"TOO_SHORT: {len(text_only)}자 (최소 2500)")

    # 4. 금지 태그 포함 여부
    bad_tags = [t for t in tags if t in banned_tags]
    if bad_tags:
        errors.append(f"BANNED_TAG: {bad_tags}")

    # 5. FAQ (비활성화 - 포맷 불일치 디버깅 중)
    faq_count = len(_re.findall(r'Q\d*[.:\s]', content))
    logger.warning("FAQ 감지: %d개 (체크 비활성화 중)", faq_count)

    # 6. STEP (비활성화 - 안정화 후 재활성화)
    step_count = len(_re.findall(r'STEP\s*\d+', content, _re.IGNORECASE))
    logger.warning("STEP 감지: %d개 (체크 비활성화 중)", step_count)

    # 7. 구체성 (비활성화 - 안정화 후 재활성화)
    specifics = _re.findall(
        r'\d+만원|\$\d+|크몽|탈잉|클래스101|위시켓|스마트스토어|Etsy|Shutterstock|Adobe|Audible|월\s*\d+',
        content,
    )
    logger.warning("구체성 감지: %d개 (체크 비활성화 중)", len(specifics))

    return {"passed": len(errors) == 0, "errors": errors}


def _reader_level_instruction(level: str) -> str:
    """선택된 reader_level에 맞는 구체적 작성 지시문을 반환한다."""
    if level == "beginner":
        return (
            "■ BEGINNER 작성 규칙:\n"
            "- 처음 나오는 기술 용어는 괄호로 설명 (예: API(앱 연결 인터페이스))\n"
            "- STEP은 7~8단계로 아주 작게 쪼개기, 각 STEP은 한 가지 행동만\n"
            "- 톤: '이게 뭔지 몰라도 됩니다 — 따라만 하면 됩니다' 스타일\n"
            "- 수익 기대치: 월 10~30만원 현실적 범위로만 표현\n"
            "- FAQ: 기초 개념, 시작 방법, 비용 같은 기본 질문 위주\n"
            "- 제목에 '초보도', '처음이라도', '몰라도 되는' 중 하나 반드시 포함"
        )
    if level == "advanced":
        return (
            "■ ADVANCED 작성 규칙:\n"
            "- 기술적 깊이 필수: API 연동, 자동화 파이프라인, 설정 아키텍처 포함\n"
            "- 타 도구 통합 구조 제안 (예: Zapier + Make + 도구명 파이프라인)\n"
            "- 톤: '이미 쓰고 있는 사람을 위한 다음 단계' 스타일\n"
            "- ROI 계산, 시간 절약 수치 구체적으로 (예: 기존 4시간 → 자동화 후 20분)\n"
            "- 수익 기대치: 월 200만원+ 또는 비용 절감 관점으로 표현\n"
            "- FAQ: 엣지케이스, 스케일업, 한계 극복 방법 위주\n"
            "- 꿀팁 섹션에 프롬프트 예시 또는 자동화 플로우 다이어그램(텍스트 형태) 포함\n"
            "- 제목에 '파이프라인', '자동화 아키텍처', '고급 활용', '스케일업' 중 하나 포함"
        )
    # intermediate (default)
    return (
        "■ INTERMEDIATE 작성 규칙:\n"
        "- 업계 용어 설명 최소화, 실무 용어 그대로 사용 가능\n"
        "- 워크플로 자동화 및 타 도구 연동 시나리오 2~3개 포함\n"
        "- 톤: '이미 써봤다면 이걸 모르면 손해' 스타일\n"
        "- 수익 기대치: 월 50~150만원 현실적 범위\n"
        "- FAQ: 응용법, 트러블슈팅, 한계 극복 위주\n"
        "- 제목에 '실무자가', '직접 써보니', '이렇게 쓰면', '실전에서는' 중 하나 포함"
    )


def _cta_html(reader_level: str) -> str:
    """독자 레벨에 맞는 마무리 CTA HTML 블록을 반환한다."""
    # Keep Blogspot readers on-site. prepare_blogspot_html() adds internal links.
    return ""


def _weighted_sample_no_replace(pool: list[str], weights: dict[str, int], k: int) -> list[str]:
    """가중치 기반 비복원 랜덤 샘플링."""
    available = list(pool)
    w = [weights.get(key, 1) for key in available]
    selected: list[str] = []
    for _ in range(min(k, len(available))):
        total = sum(w)
        if total <= 0:
            break
        r = random.uniform(0, total)
        cumsum = 0.0
        for i, wi in enumerate(w):
            cumsum += wi
            if r <= cumsum:
                selected.append(available.pop(i))
                w.pop(i)
                break
    return selected


def _load_recent_section_combos(content_type: str, limit: int = 3) -> set[frozenset[str]]:
    """최근 N회 발행 중 같은 content_type의 section_combo를 frozenset으로 반환."""
    try:
        history: list[dict[str, str]] = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        combos: set[frozenset[str]] = set()
        count = 0
        for entry in reversed(history):
            if entry.get("content_type") == content_type and entry.get("section_combo"):
                combos.add(frozenset(entry["section_combo"].split(",")))
                count += 1
                if count >= limit:
                    break
        return combos
    except Exception:
        return set()


def _content_type_section_guide(content_type: str, reader_level: str, tool_name: str) -> tuple[str, str]:
    """CONTENT_TYPE(A/B/C/D)에 맞는 섹션 구조 지시문을 반환한다.

    Returns:
        (combo_key, guide_text)
        combo_key: 선택된 optional 섹션 키를 쉼표로 이은 문자열 (history 기록용)
        guide_text: LLM에 전달할 섹션 구조 지시 텍스트
    """
    # ── 섹션 정의 ────────────────────────────────────────────────────
    TYPE_LABELS = {
        "A": "도구 심층 리뷰",
        "B": "단계별 튜토리얼",
        "C": "경쟁 도구 비교",
        "D": "수익화 전략",
    }

    # 각 TYPE별 optional 섹션 후보 (key → 지시문)
    # "비용/무료" 관련 섹션(free_vs_paid, cost_analysis)은 DEFERRED_KEYS로 분리 → 항상 뒤로 배치
    DEFERRED_KEYS: dict[str, set[str]] = {
        "A": {"free_vs_paid"},
        "B": set(),
        "C": {"cost_analysis"},
        "D": set(),
    }

    OPTIONAL_POOL: dict[str, dict[str, str]] = {
        "A": {
            "core_features":  f"핵심 기능 3가지 — 각 기능마다 <h3>이모지 기능명</h3> + 구체적 설명 + 실사용 팁",
            "tips":           "꿀팁 5가지 — 각 팁 <h3>이모지 제목</h3> + 구체적 수치/조작 방법 필수",
            "scenario":       "실제 사용 시나리오 2가지 (직장인 / 프리랜서 각각 별도 케이스)",
            "pros_cons":      "장·단점 정리 (✔ 장점 3개 이상, ✘ 단점 2개 이상)",
            "recommendation": "이런 분에게 추천 / 비추천 (각각 2가지 이상 구체적 이유)",
            "free_vs_paid":   "무료 vs 유료 비교 테이블 (HTML 비교 테이블 컴포넌트 사용, 5개 이상 비교 항목)",
        },
        "B": {
            "preview_box":      "미리보기 박스 — '이 가이드로 얻는 것' 3가지 (HTML 미리보기 박스 컴포넌트 사용)",
            "prerequisites":    "사전 준비물 — 필요한 계정·도구·예상 비용 명시",
            "tips":             "꿀팁 5가지 — 각 팁 <h3>이모지 제목</h3> + 구체적 수치/조작 방법 필수",
            "common_mistakes":  "흔한 실수 3가지 — 각각 문제 상황 → 원인 → 해결 방법 형식",
            "checklist":        "자가진단 체크리스트 (HTML 체크리스트 컴포넌트 사용, 5개 이상 항목)",
        },
        "C": {
            "tools_intro":    "비교 대상 도구 소개 (2~3개, 각 도구 핵심 특징 1줄 + 가격 명시)",
            "situational":    f"상황별 추천 — '이런 경우엔 {tool_name}', '이런 경우엔 경쟁 도구' 형식",
            "tips":           "꿀팁 5가지 — 도구 조합 활용법 위주, 각 팁 <h3>이모지 제목</h3>",
            "summary_card":   "최종 추천 요약 카드 (HTML 핵심 요약 카드 컴포넌트 사용)",
            "cost_analysis":  "비용 효율 분석 — 월 비용 대비 기능 가치 수치 비교",
        },
        "D": {
            "roi_table":       "ROI 계산표 (HTML ROI 계산표 컴포넌트 사용 — 예상 수익·비용·순수익 포함)",
            "failure_cases":   "실패 사례 박스 — '이런 경우 실패합니다' (HTML 실패 사례 박스 컴포넌트 사용)",
            "tips":            "꿀팁 5가지 — 수익화 최적화 노하우 위주, 각 팁 <h3>이모지 제목</h3>",
            "roadmap":         "월 수익 달성 로드맵 — 1주차 → 1개월 → 3개월 단계별 목표와 행동",
            "checklist":       "자가진단 체크리스트 (HTML 체크리스트 컴포넌트 사용, 5개 이상 항목)",
        },
    }

    # reader_level별 optional 섹션 가중치 (비용 섹션 가중치 낮춤)
    LEVEL_WEIGHTS: dict[str, dict[str, dict[str, int]]] = {
        "A": {
            "beginner":     {"tips": 3, "pros_cons": 3, "recommendation": 3, "core_features": 2, "scenario": 1, "free_vs_paid": 1},
            "intermediate": {"core_features": 3, "scenario": 3, "tips": 3, "pros_cons": 2, "recommendation": 1, "free_vs_paid": 1},
            "advanced":     {"core_features": 3, "scenario": 3, "tips": 3, "pros_cons": 2, "recommendation": 1, "free_vs_paid": 1},
        },
        "B": {
            "beginner":     {"prerequisites": 3, "common_mistakes": 3, "checklist": 3, "preview_box": 2, "tips": 1},
            "intermediate": {"tips": 3, "common_mistakes": 2, "preview_box": 2, "prerequisites": 1, "checklist": 1},
            "advanced":     {"tips": 3, "common_mistakes": 2, "checklist": 2, "preview_box": 1, "prerequisites": 1},
        },
        "C": {
            "beginner":     {"tools_intro": 3, "situational": 3, "tips": 2, "summary_card": 2, "cost_analysis": 1},
            "intermediate": {"situational": 3, "tips": 3, "tools_intro": 2, "summary_card": 2, "cost_analysis": 1},
            "advanced":     {"tips": 3, "situational": 3, "summary_card": 2, "tools_intro": 1, "cost_analysis": 1},
        },
        "D": {
            "beginner":     {"failure_cases": 3, "checklist": 3, "tips": 2, "roadmap": 2, "roi_table": 1},
            "intermediate": {"roi_table": 3, "roadmap": 3, "tips": 2, "failure_cases": 1, "checklist": 1},
            "advanced":     {"roi_table": 3, "tips": 3, "roadmap": 2, "failure_cases": 1, "checklist": 1},
        },
    }

    # TYPE별 optional 선택 개수
    OPTIONAL_COUNT = {"A": 4, "B": 3, "C": 4, "D": 4}

    pool = OPTIONAL_POOL.get(content_type, {})
    weights = LEVEL_WEIGHTS.get(content_type, {}).get(reader_level, {})
    pick_count = OPTIONAL_COUNT.get(content_type, 4)

    # 최근 3회 조합 로드 → 같은 조합 회피
    recent_combos = _load_recent_section_combos(content_type, limit=3)

    selected_optional: list[str] = []
    for _attempt in range(8):
        candidate = _weighted_sample_no_replace(list(pool.keys()), weights, pick_count)
        if frozenset(candidate) not in recent_combos:
            selected_optional = candidate
            break
    if not selected_optional:
        selected_optional = _weighted_sample_no_replace(list(pool.keys()), weights, pick_count)

    combo_key = ",".join(sorted(selected_optional))

    # ── 섹션 순서 결정 ────────────────────────────────────────────────
    # 비용/무료 관련 deferred 섹션은 항상 middle 맨 뒤로 배치
    deferred = DEFERRED_KEYS.get(content_type, set())
    front_optional = [k for k in selected_optional if k not in deferred]
    back_optional  = [k for k in selected_optional if k in deferred]
    random.shuffle(front_optional)

    # TYPE B: step_by_step은 항상 optional 중간 섹션 맨 앞에 고정
    if content_type == "B":
        step_guide = {
            "beginner": "7~8 STEP, 각 STEP 한 가지 행동만, 클릭 위치·메뉴명까지 명시",
            "advanced": "4~5 STEP, API 설정·자동화 파이프라인 포함",
        }.get(reader_level, "5~6 STEP, 워크플로 연동 시나리오 포함")
        step_text = f"STEP-BY-STEP 가이드 ({step_guide}) — 각 STEP: STEP 카드 컴포넌트 사용"
        middle_keys = ["step_by_step"] + front_optional + back_optional
        middle_texts = [step_text] + [pool[k] for k in front_optional + back_optional]
    else:
        middle_keys = front_optional + back_optional
        middle_texts = [pool[k] for k in middle_keys]

    # ── TYPE별 페르소나 힌트 + 오프닝 지시 + 섹션 흐름 조립 ─────────
    type_label = TYPE_LABELS.get(content_type, content_type)

    opening_hint = {
        "A": (
            f"첫 문단은 {tool_name}을 처음 발견한 순간을 묘사하며 시작하라 "
            f"(예: 어떤 맥락에서 발견했는지, 첫 인상, 왜 써보고 싶었는지)."
        ),
        "B": (
            f"첫 문단은 독자가 {tool_name} 없이 겪는 구체적 불편함을 묘사하며 시작하라 "
            f"(예: 반복 작업에 지친 상황, 시간 낭비, 결과물 품질 문제)."
        ),
        "C": (
            f"첫 문단은 {tool_name}과 경쟁 도구 중 하나를 선택해야 했던 실제 상황으로 시작하라 "
            f"(예: 어떤 프로젝트에서 비교가 필요했는지, 선택의 갈림길)."
        ),
        "D": (
            f"첫 문단은 {tool_name}으로 첫 수익이 들어온 순간 또는 첫 실패 경험으로 시작하라 "
            f"(예: 첫 의뢰·첫 판매·첫 실수 — 구체적 금액이나 상황 포함)."
        ),
    }.get(content_type, f"첫 문단은 {tool_name}과의 첫 만남으로 시작하라.")

    persona_hint = {
        "A": (
            f"글쓰기 페르소나: {tool_name}을 실제로 3개월 이상 써본 직장인 블로거 요미.\n"
            f"'이 도구 진짜 쓸 만한가?'라는 독자 질문에 솔직하게 답하는 후기형 심층 리뷰를 써라."
        ),
        "B": (
            f"글쓰기 페르소나: {tool_name} 활용법을 처음부터 끝까지 따라할 수 있게 안내하는 실전 가이드 작성자 요미.\n"
            f"독자가 이 글만 보고 바로 실행할 수 있도록 단계별로 안내해라."
        ),
        "C": (
            f"글쓰기 페르소나: 여러 AI 도구를 직접 비교 테스트해온 요미.\n"
            f"'{tool_name} vs 경쟁 도구 — 어떤 걸 써야 할까?'라는 독자 고민에 데이터 기반으로 답해라."
        ),
        "D": (
            f"글쓰기 페르소나: {tool_name}으로 실제 수익을 만들어본 경험을 공유하는 요미.\n"
            f"'현실적으로 얼마나 벌 수 있나?'에 솔직한 수치와 실패 사례까지 포함해라."
        ),
    }.get(content_type, f"글쓰기 페르소나: {tool_name} 전문 블로거 요미.")

    # ── 섹션별 명시적 번호 지시문 조립 ──────────────────────────────
    _STEP_LABEL = "STEP-BY-STEP 가이드"

    # 각 섹션 설명 리스트 (번호 부여용)
    all_section_descs: list[str] = (
        ["페르소나 카드 (HTML 페르소나 카드 컴포넌트 사용)"]
        + [f"도입 훅 — {opening_hint}"]
        + [
            f"{_STEP_LABEL} ({middle_texts[i].split('(')[1].rstrip(')') if '(' in middle_texts[i] else ''})"
            if k == "step_by_step"
            else pool[k]
            for i, k in enumerate(middle_keys)
        ]
        + ["FAQ 5개 — READER_LEVEL에 맞는 질문, 각 답변 3문장 이상·수치 포함"]
        + ["마무리 CTA — 아래 [마무리 CTA HTML] 블록을 그대로 삽입"]
    )
    total = len(all_section_descs)
    numbered_sections = "\n".join(
        f"[섹션 {i+1}/{total}] {desc}" for i, desc in enumerate(all_section_descs)
    )

    # 무료/비용 섹션이 포함된 경우 앞 섹션 노출 금지 경고 추가
    deferred_present = any(k in deferred for k in middle_keys)
    deferred_ban = (
        f"\n※ 무료 플랜·가격·비용 정보는 반드시 [섹션 {all_section_descs.index(next(d for d in all_section_descs if '무료' in d or '비용' in d)) + 1}/{total}]에서만 등장할 것."
        f" 그 이전 섹션에서 가격·무료 한도 노출 금지."
        if deferred_present and any('무료' in d or '비용' in d for d in all_section_descs)
        else ""
    )

    guide_text = (
        f"[CONTENT_TYPE {content_type} — {type_label}]\n"
        f"{persona_hint}\n\n"
        f"[오프닝 금지 패턴] '이 글에서는', '이번 포스팅에서는', '안녕하세요', '오늘은 ~에 대해'로 시작 절대 금지.\n"
        f"[핵심 요약 박스 금지] ⚡·💡 등의 핵심 요약 박스를 도입 훅보다 앞에 배치 금지. 요약은 도입 훅 뒤에만 허용.\n\n"
        f"[섹션 구조 — 아래 번호 순서 정확히 준수. 추가·삭제·순서 변경 절대 금지. 각 섹션 최소 250자]\n"
        f"{numbered_sections}"
        f"{deferred_ban}"
    )
    return combo_key, guide_text


def _labels_for_category(category: str) -> list[str]:
    """도구 카테고리에 맞는 영문·한국어 혼합 라벨 최대 5개를 반환한다."""
    mapping: dict[str, list[str]] = {
        "AI글쓰기":       ["AI Tools", "AI Writing", "AI활용법", "Side Hustle", "AI부업", "Online Income", "Freelance", "콘텐츠제작"],
        "AI이미지":       ["AI Tools", "AI Image", "AI활용법", "Side Hustle", "AI부업", "Online Income", "Freelance", "이미지생성"],
        "AI영상편집":     ["AI Tools", "AI Video", "AI활용법", "Side Hustle", "AI부업", "Online Income", "No-Code", "숏폼"],
        "AI코딩":         ["AI Tools", "AI Coding", "AI활용법", "Side Hustle", "No-Code", "Productivity", "자동화", "개발"],
        "AI자동화":       ["AI Automation", "업무자동화", "Workflow", "Productivity", "AI Tools", "ChatGPT", "생산성", "자동화"],
        "AI음성":         ["AI Tools", "AI Writing", "AI활용법", "Side Hustle", "AI부업", "Online Income", "Freelance", "오디오"],
        "AI프레젠테이션": ["AI Tools", "Productivity", "AI활용법", "Side Hustle", "No-Code", "Freelance", "생산성", "발표자료"],
        "AI생산성":       ["AI Tools", "Productivity", "AI활용법", "Side Hustle", "No-Code", "Online Income", "생산성", "업무자동화"],
    }
    return mapping.get(category, ["AI Tools", "AI활용법", "Productivity", "Side Hustle", "AI부업", "No-Code", "자동화", "AI리뷰"])


def _determine_next_content_type(repository: BlogWorkItemRepository) -> str:
    """최근 발행 글의 content_type을 보고 A→B→C→D 순환에서 다음 타입을 반환한다."""
    try:
        from blogspot_automation.storage import PublishStatus
        recent = repository.list_recent_by_status(statuses=[PublishStatus.PUBLISHED], limit=5)
        for item in recent:
            ct = getattr(item, "content_type", "")
            if ct in _CONTENT_TYPE_CYCLE:
                idx = _CONTENT_TYPE_CYCLE.index(ct)
                return _CONTENT_TYPE_CYCLE[(idx + 1) % 4]
    except Exception as exc:
        logger.warning("content_type determination failed: %s", exc)
    return "A"


SYSTEM_PROMPT = """당신은 "요미(Yomi)"라는 필명의 한국 AI 도구 전문 블로거입니다.
3년째 AI 도구를 직접 써보면서 "유료 강의에서나 들을 수 있는 정보를 무료로 푸는 블로그"를 운영 중입니다.
독자는 AI 도구로 생산성을 높이거나 부업을 시작하고 싶은 한국 직장인·프리랜서·부업 준비생입니다.
출력은 반드시 JSON 한 개만. 다른 텍스트 없이.

[글쓰기 핵심 원칙]
1. 독자가 실제로 검색하는 질문에 정확히 답하는 글을 쓴다
2. 공식 문서 요약이 아니라 "공식 문서에 없는 실전 인사이트"를 제공한다
3. 모든 문장은 독자가 "이건 저장해야겠다"고 느낄 만큼 구체적이어야 한다
4. 전체 텍스트(HTML 태그 제외) 3500자 이상 필수, 각 섹션 최소 250자
5. 마지막 섹션도 첫 섹션과 동일한 밀도로 끝까지 충실히 작성
6. 수익 금액은 반드시 범위로 표현 (예: 월 30~80만원, 건당 3~5만원)
7. 같은 정보를 다른 표현으로 반복 금지 — 매 문장은 새로운 정보를 제공할 것

[문장 톤 — 설명형 30% + 실전형 50% + 유머/말맛 20%]
- "~입니다", "~됩니다" 설명형 문장은 전체의 30% 이하
- "~해봤더니", "~더라고요", "~해보면", "~하니까" 실전 경험형 문장 50% 이상
- 독자에게 말하듯 자연스러운 톤 (강의 톤, 백과사전 톤 금지)
- "~할 수 있습니다" 막연한 문장 → "크몽에서 건당 3~5만원에 판매 가능합니다" 수준 구체화
- 모든 단락 5줄 이하 (모바일 최적화)
- 완벽한 대칭 구조 문장 3개 연속 금지 ("A이고, B이며, C입니다" 패턴 반복 금지) — AI 냄새 제거

[말맛·유머·재치 — 전체 글에 자연스럽게 녹여라]
- 글 전체에서 최소 3곳 이상 유머·재치 있는 표현을 써라. 억지스럽지 않게, 문맥에 자연스럽게.
- 허용되는 유머 스타일:
  · 반전형: "처음엔 '이게 뭐야' 했는데, 3일 뒤엔 '이거 없이 어떻게 살았지' 하고 있었습니다"
  · 공감형 자조: "물론 처음 세팅할 때 30분 날린 건 비밀입니다"
  · 과장형 비유: "이 기능 발견하고 나서 점심 먹다 말고 바로 써봤어요"
  · 직설형 솔직함: "솔직히 말하면 유튜브 알고리즘보다 이게 더 무섭습니다"
  · 독자 돌직구: "아직도 수동으로 하고 계신 거 맞죠? 저도 그랬습니다"
- 단, 억지 드립·유행어 남용·MZ 과잉 표현은 금지. 센스 있는 직장인이 쓰는 수준.
- 섹션 마무리 문장에 가끔 여운 있는 한 줄을 써라 (예: "이게 무료라는 게 아직도 믿기지 않아요")
- h2/h3 제목에도 재치를 넣을 수 있음 (예: "🤑 이게 무료라고요? 네, 무료입니다")
- 불완전 구어체 의도적 사용: "근데 이게 좀 재밌는 지점인데요." / "솔직히 이 부분은 저도 반신반의했습니다." / "그래서 결론이 뭐냐면..." — 섹션당 최소 1회
- 필자 감정 1인칭 표현 섹션당 최소 1회: "제 관점에서는", "직접 써봤더니 의외였던 건"

[비유의 건축학 — 전문 용어 첫 등장 시 반드시 적용]
원칙: 추상적 기술 개념이 처음 나오는 즉시 일상 사물·경험으로 치환한다.
- 전문 용어 등장 → 바로 다음 문장에 "쉽게 말하면 ~입니다" 또는 괄호 비유 의무 삽입
- 비유는 구체적 명사로 (추상 → 추상 치환 금지)
- 섹션당 비유 1~2개 (과도한 남발도 금지)
내장 비유 사례 (응용 사용):
  · 에이전트 = 자기 판단으로 출장 다니는 직원, 반드시 복명복창 필요
  · 컨텍스트 윈도우 = AI가 한 번에 올려다볼 수 있는 책상 넓이
  · 파인튜닝 = 식당 레시피에 우리 집 비법 소스를 추가하는 것
  · 환각(Hallucination) = 자신감 넘치는 길치의 길 안내
  · 프롬프트 = 직원에게 주는 업무 지시서, 구체적일수록 결과가 좋아짐
  · 기술 부채 = 청소 안 한 방 — 당장 눈에 안 띄지만 어느 날 발을 뻗을 수 없게 됨
→ 새로운 도구에 맞는 비유가 필요하면 위 패턴을 응용. 기존 비유 반복 금지.

[소제목 패턴 — 동일 패턴 2회 이상 연속 금지]
A — 반전·역설형: "당연하다고 생각했는데 사실은"
B — 선언형: "결론부터 말하면 ~입니다"
C — 독자 공감형: "이 상황, 한 번쯤 겪어보셨을 겁니다"
D — 질문형: "~는 정말 효과가 있을까요?"
E — 고백형: "솔직히 말하면 ~입니다"
→ 글 전체에서 A·B·C·D·E를 순환하며 사용. 같은 패턴 연달아 2번 금지.

[절대 금지]
- <img>, <figure>, <figcaption>, imageanchor 태그 사용 금지
- 본문 URL 직접 노출 금지 → 반드시 <a href="URL">앵커텍스트</a> 형식
- 첫 문단 금지 패턴: "이 글에서는", "이번 포스팅에서는", "안녕하세요", "오늘은 ~에 대해" 사용 금지
- 핵심 요약 박스(⚡·💡 등)를 도입 훅 이전 위치에 배치 금지 — 요약은 도입 훅 이후에만 허용
- "혁신적입니다", "주목받고 있습니다", "각광받고 있습니다", "다양한 기능", "여러 가지" 단독 사용 금지
- "AI 도구"를 도구명 없이 3회 이상 단독 사용 금지
- FAQ 5개 미만, 각 답변 3문장 미만, 수치 없는 답변 금지
- FAQ 답변에 "공식 페이지에서 확인하세요" / "공식 문서를 참고하세요" 금지 → 독자가 그 자리에서 판단할 수 있는 정보를 직접 제공
- 수치 hallucination 절대 금지 — 무료 플랜 한도는 도구 DB 정보만 사용
- 라벨 금지어: 인공지능, 딥러닝, 빅데이터, IT, 프로그래밍, 경영, 머신러닝 및 인공지능
- "다음과 같습니다", "아래와 같습니다"로 끝내고 내용 비우는 것 금지
- 꿀팁 각 항목: 반드시 <h3>이모지 팁 제목</h3> + 구체 수치·조작 방법 포함 (모호한 조언 금지)
- 영문 지시문·메타 코멘트 본문 노출 절대 금지
- 동일 단락 2회 이상 중복 출력 금지
- 수요 급증, 급성장, 폭발적 증가 등 출처 없는 단정 표현 금지
- "근거 없는 추천" 금지 — 반드시 수치·실제 사례·필자 관점으로 뒷받침

[제목 공식 — 후킹 필수]
- 제목 길이 25~45자, 도구명 필수, 숫자 1개 이상, 도구명 첫 단어 금지
- 마무리 패턴: "— 했습니다" / "— 바뀝니다" / "— 달라집니다" / "— 얘기입니다" 권장
  금지: "— 사용법" / "— 총정리" / "— 알아보겠습니다" / "— 후기 정리"
- 트리거 3점 체계 (숫자+감정+결과 암시 동시 충족 목표):
  예) "백로그 12개인데 코드 0줄, [도구명]이 했습니다" → 3점 합격
  예) "회의록 못 썼다고 혼났는데, [도구명] 쓰고 달라졌습니다" → 3점 합격
- READER_LEVEL별 키워드 반드시 포함:
  BEGINNER → "초보도" / "처음이라도" / "몰라도 되는" / "따라하기만 하면"
  INTERMEDIATE → "실무자가" / "직접 써보니" / "이렇게 쓰면" / "실전에서는"
  ADVANCED → "파이프라인" / "자동화 아키텍처" / "고급 활용" / "스케일업"

[독자 레벨별 작성 기준]
■ BEGINNER: 기술 용어 괄호 설명 필수, "따라만 하면 됩니다" 톤, 수익 기대치 월 10~30만원, FAQ 기초 개념 위주
■ INTERMEDIATE: 실무 용어 그대로, 연동 시나리오 2~3개, "이걸 모르면 손해" 톤, 수익 월 50~150만원
■ ADVANCED: API·파이프라인·아키텍처 수준, ROI 수치 구체적, 수익 월 200만원+, 꿀팁에 프롬프트·플로우 포함

[SEO / AEO / GEO 최적화]
- 첫 문장: "~는 ~입니다" 형태 직접 답변 (Featured Snippet 겨냥)
- meta_description: 질문형 + 답변 축약 120자 이내
- 각 h2 소제목에 도구명 자연스럽게 포함
- FAQ 질문: 독자가 구글에 실제로 검색할 문장 그대로
- 도구명 본문 10~20회 자연 분산 (키워드 스터핑 금지)
- GEO 50단어 답변 블록: 각 주요 섹션 첫 문단은 40~60단어 핵심 요약으로 시작
  → AI 검색엔진(Perplexity·ChatGPT·Gemini)이 이 글을 인용 출처로 선택하게 하는 구조
  → 형식: "이번 섹션의 핵심은 [내용]입니다. [도구명]은 [기능]을 통해 [결과]를 달성합니다. [조건]인 팀에게 특히 유효합니다."
- GEO 수치 데이터 최소 3개 삽입: "공식 발표 기준으로" / "실제 사용자 후기 종합 시" 형태로 근거 신호 포함
- 의미론적 삼중주: '주어-술어-목적어' 명확한 구조로 핵심 문장 작성 (AI 지식 그래프 파싱 최적화)

[비즈니스 언어 — 기능 설명을 ROI 언어로 전환]
- 비용 섹션에서 단순 가격 비교 대신 ROI 계산 방식 1회 이상 제시
  → "월 20달러면 싸다"보다 "이 비용으로 절감되는 업무 시간 × 시간당 인건비"로 계산
- 기술 부채 관점 1회 이상 자연스럽게 언급
  → 이 도구를 쓸 때 장기적으로 발생할 수 있는 의존도·유지보수 리스크 간단히 짚기
- "이 도구는 좋습니다" 식 근거 없는 추천 금지 → 반드시 수치·사례·필자 관점으로 뒷받침

[HTML 컴포넌트]
전체 래퍼: <div style="max-width:760px;margin:0 auto;font-family:'Pretendard','Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#1a1a1a;line-height:1.85;font-size:16.5px;">
본문 p: <p style="margin:0 0 14px 0;word-break:keep-all;">내용</p>
핵심 강조(오렌지): <div style="background:linear-gradient(135deg,#FFF7ED,#FFEDD5);padding:18px 20px;border-left:4px solid #E85D04;margin:18px 0;border-radius:8px;">내용</div>
정보 박스(블루): <div style="background:linear-gradient(135deg,#EFF6FF,#DBEAFE);padding:18px 20px;border-left:4px solid #2563EB;margin:18px 0;border-radius:8px;">내용</div>
성공(그린): <div style="background:linear-gradient(135deg,#F0FDF4,#DCFCE7);padding:18px 20px;border-left:4px solid #16A34A;margin:18px 0;border-radius:8px;">내용</div>
실패(레드): <div style="background:linear-gradient(135deg,#FEF2F2,#FEE2E2);padding:18px 20px;border-left:4px solid #DC2626;margin:18px 0;border-radius:8px;"><p style="font-weight:700;color:#DC2626;">⛔ 이런 경우 실패합니다</p>내용</div>
장점: <p style="margin:4px 0;"><span style="color:#16A34A;font-weight:700;">✔</span> 설명</p>
단점: <p style="margin:4px 0;"><span style="color:#DC2626;font-weight:700;">✘</span> 설명</p>
STEP 카드: <div style="background:#F8FAFC;padding:14px 18px;border-radius:8px;margin:10px 0;border:1px solid #E2E8F0;"><p style="margin:0 0 6px 0;"><strong style="color:#2563EB;font-size:16px;">STEP N.</strong> <strong>제목</strong></p><p style="margin:0;color:#475569;">→ 핵심 행동 1줄 + 보충 1~2줄 (각 STEP 3줄 이하 유지)</p></div>
FAQ: <div style="border-bottom:1px solid #E5E7EB;padding:16px 0;"><p style="margin:0 0 8px 0;font-weight:700;color:#7C3AED;font-size:16.5px;">QN. 질문</p><p style="margin:0;color:#374151;">A. 답변 (3문장 이상, 수치 필수, "공식 사이트 확인" 회피형 표현 금지)</p></div>
페르소나 카드(첫머리 필수): <div style="background:#F8F9FA;padding:10px 16px;border-radius:6px;margin:0 0 20px 0;border:1px solid #DEE2E6;font-size:14px;color:#495057;">👤 <strong>이 글이 맞는 분:</strong> 구체적 독자 페르소나 1줄</div>
체크리스트: <div style="background:#F0FDF4;padding:18px 20px;border-left:4px solid #16A34A;margin:18px 0;border-radius:8px;"><p style="font-weight:700;color:#15803D;">✅ 체크리스트 제목</p><p style="margin:4px 0;">☐ 항목</p></div>
줄바꿈: h2/h3로 섹션 전환. h2 앞 <br> 금지. 연속 <br> 3개 이상 금지.

[본문 구조]
- user_prompt에서 지정한 섹션 순서를 정확히 따를 것
- 매 글 첫머리: 페르소나 카드 필수
- 도입부 훅: 질문형/공감형/데이터형/발견형 중 매번 다르게 선택. 첫 줄은 2인칭 + 구체 숫자 또는 장면
- FAQ 5개 필수, READER_LEVEL에 맞는 질문. 보안·데이터 리스크 질문 최소 1개 포함
- 마무리 CTA: user_prompt 지정 레벨별 HTML 그대로 삽입

[라벨] 2~5개만 사용. 영문·한국어 혼합 가능. 금지: 인공지능, 딥러닝, 빅데이터, IT, 프로그래밍, 경영, 머신러닝

[출력 JSON — 다른 텍스트 없이]
{
  "title": "후킹 제목 (25~45자, 도구명+숫자 필수, 도구명 첫 단어 금지, 감정 유지형 마무리)",
  "content": "HTML 본문 전체 (<div> 래퍼 포함, 텍스트 기준 3500자 이상, 이미지 태그 금지)",
  "tags": ["라벨1", "라벨2", "라벨3"],
  "meta_description": "질문형+답변 축약 120자 이내",
  "faq_items": [
    {"question": "Q1 질문 전문", "answer": "A1 답변 전문"},
    {"question": "Q2 질문 전문", "answer": "A2 답변 전문"},
    {"question": "Q3 질문 전문", "answer": "A3 답변 전문"},
    {"question": "Q4 질문 전문", "answer": "A4 답변 전문"},
    {"question": "Q5 질문 전문", "answer": "A5 답변 전문"}
  ],
  "hashtags": ["#AI도구명", "#AI활용", "#업무자동화"]
}
"""


@dataclass
class AiContentResult:
    title_candidates: list[str]
    meta_description: str
    labels: list[str]
    faq_items: list[dict[str, str]]
    article_html: str
    hashtags: list[str] = field(default_factory=list)
    one_line_hook: str = ""
    estimated_time_to_start: str = ""
    estimated_cost_to_start: str = ""
    potential_income_range: str = ""
    difficulty_level: str = ""
    failure_points: list[str] = field(default_factory=list)
    practical_actions: list[str] = field(default_factory=list)
    cta_direction: str = ""


class AiContentService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        brief_repository: BriefRecordRepository,
        settings: Settings,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.brief_repository = brief_repository
        self.settings = settings
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

    def generate_from_selected_topic(self, selection: SelectedTopicResult) -> BriefRecord:
        if selection.publish_status != PublishStatus.PLANNED.value:
            raise ValueError(
                f"Content generation is blocked because publish_status={selection.publish_status}. "
                "Only planned topics with sufficient sources can continue."
            )

        work_item = self.work_item_repository.get_by_id(selection.saved_work_item_id)
        if not work_item:
            raise ValueError(f"Work item not found: {selection.saved_work_item_id}")

        # 메인 기사 내용 (첫 번째 소스 기사)
        topic_summary = ""
        source_name = ""
        if selection.source_articles:
            first = selection.source_articles[0]
            topic_summary = first.get("summary", "") or first.get("description", "")
            source_name = first.get("provider_name", "") or first.get("source_name", "")

        # 추가 관련 기사 컨텍스트
        extra_context = self._build_source_context(selection.source_articles[1:])

        # content_type A→B→C→D 순환 결정
        content_type = _determine_next_content_type(self.work_item_repository)
        # 독자 레벨 선택 (3회 연속 같은 레벨 금지)
        reader_level = _select_reader_level()
        logger.info("content_type=%s reader_level=%s", content_type, reader_level)

        # 오늘의 AI 도구 선택 (7일 미사용 + 30일 내 동일 combo 제외)
        selected_tool = _select_tool_for_today(reader_level=reader_level, content_type=content_type)

        if selected_tool:
            tool_name_ko = selected_tool.get("name_ko", "")
            tool_name_en = selected_tool.get("name_en", "")
            use_cases_str = ", ".join(selected_tool.get("use_cases", []))
            routes_str = ", ".join(selected_tool.get("monetization_routes", []))
            tags_str = ", ".join(selected_tool.get("tags", []))
            search_queries = selected_tool.get("search_queries", [])
            search_queries_str = "\n".join(f"  - {q}" for q in search_queries)
            user_prompt = (
                f"오늘 리뷰할 도구 정보:\n"
                f"- 도구명(한글): {tool_name_ko}\n"
                f"- 도구명(영문): {tool_name_en}\n"
                f"- 카테고리: {selected_tool.get('category')}\n"
                f"- 무료/유료: {selected_tool.get('free_plan_detail')}\n"
                f"- 활용 사례: {use_cases_str}\n"
                f"- 수익화 경로: {routes_str}\n"
                f"- 시장 갭: {selected_tool.get('competitor_gap')}\n"
                f"- 사용할 태그: {tags_str}\n"
            )
            if search_queries_str:
                user_prompt += (
                    f"\n[독자가 실제로 검색하는 질문들 — 이 질문들에 반드시 답하는 글을 쓸 것]\n"
                    f"{search_queries_str}\n"
                )
            user_prompt += (
                f"\n오늘의 뉴스/토픽: {selection.selected_topic}\n"
                f"토픽 요약: {topic_summary}\n"
            )
            if extra_context:
                user_prompt += f"\n[추가 관련 기사]\n{extra_context}\n"
            _today_str = datetime.now(timezone.utc).strftime("%Y년 %m월 %d일")
            _section_combo, _section_guide = _content_type_section_guide(content_type, reader_level, tool_name_ko or tool_name_en)
            _cta = _cta_html(reader_level)
            user_prompt += (
                f"\n[오늘의 작성 조건 — 반드시 준수]\n"
                f"작성일: {_today_str}\n"
                f"CONTENT_TYPE: {content_type}\n"
                f"READER_LEVEL: {reader_level.upper()}\n"
                f"{_reader_level_instruction(reader_level)}\n"
                f"\n{_section_guide}\n"
                f"\n[마무리 CTA HTML — 마지막 섹션에 그대로 삽입]\n{_cta}\n"
                f"\n반드시 제목에 {tool_name_ko} 또는 {tool_name_en}을 포함하세요.\n"
                f"독자가 실제로 필요로 하는 정보(무료/유료 차이, 꿀팁, 핵심 원리, 실수 방지)를 중심으로 써주세요.\n"
                f"반드시 faq_items(5개)를 JSON에 포함하고, hashtags는 최대 3개만 포함하세요.\n"
            )
        else:
            # 도구 DB 없을 때 fallback
            user_prompt = (
                f"오늘의 뉴스/토픽: {selection.selected_topic}\n"
                f"토픽 요약: {topic_summary}\n"
            )
            if extra_context:
                user_prompt += f"\n[추가 관련 기사]\n{extra_context}\n"
            _today_str = datetime.now(timezone.utc).strftime("%Y년 %m월 %d일")
            _section_combo, _section_guide = _content_type_section_guide(content_type, reader_level, selection.selected_topic[:20])
            _cta = _cta_html(reader_level)
            user_prompt += (
                f"\n[오늘의 작성 조건]\n"
                f"작성일: {_today_str}\n"
                f"CONTENT_TYPE: {content_type}\n"
                f"READER_LEVEL: {reader_level.upper()}\n"
                f"{_reader_level_instruction(reader_level)}\n"
                f"\n{_section_guide}\n"
                f"\n[마무리 CTA HTML — 마지막 섹션에 그대로 삽입]\n{_cta}\n"
                f"반드시 faq_items(5개)를 JSON에 포함하고, hashtags는 최대 3개만 포함하세요.\n"
            )

        # 태그 필터 목록 로드
        whitelist, banned = _load_tag_lists()

        # LLM 호출 → QA 검증 → 재시도 루프 (최대 2회)
        _MAX_RETRIES = 2
        ai_result = None
        last_errors: list[str] = []
        current_prompt = user_prompt

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                current_prompt = (
                    user_prompt
                    + f"\n\n[재작성 요청 — 이전 QA 실패 사유: {last_errors}]\n"
                    "다음 규칙을 반드시 지켜서 전체 글을 다시 작성하세요:\n"
                    "1) 순수 텍스트 기준 1500자 이상 충분히 작성할 것\n"
                    "2) FAQ는 반드시 <p><strong>Q1.</strong></p><p>A. 답변</p> 형식으로 4개 이상 작성\n"
                    "3) STEP 1. STEP 2. STEP 3. 형식으로 3개 이상 작성\n"
                    "4) 수익 금액·플랫폼명 등 구체적 수치를 5개 이상 포함\n"
                )
                logger.info("QA 실패로 재생성 시도 %d/%d", attempt, _MAX_RETRIES)

            ai_result = self._call_llm(current_prompt)

            # 태그 필터링 — 카테고리 기반 영문 라벨을 fallback으로 사용
            _category = selected_tool.get("category", "") if selected_tool else ""
            fallback_tags = _labels_for_category(_category)
            ai_result.labels = filter_tags(
                generated_tags=ai_result.labels,
                whitelist=whitelist,
                banned=banned,
                fallback_tags=fallback_tags,
            )
            # 카테고리 레이블 merge → 한국어 포함 최소 8개, 최대 12개 보장
            _category_labels = _labels_for_category(_category)
            _merged = list(dict.fromkeys(ai_result.labels + _category_labels))
            ai_result.labels = normalize_labels([lb for lb in _merged if lb not in banned])
            ai_result.hashtags = normalize_hashtags(ai_result.hashtags)

            # HTML 후처리
            ai_result.article_html = post_process_html(ai_result.article_html)

            # QA 검증 (도구가 선택된 경우에만)
            if selected_tool:
                title_for_qa = ai_result.title_candidates[0] if ai_result.title_candidates else ""
                qa = validate_content(
                    title=title_for_qa,
                    content=ai_result.article_html,
                    tags=ai_result.labels,
                    tool=selected_tool,
                    banned_tags=banned,
                )
                if qa["passed"]:
                    logger.info("QA 검증 통과 (attempt %d)", attempt + 1)
                    break
                last_errors = qa["errors"]
                logger.warning("QA 검증 실패 (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES + 1, last_errors)
                if attempt == _MAX_RETRIES:
                    logger.error("QA 검증 %d회 재시도 후 최종 실패, 발행 스킵: %s", _MAX_RETRIES, last_errors)
                    raise ValueError(f"Content QA failed after {_MAX_RETRIES} retries: {last_errors}")
            else:
                break  # 도구 없을 때 QA 스킵

        # 콘텐츠 생성 완료 → 히스토리 기록 (selected_tool 없어도 항상 실행)
        _tool_id = selected_tool["id"] if selected_tool else "no_tool"
        _record_tool_used(_tool_id, content_type=content_type, reader_level=reader_level, section_combo=_section_combo)

        timestamp = datetime.now(timezone.utc).isoformat()

        record = BriefRecord(
            work_item_id=selection.saved_work_item_id,
            created_at=timestamp,
            updated_at=timestamp,
            brief_summary=ai_result.meta_description,
            final_angle=ai_result.title_candidates[0] if ai_result.title_candidates else selection.selected_topic,
            target_reader="AI 기술/교육 관심 독자",
            one_line_hook=ai_result.one_line_hook,
            faq_items=ai_result.faq_items,
            estimated_time_to_start=ai_result.estimated_time_to_start,
            estimated_cost_to_start="",
            potential_income_range="",
            difficulty_level="",
            failure_points=[],
            practical_actions=[],
            cta_direction="",
            content_density_status="dense",
        )

        work_item.title_candidates = ai_result.title_candidates
        work_item.final_title = ai_result.title_candidates[0] if ai_result.title_candidates else selection.selected_topic
        work_item.meta_description = ai_result.meta_description
        work_item.labels = ai_result.labels
        work_item.article_html = ai_result.article_html
        work_item.faq_items = ai_result.faq_items
        # LLM 생성 해시태그 저장 (publish 시 사용)
        if hasattr(work_item, 'hashtags') and ai_result.hashtags:
            work_item.hashtags = normalize_hashtags(ai_result.hashtags)
        work_item.estimated_time_to_start = ai_result.estimated_time_to_start
        work_item.estimated_cost_to_start = ""
        work_item.potential_income_range = ""
        work_item.difficulty_level = ""
        work_item.failure_points = []
        work_item.content_density_status = "dense"
        work_item.content_type = content_type
        self.work_item_repository.upsert(work_item)

        self.brief_repository.upsert(record)
        return record

    def _call_llm(self, user_prompt: str, system_prompt: str | None = None) -> AiContentResult:
        import re
        from blogspot_automation.services.llm_content_service import LlmContentService

        # LLM 비용 절감 정책 — Gemini API free-tier → OpenAI API fallback 순.
        # Gemini 키 장애/한도 초과 시 OpenAI로 fallback.
        # validator로 JSON 파싱 검증 — 응답이 잘리거나 형식 깨지면 자동 다음 provider로 fallback.
        llm = LlmContentService()
        sys_prompt = system_prompt or SYSTEM_PROMPT
        sys_prompt = (
            sys_prompt
            + "\n\n[신뢰성/SEO 안전 규칙]\n"
            + "- 실제로 검증하지 않은 1인칭 경험담을 쓰지 마세요. '제가 해보니', '첫 수익 경험', '직접 벌었다' 같은 표현 금지.\n"
            + "- 출처에 없는 수익 금액, 매출, 절감률, 날짜, 인원 수를 창작하지 마세요.\n"
            + "- labels는 2~5개, hashtags는 최대 3개만 사용하세요.\n"
            + "- 외부 블로그 CTA나 blog.naver.com 링크를 본문에 넣지 마세요.\n"
        )

        def _normalize_and_parse(text: str) -> dict[str, Any]:
            """LLM 응답에서 JSON 추출 + 파싱 — prefix(`json`/```/```json), suffix(```) 제거 + JSON 블록만 추출."""
            cleaned = (text or "").strip()
            # ```json / ``` 코드 펜스 제거
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
            # LLM이 펜스 없이 `json\n{...}` 형태로 prefix만 붙이는 케이스
            cleaned = re.sub(r"^json\s*\n", "", cleaned, flags=re.IGNORECASE)
            # 첫 { 부터 마지막 } 까지만 사용 (앞뒤 자연어 prefix/suffix 제거)
            m = re.search(r"\{[\s\S]*\}", cleaned)
            if m:
                cleaned = m.group(0)
            return json.loads(cleaned)

        def _validator(text: str) -> None:
            # 응답이 JSON 파싱 가능한지 + 핵심 필드(content) 존재 확인.
            # 실패하면 LlmContentService가 자동으로 다음 provider 시도.
            parsed = _normalize_and_parse(text)
            if not isinstance(parsed, dict) or not str(parsed.get("content") or "").strip():
                raise ValueError("response missing 'content' field")
            if has_unverified_experience_or_income_claim(str(parsed.get("content") or "")):
                raise ValueError("unverified experience or income claim detected")

        logger.info("LLM fallback chain 호출 시작 (무료 우선, JSON validator 활성)...")
        content_str = llm.call_with_fallback(
            user_prompt=user_prompt,
            system_prompt=sys_prompt,
            min_chars=500,
            validator=_validator,
        )

        if not content_str:
            raise RuntimeError(
                "LLM fallback chain 전체 실패 — 모든 provider가 호출 실패 또는 invalid JSON 반환. "
                "GOOGLE_AI_API_KEY 또는 OPENAI_API_KEY 중 최소 1개가 유효 + 정상 응답해야 합니다."
            )

        try:
            result = _normalize_and_parse(content_str)

            title = result.get("title", "").strip("\"'")
            title_candidates = [title] if title else []
            meta_description = result.get("meta_description", "")
            tags = result.get("tags", [])
            labels = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
            article_html = result.get("content", "")

            # FAQ 파싱 (JSON-LD용)
            faq_items = result.get("faq_items", [])
            if not isinstance(faq_items, list):
                faq_items = []

            # 해시태그 파싱 (본문 하단 삽입용)
            hashtags = result.get("hashtags", [])
            if not isinstance(hashtags, list):
                hashtags = []
            # 플레이스홀더/불완전 항목 제거 후 최대 3개로 제한
            hashtags = [
                h for h in hashtags
                if isinstance(h, str) and h.startswith('#') and len(h) > 1
                and '개' not in h and '...' not in h and '~' not in h
            ]
            hashtags = normalize_hashtags(hashtags)

            return AiContentResult(
                title_candidates=title_candidates,
                meta_description=meta_description,
                labels=labels,
                faq_items=faq_items,
                article_html=article_html,
                hashtags=hashtags,
                one_line_hook="",
                estimated_time_to_start="",
                estimated_cost_to_start="",
                potential_income_range="",
                difficulty_level="",
                failure_points=[],
                practical_actions=[],
                cta_direction="",
            )
        except Exception as e:
            head = (content_str or "")[:300]
            tail = (content_str or "")[-300:]
            logger.error(
                "Failed to parse LLM response: %s\n  len=%d\n  head: %s\n  tail: %s",
                e, len(content_str or ""), head, tail,
            )
            raise ValueError(f"LLM content parsing failed: {e}")

    def _build_source_context(self, source_articles: list[dict[str, Any]]) -> str:
        parts = []
        for i, article in enumerate(source_articles[:4], 1):
            title = article.get("title", "")
            summary = article.get("summary", "")
            source_name = article.get("source_name", article.get("source_url", ""))
            parts.append(f"--- 기사 {i} ---\n제목: {title}\n출처: {source_name}\n내용: {summary}\n")
        return "\n".join(parts)


