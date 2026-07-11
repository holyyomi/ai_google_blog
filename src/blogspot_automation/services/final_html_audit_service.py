from __future__ import annotations

import re
from collections import Counter
from datetime import date
from html import unescape
from typing import Any

from blogspot_automation.services.seo_policy import MAX_CONTENT_HASHTAGS
from blogspot_automation.services.title_integrity_policy import FOREIGN_SCRIPT_RE, audit_title_integrity


def audit_final_html_quality(
    html: str,
    *,
    topic: str = "",
    content_type: str = "",
    topic_group: str = "",
) -> dict[str, Any]:
    content = html or ""
    visible = _visible_text(content)
    issues: list[str] = []
    warnings: list[str] = []

    title_like_texts = _extract_title_like_texts(content)
    if topic:
        title_like_texts.insert(0, topic)
    for text in list(dict.fromkeys(title_like_texts)):
        integrity = audit_title_integrity(text, content_type=content_type, topic_group=topic_group)
        for issue in integrity.get("blocking_issues", []):
            if issue == "missing_title":
                continue
            issues.append(f"visible_title_integrity:{issue}")

    legacy_markers = [
        marker
        for marker in ("hero-summary-box", "core-message-box", "ai-overview-box", "paa-block", "golden-preview")
        if re.search(rf'class=["\'][^"\']*\b{re.escape(marker)}\b', content, flags=re.IGNORECASE)
    ]
    if legacy_markers:
        issues.append("legacy_visual_layout_markers_present:" + ",".join(legacy_markers))
    if "<article" in content.lower() and "yomi-clean-post" not in content:
        warnings.append("missing_yomi_clean_post_layout")
    clean_layout = _clean_layout_metrics(content)
    if clean_layout["present"]:
        if clean_layout["lede_count"] != 1:
            issues.append(f"yomi_clean_layout_lede_count:{clean_layout['lede_count']}")
        if clean_layout["adaptive_module_count"] < 2:
            issues.append(
                f"yomi_clean_layout_lacks_adaptive_modules:{clean_layout['adaptive_module_count']}"
            )
        if clean_layout["inline_style_count"]:
            issues.append(f"inline_styles_present_in_clean_layout:{clean_layout['inline_style_count']}")
        if clean_layout["details_count"]:
            issues.append(f"details_ui_present_in_clean_layout:{clean_layout['details_count']}")

    replacement_count = visible.count("\ufffd")
    question_run_count = len(re.findall(r"\?{3,}", visible))
    latin_mojibake_count = len(re.findall(r"[ÃÂìíîïêëð]", visible))
    compatibility_hanja_count = len(re.findall(r"[\uF900-\uFAFF]", visible))
    if replacement_count:
        issues.append(f"unicode_replacement_characters_present:{replacement_count}")
    if question_run_count:
        issues.append(f"broken_question_mark_runs_present:{question_run_count}")
    if latin_mojibake_count >= 3:
        issues.append(f"latin_mojibake_signals_present:{latin_mojibake_count}")
    elif latin_mojibake_count:
        warnings.append(f"latin_mojibake_signal_present:{latin_mojibake_count}")
    if compatibility_hanja_count >= 12:
        issues.append(f"compatibility_hanja_mojibake_signals_present:{compatibility_hanja_count}")
    elif compatibility_hanja_count >= 4:
        warnings.append(f"compatibility_hanja_mojibake_signals_present:{compatibility_hanja_count}")

    intent_answers = _extract_intent_answers(content)
    faq_answers = _extract_faq_answers(content)
    all_answers = intent_answers + faq_answers
    bad_answer_count = sum(1 for answer in all_answers if _is_low_quality_answer(answer))
    if bad_answer_count:
        issues.append(f"low_quality_faq_or_intent_answer:{bad_answer_count}")

    repeated_answers = _repeated_answer_count(all_answers)
    if repeated_answers >= 3:
        issues.append(f"repeated_faq_or_intent_answers:{repeated_answers}")
    elif repeated_answers == 2:
        warnings.append("repeated_faq_or_intent_answers:2")

    overview = _extract_section_text(content, "AI_OVERVIEW_TARGET_ANSWER")
    if overview and _is_low_quality_overview(overview):
        issues.append("low_quality_ai_overview_answer")
    issue_context = _extract_section_text(content, "ISSUE_CONTEXT_BLOCK")
    if issue_context and _is_low_quality_overview(issue_context):
        warnings.append("thin_or_metadata_like_issue_context")

    internal_labels = _visible_internal_section_labels(content)
    if internal_labels:
        issues.append("visible_internal_section_labels:" + ",".join(internal_labels))
    stale_question_labels = [
        label
        for label in ("관련 검색 질문", "추가로 확인할 검색 질문", "함께 확인할 질문", "신청 전 많이 묻는 질문", "신청전 많이 묻는 질문")
        if label in visible
    ]
    if stale_question_labels:
        issues.append("stale_question_section_labels:" + ",".join(stale_question_labels))
    repeated_summary_headings = _repeated_summary_heading_count(content)
    if repeated_summary_headings >= 3:
        issues.append(f"repeated_summary_headings:{repeated_summary_headings}")
    elif repeated_summary_headings == 2:
        warnings.append("repeated_summary_headings:2")
    # 실사례: 본문에 `chrome://flags/#search-ai-overviews` 같은 URL 프래그먼트를
    # 인용하면 '#'이 진짜 해시태그가 아닌데도 매칭돼 uncontrolled_visible_body_hashtags가
    # 오탐으로 발행을 차단했다(2026-07-10). '#' 바로 앞이 단어문자·/·.·:·-면 URL/코드
    # 조각으로 보고 제외한다.
    visible_hashtags = re.findall(r"(?<![\w/:.\-])#[가-힣A-Za-z0-9_]{2,}", visible)
    controlled_hashtags = _controlled_hashtag_count(content)
    if visible_hashtags and controlled_hashtags != len(visible_hashtags):
        issues.append(f"uncontrolled_visible_body_hashtags:{len(visible_hashtags)}")
    if controlled_hashtags > MAX_CONTENT_HASHTAGS:
        issues.append(f"too_many_content_hashtags:{controlled_hashtags}")

    empty_td_count = _empty_table_cell_count(content)
    if empty_td_count:
        issues.append(f"empty_table_cells:{empty_td_count}")

    # LLM 외국어 혼입 차단 (실사례: 본문/제목에 키릴 "зарубеж" → LIVE 유출)
    foreign_hit = FOREIGN_SCRIPT_RE.search(visible)
    if foreign_hit:
        issues.append(f"foreign_script_in_body:{foreign_hit.group(0)}")

    if _requires_official_sources(content_type=content_type, topic_group=topic_group):
        source_links = _official_source_link_count(content)
        if source_links < 2:
            issues.append(f"official_source_links_below_2:{source_links}")

    if _has_post_document_shell(content):
        issues.append("post_body_contains_document_shell_or_meta")

    paa_questions = _extract_paa_questions(content)
    question_like_paa_count = sum(1 for item in paa_questions if _is_question_like_paa_item(item))
    if question_like_paa_count:
        issues.append(f"question_like_paa_items:{question_like_paa_count}")
    question_budget = _question_budget_metrics(content)
    if question_budget["question_heading_count"] > 5:
        issues.append(f"visible_question_headings_above_5:{question_budget['question_heading_count']}")
    if (
        question_budget["intent_qa_count"] >= 3
        and question_budget["faq_card_count"] >= 3
        and question_budget["paa_item_count"] >= 5
    ):
        issues.append("aeo_visible_question_blocks_overstacked:intent,paa,faq")
    if len(set(paa_questions)) < len(paa_questions):
        warnings.append("duplicate_people_also_ask_questions")
    if _is_delivery_schedule_issue(f"{topic} {visible}") and _has_delivery_irrelevant_paa(paa_questions):
        issues.append("delivery_issue_contains_irrelevant_consumer_paa")
    if content_type == "viral_issue_decode" and _has_problem_solution_terms(visible):
        warnings.append("viral_issue_contains_problem_solution_terms")
    if content_type == "today_issue_explainer" and _has_forced_action_terms(visible):
        warnings.append("timeline_issue_contains_forced_action_terms")
    stale_evidence = _stale_evidence_warning(visible)
    if stale_evidence:
        warnings.append(stale_evidence)

    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "metrics": {
            "replacement_count": replacement_count,
            "question_run_count": question_run_count,
            "latin_mojibake_count": latin_mojibake_count,
            "compatibility_hanja_count": compatibility_hanja_count,
            "intent_answer_count": len(intent_answers),
            "faq_answer_count": len(faq_answers),
            "low_quality_answer_count": bad_answer_count,
            "repeated_answer_count": repeated_answers,
            "people_also_ask_count": len(paa_questions),
            "visible_question_heading_count": question_budget["question_heading_count"],
            "intent_qa_count_visible": question_budget["intent_qa_count"],
            "faq_card_count_visible": question_budget["faq_card_count"],
            "paa_item_count_visible": question_budget["paa_item_count"],
            "empty_table_cell_count": empty_td_count,
            "controlled_hashtag_count": controlled_hashtags,
            "content_type": content_type,
            "topic_group": topic_group,
            "yomi_clean_post_layout": "yomi-clean-post" in content,
            "yomi_clean_layout": clean_layout,
        },
    }


