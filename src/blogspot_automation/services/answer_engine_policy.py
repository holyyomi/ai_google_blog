from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html import escape, unescape
from typing import Any

from blogspot_automation.services.geo_intent_service import GeoIntentService
from blogspot_automation.services.news_taxonomy import content_type_for_topic_group


# 기계적 SEO 라벨("먼저 볼 핵심" 등) 대신 사람 에디터 말투로, 글마다 다르게 변주한다.
# AI가 쓴 티를 줄이는 핵심 장치. (seed=토픽으로 결정적 선택 → 같은 글은 항상 같은 라벨)
_LABEL_VARIANTS: dict[str, tuple[str, ...]] = {
    "overview": ("결론부터 말하면", "핵심부터 짚으면", "한 줄로 먼저", "짧게 보면 이렇습니다"),
    "context": ("왜 지금 터졌나", "이 일이 불거진 배경", "지금 주목받는 이유", "타이밍부터 보면"),
    "intent": ("많이들 궁금해하는 것", "이건 짚고 넘어가죠", "자주 나오는 물음", "여기서 헷갈리기 쉬운 것"),
    "confirmed": ("지금까지 확인된 것", "사실과 추측, 이렇게 갈립니다", "확인된 것과 아직인 것"),
    "trust": ("어디서 확인했나", "참고한 보도", "근거"),
}


def _varied_label(kind: str, seed: str) -> str:
    variants = _LABEL_VARIANTS.get(kind, ())
    if not variants:
        return ""
    digest = hashlib.md5((seed or kind).encode("utf-8")).hexdigest()
    return variants[int(digest, 16) % len(variants)]


def ensure_answer_engine_optimized_html(
    html: str,
    *,
    title: str,
    topic: str = "",
    content_type: str = "",
    topic_group: str = "",
    reader_questions: list[str] | tuple[str, ...] | None = None,
    today: str = "",
    faq_items: list[dict[str, str]] | None = None,
    confirmed_facts: list[str] | None = None,
    check_needed: list[str] | None = None,
) -> str:
    """Add AEO/GEO/SGE blocks to any publish HTML path.

    This is intentionally deterministic. It does not chase query variants by
    creating more pages; it strengthens the one article around the user's
    likely question, answer need, source trust, and follow-up questions.
    """
    content = html or ""
    if not content.strip():
        return content

    # 본문 중간의 FAQ를 먼저 글 끝으로 이동해야 한다 — normalize가 첫 yomi-faq에
    # INTENT_ANSWER_BLOCK id를 부여하므로, 이동 전에 normalize가 돌면 FAQ가
    # 본문 중간에 시스템 블록으로 고정돼 'FAQ 뒤에 본문이 이어지는' 깨진 구조가 된다.
    content = _relocate_body_faq_to_tail(content)
    content = _normalize_existing_clean_answer_sections(content)
    content = _collapse_visible_question_overstack(content)
    resolved_type = (content_type or content_type_for_topic_group(topic_group)).strip() or "general_life"
    today = today or datetime.now().strftime("%Y-%m-%d")
    topic_text = " ".join((topic or title or "오늘 이슈").split()).strip()
    slots = _build_slots_from_html(content, title=title, topic=topic_text)
    has_author_answer_sections = _has_author_answer_sections(content)

    service = GeoIntentService()
    generated_questions = service.generate_reader_intent_questions(
        topic=topic_text,
        content_type=resolved_type,
        topic_group=topic_group,
        slots=slots,
    )
    questions = _merge_questions(reader_questions or [], generated_questions, title=title, topic=topic_text)
    intent_answers = service.generate_intent_answers(
        questions=questions,
        topic=topic_text,
        content_type=resolved_type,
        slots=slots,
    )
    if len(intent_answers) < 3:
        intent_answers.extend(_fallback_intent_answers(questions, topic_text))
        intent_answers = intent_answers[:5]

    overview = service.generate_ai_overview_target_answer(
        topic=topic_text,
        content_type=resolved_type,
        slots=slots,
    )
    issue_context = service.generate_issue_context(
        topic=topic_text,
        content_type=resolved_type,
        hook=str(slots.get("hook_opening") or ""),
    )
    people_also_ask = service.generate_people_also_ask(
        questions=questions,
        topic=topic_text,
        content_type=resolved_type,
    )
    people_also_ask = _dedupe_people_also_ask(
        people_also_ask,
        intent_answers,
        topic=topic_text,
        content_type=resolved_type,
    )
    confirmed_map = service.generate_confirmed_vs_check_needed(
        content_type=resolved_type,
        topic_group=topic_group,
        slots=slots,
        topic=topic_text,
    )
    # 본문을 쓴 LLM이 뽑은 이슈 특정적 사실 목록이 있으면 템플릿 대신 사용한다.
    # (템플릿 문장은 모든 글에서 반복돼 AI 티의 주범 — 폴백 전용으로 강등.)
    _llm_confirmed = _clean_fact_list(confirmed_facts, max_items=3)
    _llm_check = _clean_fact_list(check_needed, max_items=2)
    if _llm_confirmed and _llm_check:
        confirmed_map = {"confirmed": _llm_confirmed, "check_needed": _llm_check}
    trust_text = service.generate_enhanced_source_trust_block(
        content_type=resolved_type,
        topic_group=topic_group,
        pattern_id="",
        today_str=today,
        seed=topic_text or title,
    )

    _seed = topic_text or title or ""
    # today_issue 해설글은 본문(LLM)이 이미 풍부한 맥락·다관점을 담는다.
    # - PAA(검색어 목록)는 가장 AI 티 나는 군더더기 → 항상 억제.
    # - ISSUE_CONTEXT(배경)는 본문과 중복되기 쉬움 → 본문이 자체 모듈을 1개 이상 가졌으면
    #   드롭(중복 제거). 본문이 모듈-라이트면 유지해 adaptive module 수(≥2)를 보장한다.
    #   (CONFIRMED_VS_CHECK가 항상 1개 모듈을 보태므로 본문 모듈 1개면 안전.)
    # 소비자/정책(골든) 경로는 geo_score 영향이 있으므로 일절 건드리지 않는다.
    _author_rich_today = has_author_answer_sections and (
        resolved_type == "today_issue_explainer" or topic_group == "today_issue"
    )
    _body_module_count = sum(
        1
        for marker in ("yomi-thesis", "yomi-risk", "yomi-list", "yomi-lens")
        if re.search(rf'class=["\'][^"\']*\b{marker}\b', content, flags=re.IGNORECASE)
    )
    _drop_issue_context = _author_rich_today and _body_module_count >= 1
    # 본문 LLM이 만든 이슈 특정적 Q&A가 있으면 템플릿 intent 답변 대신 visible
    # 블록에 사용한다 — 본문과 같은 목소리, 같은 사실 기반.
    llm_faq_pairs = _normalize_llm_faq_pairs(faq_items)
    use_llm_intent = bool(llm_faq_pairs) and _author_rich_today
    head_blocks: list[str] = []
    if 'id="AI_OVERVIEW_TARGET_ANSWER"' not in content:
        head_blocks.append(_section("AI_OVERVIEW_TARGET_ANSWER", "yomi-lede", _varied_label("overview", _seed), overview))
    if 'id="ISSUE_CONTEXT_BLOCK"' not in content and not _drop_issue_context:
        head_blocks.append(_section("ISSUE_CONTEXT_BLOCK", "yomi-note", _varied_label("context", _seed), issue_context))
    if 'id="INTENT_ANSWER_BLOCK"' not in content:
        _intent_items = llm_faq_pairs[:3] if use_llm_intent else intent_answers
        head_blocks.append(_intent_answer_block(_intent_items, label=_varied_label("intent", _seed)))
    if 'id="PEOPLE_ALSO_ASK_BLOCK"' not in content and not _author_rich_today:
        head_blocks.append(_people_also_ask_block(people_also_ask))

    if head_blocks:
        head_bundle = "\n".join(head_blocks)
        if has_author_answer_sections:
            content = _insert_before_internal_links_or_body_end(
                content,
                _wrap_answer_engine_support(head_bundle),
            )
        else:
            content = _insert_after_h1_or_prepend(content, head_bundle)

    tail_blocks: list[str] = []
    if 'id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"' not in content:
        tail_blocks.append(_confirmed_vs_check_needed_block(confirmed_map, label=_varied_label("confirmed", _seed)))
    if 'id="SOURCE_TRUST_BLOCK"' not in content:
        tail_blocks.append(_section("SOURCE_TRUST_BLOCK", "yomi-source", _varied_label("trust", _seed), trust_text))
    if tail_blocks:
        content = _insert_before_internal_links_or_body_end(content, "\n".join(tail_blocks))

    if not _has_faq_section(content):
        content = _insert_before_internal_links_or_body_end(content, _faq_block(intent_answers))
    if '"@type": "FAQPage"' not in content and '"@type":"FAQPage"' not in content:
        # 본문을 쓴 LLM의 이슈 특정적 faq_items가 있으면 그것으로 FAQPage 구조화
        # 데이터를 만든다. 구글 rich result 정책상 구조화 데이터는 페이지에 visible한
        # 내용과 일치해야 하므로, visible intent 3개 + 본문 yomi-faq 질문을 합친다.
        # 템플릿 intent_answers는 폴백 전용.
        if use_llm_intent:
            _body_faq = [
                p
                for p in (slots.get("faq") or [])
                if isinstance(p, dict) and _heading_text_is_question(str(p.get("Q") or ""))
            ]
            _ld_pairs = _dedupe_qa_pairs(llm_faq_pairs[:3] + _body_faq)
            content = _insert_json_ld(content, _faq_json_ld(_ld_pairs, max_items=5))
        elif llm_faq_pairs:
            content = _insert_json_ld(content, _faq_json_ld(llm_faq_pairs, max_items=5))
        else:
            content = _insert_json_ld(content, _faq_json_ld(intent_answers))
    if '"@type": "BlogPosting"' not in content and '"@type":"BlogPosting"' not in content:
        content = _insert_json_ld(content, _blogposting_json_ld(title=title, topic=topic_text, today=today))
    content = _collapse_visible_question_overstack(content)
    # 블록을 모두 추가한 뒤 최종 질문헤딩 예산(≤5) 보장. 본문이 자체 질문 h2를
    # 갖고 있고 여기서 intent Q&A까지 더해지면 누적 초과 → 감사 차단되던 문제 해소.
    content = _demote_excess_question_headings(content, max_count=5)

    try:
        from blogspot_automation.services.seo_policy import ensure_yomi_clean_article_layout

        content = ensure_yomi_clean_article_layout(content)
    except Exception:
        pass

    return content