def _visible_text(html: str) -> str:
    content = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<[^>]+>", " ", content)
    return " ".join(unescape(content).split())


def _extract_title_like_texts(html: str) -> list[str]:
    texts: list[str] = []
    for tag in ("h1", "h2", "h3", "title"):
        for match in re.finditer(
            rf"<{tag}\b[^>]*>(.*?)</{tag}>",
            html or "",
            flags=re.IGNORECASE | re.DOTALL,
        ):
            text = _visible_text(match.group(1))
            if text:
                texts.append(text)
    return texts


def _controlled_hashtag_count(html: str) -> int:
    total = 0
    for match in re.finditer(
        r'<section\b(?=[^>]*(?:data-yomi-block=["\']hashtags["\']|class=["\'][^"\']*\byomi-hashtags\b))[^>]*>(.*?)</section>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        total += len(re.findall(r"#[가-힣A-Za-z0-9_]{2,}", _visible_text(match.group(1))))
    return total


def _empty_table_cell_count(html: str) -> int:
    count = 0
    for match in re.finditer(r"<td\b[^>]*>(.*?)</td>", html or "", flags=re.IGNORECASE | re.DOTALL):
        text = _visible_text(match.group(1)).replace("\xa0", " ").strip()
        if not text:
            count += 1
    return count


def _requires_official_sources(*, content_type: str, topic_group: str) -> bool:
    haystack = f"{content_type} {topic_group}".lower()
    return any(
        token in haystack
        for token in ("consumer", "refund", "policy", "tax", "delivery_money", "platform_change")
    )


def _official_source_link_count(html: str) -> int:
    block = _extract_section_html(html, "SOURCE_TRUST_BLOCK") or html
    return len(re.findall(r"<a\b[^>]*\bhref=[\"']https?://", block, flags=re.IGNORECASE))


def _has_post_document_shell(html: str) -> bool:
    return bool(re.search(r"<!doctype\b|</?(?:html|head|body)\b|<title\b|<meta\b", html or "", flags=re.IGNORECASE))


def _extract_section_html(html: str, section_id: str) -> str:
    match = re.search(
        rf'<section\b(?=[^>]*id=["\']{re.escape(section_id)}["\'])[^>]*>(.*?)</section>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _extract_intent_answers(html: str) -> list[str]:
    answers: list[str] = []
    for match in re.finditer(
        r'<(?P<tag>div|article)\b[^>]*class=["\'][^"\']*intent-qa-item[^"\']*["\'][^>]*>(?P<body>.*?)</(?P=tag)>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        body = match.group("body")
        p_match = re.search(r"<p\b[^>]*>(.*?)</p>", body, flags=re.IGNORECASE | re.DOTALL)
        if p_match:
            answers.append(_visible_text(p_match.group(1)))
    return answers


def _extract_faq_answers(html: str) -> list[str]:
    answers: list[str] = []
    for match in re.finditer(
        r'<(?P<tag>div|article)\b[^>]*class=["\'][^"\']*faq-(?:card|item)[^"\']*["\'][^>]*>(?P<body>.*?)</(?P=tag)>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        body = match.group("body")
        for p_match in re.finditer(r"<p\b[^>]*>(.*?)</p>", body, flags=re.IGNORECASE | re.DOTALL):
            text = _visible_text(p_match.group(1))
            if text:
                answers.append(text)
    return answers


def _extract_paa_questions(html: str) -> list[str]:
    return [
        _visible_text(match.group(1))
        for match in re.finditer(
            r'<li\b[^>]*class=["\'][^"\']*paa-item[^"\']*["\'][^>]*>(.*?)</li>',
            html or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def _is_question_like_paa_item(text: str) -> bool:
    value = " ".join((text or "").split()).strip()
    if not value:
        return False
    return bool(
        re.search(r"[?？]$", value)
        or re.search(r"(가요|나요|하나요|되나요|인가요|일까요|하는지|되는지|인지|한지)$", value)
    )


_QUESTION_HEADING_END = re.compile(
    r"(나요|까요|가요|은가요|는가요|인가요|을까요|일까요|할까요|될까요|하나요|되나요|합니까|입니까|습니까)\??$"
)


def _heading_text_is_question(text: str) -> bool:
    """헤딩이 실제 질문인지 판정. 'directly 필요/중요/내용'처럼 '요'로 끝나는
    서술형을 질문으로 오탐하지 않도록 의문 종결어미·의문사·물음표만 인정한다."""
    t = " ".join((text or "").split())
    if not t:
        return False
    if "?" in t or "무엇" in t or "왜" in t:
        return True
    return bool(_QUESTION_HEADING_END.search(t))


def _question_budget_metrics(html: str) -> dict[str, int]:
    headings = [
        _visible_text(match.group(1))
        for match in re.finditer(r"<h[123]\b[^>]*>(.*?)</h[123]>", html or "", flags=re.IGNORECASE | re.DOTALL)
    ]
    question_headings = [text for text in headings if _heading_text_is_question(text)]
    return {
        "question_heading_count": len(question_headings),
        "intent_qa_count": len(re.findall(r'class=["\'][^"\']*intent-qa-item', html or "", flags=re.IGNORECASE)),
        "faq_card_count": len(re.findall(r'class=["\'][^"\']*faq-card', html or "", flags=re.IGNORECASE)),
        "paa_item_count": len(re.findall(r'class=["\'][^"\']*paa-item', html or "", flags=re.IGNORECASE)),
    }


def _clean_layout_metrics(html: str) -> dict[str, Any]:
    content = html or ""
    present = bool(
        re.search(
            r'<article\b[^>]*class=["\'][^"\']*\byomi-clean-post\b',
            content,
            flags=re.IGNORECASE,
        )
    )
    if not present:
        return {
            "present": False,
            "lede_count": 0,
            "adaptive_module_count": 0,
            "inline_style_count": 0,
            "details_count": 0,
        }

    lede_count = len(
        re.findall(r'class=["\'][^"\']*\byomi-lede\b', content, flags=re.IGNORECASE)
    )
    module_markers = (
        "yomi-thesis",
        "yomi-risk",
        "yomi-list",
        "yomi-lens",
        "yomi-note",
        "yomi-paa-compact",
        "confirmed-needed-box",
    )
    adaptive_module_count = sum(
        1
        for marker in module_markers
        if re.search(rf'class=["\'][^"\']*\b{re.escape(marker)}\b', content, flags=re.IGNORECASE)
    )
    body_without_code = re.sub(
        r"<(?:script|style)\b.*?</(?:script|style)>",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    inline_style_count = len(
        re.findall(r"<[a-zA-Z][^>]*\sstyle\s*=", body_without_code, flags=re.IGNORECASE)
    )
    details_count = len(re.findall(r"<details\b", body_without_code, flags=re.IGNORECASE))
    return {
        "present": True,
        "lede_count": lede_count,
        "adaptive_module_count": adaptive_module_count,
        "inline_style_count": inline_style_count,
        "details_count": details_count,
    }


def _extract_section_text(html: str, section_id: str) -> str:
    match = re.search(
        rf'<section\b[^>]*id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _visible_text(match.group(1)) if match else ""


def _visible_internal_section_labels(html: str) -> list[str]:
    labels: list[str] = []
    for match in re.finditer(
        r'<p\b[^>]*class=["\'][^"\']*\bsection-label\b[^"\']*["\'][^>]*>(.*?)</p>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = _visible_text(match.group(1))
        if text in {"도입", "해시태그"} and text not in labels:
            labels.append(text)
    return labels


def _repeated_summary_heading_count(html: str) -> int:
    repeated_labels = {"핵심 요약", "이 이슈의 핵심", "오늘 이슈 3줄 요약"}
    count = 0
    for match in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", html or "", flags=re.IGNORECASE | re.DOTALL):
        if _visible_text(match.group(1)) in repeated_labels:
            count += 1
    return count


def _is_low_quality_answer(answer: str) -> bool:
    text = " ".join((answer or "").split())
    if len(text) < 18:
        return True
    if text.startswith(("으로 ", "라고 ", "에는 ", "에서는 ", "입니다", "합니다", "다만 ")):
        return True
    if text.count("공식") >= 2 and len(text) < 45:
        return True
    if "으로 단정하면 안 됩니다" in text:
        return True
    if re.search(r"(핵심 영향|대상|기준일).{0,20}(핵심 영향|대상|기준일)", text):
        return True
    return False


def _is_low_quality_overview(text: str) -> bool:
    clean = " ".join((text or "").split())
    if len(clean) < 35:
        return True
    if clean.startswith(("AI활용 유형", "카테고리:", "유형:")):
        return True
    return _is_low_quality_answer(clean)


def _repeated_answer_count(answers: list[str]) -> int:
    normalized = [
        re.sub(r"[\s,.!?·\-]+", "", answer or "")[:90]
        for answer in answers
        if len(answer or "") >= 18
    ]
    if not normalized:
        return 0
    counts = Counter(normalized)
    return max(counts.values(), default=0)


def _is_delivery_schedule_issue(text: str) -> bool:
    haystack = (text or "").lower()
    return any(token in haystack for token in ("택배", "배송", "집화", "cj", "한진", "롯데", "쿠팡", "새벽배송"))


def _has_delivery_irrelevant_paa(questions: list[str]) -> bool:
    joined = " ".join(questions)
    irrelevant = ("환불 거부", "소비자 피해 신고", "결제 오류", "개인정보 유출")
    return any(token in joined for token in irrelevant)


def _has_problem_solution_terms(text: str) -> bool:
    return sum(1 for token in ("신청", "환급", "환불", "택배", "배송", "지원금", "대상 조건") if token in text) >= 2


def _has_forced_action_terms(text: str) -> bool:
    return sum(1 for token in ("신청 방법", "환급", "대응 절차", "오늘 바로 할 체크리스트") if token in text) >= 2


def _stale_evidence_warning(visible: str) -> str:
    """본문이 인용한 연·월 근거가 전부 12개월 이상 묵었으면 경고(비차단).

    실사례(2026-07-11): 발행일이 2026-07인데 도입부 핵심 근거가 "2025년 5월
    기준 직장인 조사"뿐이었다 — 뉴스 블로그 글이 14개월 전 통계로 굴러갔다.
    날짜 인용이 아예 없는 글은 신호가 없으므로 경고하지 않고, 최근 12개월
    내 날짜가 하나라도 있으면 오래된 배경 인용은 허용한다.
    """
    from blogspot_automation.services.kst_clock import kst_today

    try:
        today = date.fromisoformat(kst_today("%Y-%m-%d"))
    except Exception:
        return ""
    cited: list[tuple[int, int]] = []
    for match in re.finditer(r"(20\d{2})년\s*(\d{1,2})월", visible or ""):
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and 2015 <= year <= today.year + 1:
            cited.append((year, month))
    if not cited:
        return ""
    newest_year, newest_month = max(cited)
    age_months = (today.year - newest_year) * 12 + (today.month - newest_month)
    if age_months >= 12:
        return f"stale_evidence_dates:newest_{newest_year}-{newest_month:02d}"
    return ""