def answer_engine_coverage(html: str) -> dict[str, object]:
    content = html or ""
    return {
        "ai_overview_target_answer_present": 'id="AI_OVERVIEW_TARGET_ANSWER"' in content,
        "issue_context_present": 'id="ISSUE_CONTEXT_BLOCK"' in content,
        "intent_answer_present": 'id="INTENT_ANSWER_BLOCK"' in content,
        "intent_qa_count": len(re.findall(r'class=["\'][^"\']*intent-qa-item', content)),
        "people_also_ask_present": 'id="PEOPLE_ALSO_ASK_BLOCK"' in content,
        "people_also_ask_count": len(re.findall(r'class=["\'][^"\']*paa-item', content)),
        "confirmed_vs_check_needed_present": 'id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"' in content,
        "source_trust_block_present": 'id="SOURCE_TRUST_BLOCK"' in content,
        "faq_section_present": _has_faq_section(content),
        "faqpage_json_ld_present": '"@type": "FAQPage"' in content or '"@type":"FAQPage"' in content,
        "blogposting_json_ld_present": '"@type": "BlogPosting"' in content or '"@type":"BlogPosting"' in content,
    }


def _build_slots_from_html(html: str, *, title: str, topic: str) -> dict[str, Any]:
    scoped_html = _content_scope_html(html)
    plain = _plain_text(scoped_html)
    faq = _extract_faq_pairs(scoped_html)
    sentences = _sentences(plain, max_items=4)
    first_sentence = sentences[0] if sentences else _first_sentence(plain, max_len=180)
    second_sentence = ""
    for sentence in sentences[1:]:
        if sentence != first_sentence and len(sentence) >= 20:
            second_sentence = sentence
            break
    hook = first_sentence or f"{topic}에 대해 독자가 먼저 확인해야 할 핵심을 정리했습니다."
    return {
        "hook_opening": hook,
        "real_criterion": second_sentence or _first_sentence(plain, max_len=160) or hook,
        "yomi_judgment": f"핵심은 {title or topic}을 단순 반응이 아니라 실제 영향과 확인 기준으로 나누어 보는 것입니다.",
        "faq": faq,
    }


def _merge_questions(
    primary: list[str] | tuple[str, ...],
    fallback: list[str],
    *,
    title: str,
    topic: str,
) -> list[str]:
    merged: list[str] = []
    for value in [*primary, *fallback]:
        q = " ".join(str(value or "").split()).strip()
        if not q:
            continue
        if not q.endswith("?") and not q.endswith("요?") and not q.endswith("까?"):
            q = f"{q}?"
        if q not in merged:
            merged.append(q)
        if len(merged) >= 8:
            break
    if len(merged) < 5:
        seed = topic or title or "이 이슈"
        for q in (
            f"{seed}에서 지금 가장 먼저 확인할 것은 무엇인가요?",
            "나에게 직접 영향이 있는지 어떻게 확인하나요?",
            "공식 정보는 어디에서 확인해야 하나요?",
            "주의해야 할 오해는 무엇인가요?",
            "오늘 바로 할 일은 무엇인가요?",
        ):
            if q not in merged:
                merged.append(q)
            if len(merged) >= 5:
                break
    return merged[:8]


def _fallback_intent_answers(questions: list[str], topic: str) -> list[dict[str, str]]:
    answers: list[dict[str, str]] = []
    for question in questions[:5]:
        answers.append(
            {
                "Q": question,
                "A": f"{topic}은 공식 안내, 적용 대상, 실제 영향 순서로 확인하는 것이 안전합니다.",
            }
        )
    return answers


def _section(section_id: str, css_class: str, heading: str, text: str) -> str:
    return (
        f'<section id="{section_id}" class="{css_class}">'
        f'<h2>{escape(heading)}</h2>'
        f'<p>{escape(" ".join((text or "").split()))}</p>'
        "</section>"
    )


def _intent_answer_block(items: list[dict[str, str]], *, label: str = "") -> str:
    body = "".join(
        '<div class="intent-qa-item">'
        f'<h3>Q. {escape(str(item.get("Q") or ""))}</h3>'
        f'<p>A. {escape(str(item.get("A") or ""))}</p>'
        "</div>"
        for item in items[:3]
        if item.get("Q") and item.get("A")
    )
    heading = label or "많이들 궁금해하는 것"
    return (
        '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq">'
        f"<h2>{escape(heading)}</h2>"
        f"{body}"
        "</section>"
    )


def _people_also_ask_block(questions: list[str], *, label: str = "") -> str:
    items = "".join(f'<li class="paa-item">{escape(_search_phrase_from_question(str(q)))}</li>' for q in questions[:5])
    heading = label or "이어서 찾아보면 좋은 것"
    return (
        '<section id="PEOPLE_ALSO_ASK_BLOCK" class="yomi-paa-compact">'
        f"<h2>{escape(heading)}</h2>"
        f"<ul>{items}</ul>"
        "</section>"
    )


def _search_phrase_from_question(question: str) -> str:
    text = " ".join((question or "").split()).strip()
    text = re.sub(r"[?？]+$", "", text)
    if "무료배송" in text and "결제금액" in text and ("비교" in text or "기준" in text):
        return "무료배송 결제금액 비교 기준"
    if "쿠폰" in text and ("저렴" in text or "최종" in text):
        return "쿠폰 적용 후 최종금액 비교"
    if "최소주문금액" in text and "미달" in text:
        return "최소주문금액 미달 조건"
    if "앱별" in text and "결제금액" in text:
        return "앱별 결제금액 차이"
    text = text.replace("무엇을 기준으로 비교해야", "비교 기준")
    text = text.replace("무엇을 기준으로 비교", "비교 기준")
    replacements = (
        ("무엇인가요", ""),
        ("무엇인가", ""),
        ("무엇인가요", ""),
        ("한가요", "한지"),
        ("되나요", "되는지"),
        ("있나요", "있는지"),
        ("없나요", "없는지"),
        ("하나요", "하는지"),
        ("인가요", "인지"),
        ("일까요", "일지"),
        ("왜", ""),
        ("어떻게", ""),
        ("나요", ""),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r"(은|는)\s+비교 기준\s+하는지$", r" 비교 기준", text)
    text = re.sub(r"(하는지|되는지|인지|한지)$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,·-")
    return text or "관련 확인 포인트"


def _dedupe_people_also_ask(
    questions: list[str],
    intent_answers: list[dict[str, str]],
    *,
    topic: str,
    content_type: str,
) -> list[str]:
    intent_keys = {
        _normalize_question_key(str(item.get("Q") or ""))
        for item in intent_answers
        if item.get("Q")
    }
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in [*questions, *_paa_search_fallbacks(topic=topic, content_type=content_type)]:
        question = " ".join(str(value or "").split()).strip()
        key = _normalize_question_key(question)
        if not question or not key:
            continue
        if _is_near_duplicate_question_key(key, intent_keys) or _is_near_duplicate_question_key(key, seen):
            continue
        cleaned.append(question)
        seen.add(key)
        if len(cleaned) >= 5:
            break
    return cleaned


def _paa_search_fallbacks(*, topic: str, content_type: str) -> list[str]:
    topic_text = " ".join((topic or "이 주제").split()).strip()
    if content_type in {"money_checklist", "delivery_money"}:
        return [
            "배달앱 무료 배달 조건",
            "배달앱 쿠폰 적용 안 되는 이유",
            "배달비 최소주문금액 기준",
            "배달앱별 최종 결제금액 차이",
            "주문 전 결제금액 확인 방법",
        ]
    if content_type in {"policy_benefit", "policy_deadline", "tax_refund"}:
        return [
            f"{topic_text} 대상 조건",
            f"{topic_text} 신청 마감일",
            f"{topic_text} 필요 서류",
            f"{topic_text} 공식 문의처",
            f"{topic_text} 지급 방식",
        ]
    if content_type == "viral_issue_decode":
        return [
            f"{topic_text} 확인된 내용",
            f"{topic_text} 루머 사실 구분",
            f"{topic_text} 시청 전 체크포인트",
            f"{topic_text} 반응이 갈린 이유",
            f"{topic_text} 다음 쟁점",
        ]
    return [
        f"{topic_text} 확인된 내용",
        f"{topic_text} 직접 영향",
        f"{topic_text} 공식 확인처",
        f"{topic_text} 주의할 점",
        f"{topic_text} 다음 단계",
    ]


def _normalize_question_key(text: str) -> str:
    key = re.sub(r"[^0-9A-Za-z가-힣]+", "", (text or "").lower())
    replacements = {
        "어떻게확인하나요": "확인",
        "어떻게확인하나": "확인",
        "어디에서확인하나요": "확인",
        "어디서확인하나요": "확인",
        "무엇을기준으로비교해야하나요": "비교기준",
        "무엇을기준으로비교하나요": "비교기준",
        "무엇인가요": "",
        "무엇인가": "",
    }
    for source, target in replacements.items():
        key = key.replace(source, target)
    key = re.sub(r"(인가요|인가|하나요|하나|나요|습니까|까요|까|요)$", "", key)
    return key


def _is_near_duplicate_question_key(key: str, seen_keys: set[str]) -> bool:
    if key in seen_keys:
        return True
    for seen in seen_keys:
        if min(len(key), len(seen)) >= 10 and (key in seen or seen in key):
            return True
    return False


def _confirmed_vs_check_needed_block(items: dict[str, list[str]], *, label: str = "") -> str:
    confirmed = "".join(f"<li>{escape(str(item))}</li>" for item in items.get("confirmed", [])[:5])
    check_needed = "".join(f"<li>{escape(str(item))}</li>" for item in items.get("check_needed", [])[:5])
    heading = label or "지금까지 확인된 것"
    return (
        '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">'
        f"<h2>{escape(heading)}</h2>"
        '<div class="confirmed-section"><h3>확인된 내용</h3>'
        f"<ul>{confirmed}</ul></div>"
        '<div class="check-needed-section"><h3>직접 확인 필요</h3>'
        f"<ul>{check_needed}</ul></div>"
        "</section>"
    )


def _faq_block(items: list[dict[str, str]]) -> str:
    cards = "".join(
        '<div class="faq-card">'
        f'<h3>{escape(str(item.get("Q") or ""))}</h3>'
        f'<p>{escape(str(item.get("A") or ""))}</p>'
        "</div>"
        for item in items[:5]
        if item.get("Q") and item.get("A")
    )
    return f'<section class="yomi-faq"><h2>자주 묻는 질문</h2>{cards}</section>'


def _collapse_visible_question_overstack(html: str) -> str:
    content = html or ""
    content = _limit_visible_intent_answers(content, max_items=3)
    content = _normalize_visible_paa_items(content)

    intent_count = len(re.findall(r'class=["\'][^"\']*intent-qa-item', content, flags=re.IGNORECASE))
    if intent_count < 3:
        return content

    def remove_extra_faq_section(match: re.Match[str]) -> str:
        section = match.group(0)
        if 'id="INTENT_ANSWER_BLOCK"' in section or "id='INTENT_ANSWER_BLOCK'" in section:
            return section
        if "faq-card" in section:
            return ""
        return section

    content = re.sub(
        r'<section\b(?=[^>]*class=["\'][^"\']*faq[^"\']*["\'])[^>]*>.*?</section>',
        remove_extra_faq_section,
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return content


_QUESTION_HEADING_END = re.compile(
    r"(나요|까요|가요|은가요|는가요|인가요|을까요|일까요|할까요|될까요|하나요|되나요|합니까|입니까|습니까)\??$"
)


def _heading_text_is_question(text: str) -> bool:
    # final_html_audit_service._heading_text_is_question와 동일 규약 유지.
    t = " ".join((text or "").split())
    if not t:
        return False
    if "?" in t or "무엇" in t or "왜" in t:
        return True
    return bool(_QUESTION_HEADING_END.search(t))


def _demote_excess_question_headings(html: str, *, max_count: int = 5) -> str:
    """visible 질문형 헤딩이 max_count를 넘으면 본문의 '느슨한' 질문 h2/h3를
    문단(<p>)으로 강등해 예산 이내로 맞춘다. 구조화된 AEO 블록
    (intent-qa-item, faq-card) 안의 질문은 보존한다."""
    content = html or ""
    structured_spans: list[tuple[int, int]] = [
        (m.start(), m.end())
        for m in re.finditer(
            r'<article\b[^>]*class=["\'][^"\']*intent-qa-item[^"\']*["\'].*?</article>',
            content, flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    structured_spans += [
        (m.start(), m.end())
        for m in re.finditer(
            r'<div\b[^>]*class=["\'][^"\']*faq-card[^"\']*["\'].*?</div>',
            content, flags=re.IGNORECASE | re.DOTALL,
        )
    ]

    def _structured(pos: int) -> bool:
        return any(start <= pos < end for start, end in structured_spans)

    headings = list(re.finditer(r"<(h[23])\b[^>]*>(.*?)</\1>", content, flags=re.IGNORECASE | re.DOTALL))
    q_headings = [
        m for m in headings
        if _heading_text_is_question(re.sub(r"<[^>]+>", " ", m.group(2)))
    ]
    if len(q_headings) <= max_count:
        return content
    excess = len(q_headings) - max_count
    loose = [m for m in q_headings if not _structured(m.start())]
    chosen = loose[:excess]
    for m in sorted(chosen, key=lambda x: x.start(), reverse=True):
        inner = m.group(2)
        content = (
            content[: m.start()]
            + f'<p class="yomi-subhead"><strong>{inner}</strong></p>'
            + content[m.end():]
        )
    return content


def _limit_visible_intent_answers(html: str, *, max_items: int) -> str:
    def trim_section(match: re.Match[str]) -> str:
        section = match.group(0)
        count = 0

        def keep_or_drop(item_match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if count <= max_items:
                return item_match.group(0)
            return ""

        return re.sub(
            r'<(?P<tag>div|article)\b(?=[^>]*class=["\'][^"\']*intent-qa-item[^"\']*["\'])[^>]*>.*?</(?P=tag)>',
            keep_or_drop,
            section,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return re.sub(
        r'<section\b(?=[^>]*id=["\']INTENT_ANSWER_BLOCK["\'])[^>]*>.*?</section>',
        trim_section,
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )


def _normalize_visible_paa_items(html: str) -> str:
    def replace_item(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        phrase = escape(_search_phrase_from_question(_plain_text(match.group("body"))))
        return f"<li{attrs}>{phrase}</li>"

    return re.sub(
        r'<li(?P<attrs>[^>]*class=["\'][^"\']*paa-item[^"\']*["\'][^>]*)>(?P<body>.*?)</li>',
        replace_item,
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )


def _faq_json_ld(items: list[dict[str, str]], *, max_items: int = 3) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": str(item.get("Q") or ""),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": str(item.get("A") or ""),
                },
            }
            for item in items[:max_items]
            if item.get("Q") and item.get("A")
        ],
    }


def _relocate_body_faq_to_tail(html: str) -> str:
    """본문 중간의 FAQ 섹션(yomi-faq, INTENT_ANSWER_BLOCK 제외)을 보조 블록
    영역 시작(CONFIRMED_VS_CHECK → SOURCE_TRUST → article 끝 순) 직전으로 이동.

    LLM이 FAQ를 본문 중간에 배치하면 'FAQ 뒤에 본문이 다시 이어지는' 어색한
    구조가 된다. 구조 일관성: 본문 → Q&A/FAQ → 확인된 것 → 출처 → 내부링크.
    """
    content = html or ""
    pattern = re.compile(
        r'\s*<section\b(?![^>]*id=["\']INTENT_ANSWER_BLOCK["\'])'
        r'[^>]*class=["\'][^"\']*\byomi-faq\b[^"\']*["\'][^>]*>.*?</section>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    moved: list[str] = []

    def _extract(match: re.Match[str]) -> str:
        moved.append(match.group(0).strip())
        return ""

    # 마지막 보조 블록 앞에 이미 있는 FAQ는 옮길 필요가 있는지 판단이 복잡하므로
    # 단순·멱등하게: 전부 추출 후 같은 순서로 보조 영역 앞에 재삽입한다.
    stripped = pattern.sub(_extract, content)
    if not moved:
        return content
    bundle = "\n".join(moved)
    for anchor in (
        r'<section\b[^>]*id=["\']CONFIRMED_VS_CHECK_NEEDED_BLOCK["\']',
        r'<section\b[^>]*id=["\']SOURCE_TRUST_BLOCK["\']',
    ):
        m = re.search(anchor, stripped, flags=re.IGNORECASE)
        if m:
            return stripped[: m.start()] + bundle + "\n" + stripped[m.start():]
    last_article = stripped.lower().rfind("</article>")
    if last_article >= 0:
        return stripped[:last_article] + bundle + "\n" + stripped[last_article:]
    return stripped + "\n" + bundle


def _clean_fact_list(items: list[str] | None, *, max_items: int) -> list[str]:
    """LLM이 뽑은 사실 목록 정리 — 짧거나 깨진 항목 제거, 중복 제거."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split()).strip()
        if len(text) < 8:
            continue
        key = re.sub(r"[^가-힣a-zA-Z0-9]", "", text.lower())[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _dedupe_qa_pairs(pairs: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for p in pairs:
        q = str(p.get("Q") or "").strip()
        a = str(p.get("A") or "").strip()
        if not q or not a:
            continue
        key = re.sub(r"[^가-힣a-zA-Z0-9]", "", q.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"Q": q, "A": a})
    return out


def _normalize_llm_faq_pairs(items: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """LLM faq_items({'question','answer'})를 Q/A 페어로 정규화 (구조화 데이터용).

    너무 짧거나 깨진 항목은 버리고 질문 기준으로 중복 제거. 유효 항목이 없으면
    빈 리스트를 반환해 호출부가 템플릿 폴백을 쓰게 한다.
    """
    pairs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        q = " ".join(str(item.get("question") or item.get("Q") or "").split()).strip()
        a = " ".join(str(item.get("answer") or item.get("A") or "").split()).strip()
        if len(q) < 8 or len(a) < 20:
            continue
        key = re.sub(r"[^가-힣a-zA-Z0-9]", "", q.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        pairs.append({"Q": q, "A": a})
        if len(pairs) >= 5:
            break
    return pairs


# E-E-A-T: 저자·발행 주체 엔티티를 소개 페이지와 연결 (실존 페이지)
_ABOUT_PAGE_URL = "https://holyyomiai.blogspot.com/p/about.html"
_SITE_URL = "https://holyyomiai.blogspot.com/"


def _blogposting_json_ld(*, title: str, topic: str, today: str) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title or topic,
        "description": topic or title,
        "datePublished": today,
        "dateModified": today,
        "author": {
            "@type": "Person",
            "name": "요미",
            "url": _ABOUT_PAGE_URL,
            "description": "한국 오늘의 이슈를 복수 보도 교차 확인과 사실·해석 분리 원칙으로 해설하는 에디터",
        },
        "publisher": {
            "@type": "Organization",
            "name": "요미의 오늘 이슈",
            "url": _SITE_URL,
        },
        "mainEntityOfPage": {"@type": "WebPage"},
        # 음성 어시스턴트·AI 요약이 읽어갈 핵심 답변 위치 (SGE/AEO 신호)
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": [".yomi-lede", ".intent-qa-item"],
        },
    }


def _insert_after_h1_or_prepend(html: str, block: str) -> str:
    if re.search(r"</h1>", html, flags=re.IGNORECASE):
        return re.sub(r"</h1>", f"</h1>\n{block}", html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE):
        return re.sub(r"(<body\b[^>]*>)", lambda m: f"{m.group(1)}\n{block}", html, count=1, flags=re.IGNORECASE)
    return f"{block}\n{html}"


def _insert_before_internal_links_or_body_end(html: str, block: str) -> str:
    internal_links = re.search(
        r'<section\b[^>]*data-yomi-block=["\']internal-links["\'][^>]*>',
        html,
        flags=re.IGNORECASE,
    )
    if internal_links:
        pos = internal_links.start()
        return html[:pos] + block + "\n" + html[pos:]
    # 본문 FAQ가 <article> 항목을 중첩 사용하므로, 첫 번째가 아니라 *마지막*
    # </article>(루트 래퍼 닫힘) 앞에 삽입해야 한다. 첫 매치에 넣으면 시스템
    # 블록이 FAQ 한가운데 박혀 'FAQ 뒤에 본문이 또 이어지는' 깨진 구조가 됐다.
    last_article = html.lower().rfind("</article>")
    if last_article >= 0:
        return html[:last_article] + block + "\n" + html[last_article:]
    last_body = html.lower().rfind("</body>")
    if last_body >= 0:
        return html[:last_body] + block + "\n" + html[last_body:]
    return f"{html.rstrip()}\n{block}"


def _normalize_existing_clean_answer_sections(html: str) -> str:
    content = html or ""
    if 'id="AI_OVERVIEW_TARGET_ANSWER"' not in content and "yomi-lede" in content:
        content = _add_id_to_first_section_with_class(
            content,
            css_class="yomi-lede",
            section_id="AI_OVERVIEW_TARGET_ANSWER",
            extra_attrs=' data-yomi-engine="aeo-sge"',
        )
    if 'id="INTENT_ANSWER_BLOCK"' not in content and "yomi-faq" in content:
        content = _add_id_to_first_section_with_class(
            content,
            css_class="yomi-faq",
            section_id="INTENT_ANSWER_BLOCK",
            extra_attrs=' data-yomi-engine="aeo"',
        )
    return content


def _add_id_to_first_section_with_class(
    html: str,
    *,
    css_class: str,
    section_id: str,
    extra_attrs: str = "",
) -> str:
    pattern = re.compile(
        rf"<section\b(?P<attrs>[^>]*)\bclass=(?P<quote>[\"'])(?P<classes>[^\"']*\b{re.escape(css_class)}\b[^\"']*)(?P=quote)(?P<tail>[^>]*)>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def _replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\bid=", tag, flags=re.IGNORECASE):
            return tag
        return tag[:-1].rstrip() + f' id="{section_id}"{extra_attrs}>'

    return pattern.sub(_replace, html, count=1)


def _wrap_answer_engine_support(block: str) -> str:
    # 기계적 래퍼 라벨("검색용 빠른 정리") 제거 — 내부 블록들이 각자 자연스러운
    # 헤딩을 갖고 있으므로 별도 SEO 흔적 라벨을 노출하지 않는다.
    return (
        '<section class="yomi-engine-support" data-yomi-block="answer-engine-support">'
        f"{block}"
        "</section>"
    )


def _insert_json_ld(html: str, payload: dict[str, Any]) -> str:
    script = (
        '<script type="application/ld+json">'
        f"{json.dumps(payload, ensure_ascii=False)}"
        "</script>"
    )
    if re.search(r"</head>", html, flags=re.IGNORECASE):
        return re.sub(r"</head>", f"{script}\n</head>", html, count=1, flags=re.IGNORECASE)
    return f"{script}\n{html}"


def _has_faq_section(html: str) -> bool:
    return bool(re.search(r'<section\b[^>]*class=["\'][^"\']*faq', html or "", flags=re.IGNORECASE))


def _has_author_answer_sections(html: str) -> bool:
    content = html or ""
    markers = (
        "hero-summary-box",
        "core-message-box",
        "key-fact-cards",
        "quick-decision-table",
        "action-guide-box",
        "yomi-judgment-box",
        "yomi-lede",
        "yomi-risk",
        "yomi-list",
    )
    return sum(1 for marker in markers if marker in content) >= 2


def _content_scope_html(html: str) -> str:
    content = html or ""
    match = re.search(
        r'<div\b[^>]*class=["\'][^"\']*post-content[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div\b[^>]*class=["\'][^"\']*tag-list|<p\b[^>]*class=["\'][^"\']*source-note)',
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    scoped = match.group(1) if match else content
    scoped = re.sub(
        r'<div\b[^>]*class=["\'][^"\']*post-meta[^"\']*["\'][^>]*>.*?</div>',
        " ",
        scoped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    scoped = re.sub(r"<h1\b[^>]*>.*?</h1>", " ", scoped, flags=re.IGNORECASE | re.DOTALL)
    return scoped


def _extract_faq_pairs(html: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for match in re.finditer(
        r"<h3\b[^>]*>(.*?)</h3>\s*<p\b[^>]*>(.*?)</p>",
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        q = _plain_text(match.group(1)).strip(" Q.:-")
        a = _plain_text(match.group(2))
        if q and a and len(a) >= 10:
            pairs.append({"Q": q, "A": a})
        if len(pairs) >= 5:
            break
    return pairs


def _plain_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


def _sentences(text: str, *, max_items: int = 4) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    pattern = re.compile(r".+?(?:다\.|요\.|니다\.|습니다\.|[.!?。])")
    sentences: list[str] = []
    for match in pattern.finditer(cleaned):
        sentence = match.group(0).strip()
        if len(sentence) >= 20 and sentence not in sentences:
            sentences.append(sentence)
        if len(sentences) >= max_items:
            break
    if not sentences and cleaned:
        sentences.append(cleaned[:180].rstrip(" ,."))
    return sentences[:max_items]


def _first_sentence(text: str, *, max_len: int) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    for match in re.finditer(r"(?:다\.|요\.|니다\.|습니다\.|[.!?。])", text):
        end = match.end()
        if 20 <= end <= max_len:
            return text[:end]
    return text[:max_len].rstrip(" ,.")
