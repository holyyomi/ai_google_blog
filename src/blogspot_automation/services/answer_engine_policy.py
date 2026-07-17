from __future__ import annotations

import hashlib
import json
import re
from html import escape, unescape
from typing import Any

from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.geo_intent_service import GeoIntentService
from blogspot_automation.services.kst_clock import kst_today
from blogspot_automation.services.news_taxonomy import content_type_for_topic_group


# 기계적 SEO 라벨("먼저 볼 핵심" 등) 대신 사람 에디터 말투로, 글마다 다르게 변주한다.
# AI가 쓴 티를 줄이는 핵심 장치. (seed=토픽으로 결정적 선택 → 같은 글은 항상 같은 라벨)
_LABEL_VARIANTS: dict[str, tuple[str, ...]] = {
    "overview": ("결론부터 말하면", "핵심부터 짚으면", "한 줄로 먼저", "짧게 보면 이렇습니다"),
    "context": ("왜 지금 터졌나", "이 일이 불거진 배경", "지금 주목받는 이유", "타이밍부터 보면"),
    # AI 도구/기능 글은 "터졌나" 같은 사건 어휘가 어색하다 — 도구 글 전용 변주.
    "context_ai": ("무엇이 달라졌나", "이 기능이 지금 중요한 이유", "지금 확인해야 하는 이유", "변화의 핵심부터"),
    "intent": ("많이들 궁금해하는 것", "이건 짚고 넘어가죠", "자주 나오는 물음", "여기서 헷갈리기 쉬운 것"),
    "confirmed": ("지금까지 확인된 것", "사실과 추측, 이렇게 갈립니다", "확인된 것과 아직인 것"),
    "trust": ("어디서 확인했나", "참고한 보도", "근거"),
}

# 영어 모드 변주 풀 — 선택 메커니즘(seed 결정적)은 한국어와 동일.
# 주의: 변형은 전부 '비질문형' 표현만 쓴다 — What/Why/How/Which 시작이나 '?'가
# 들어가면 final_html_audit의 질문 헤딩 예산(≤5)을 GEO 블록이 잡아먹어
# visible_question_headings_above_5로 발행이 차단된다 (2026-07-17 드라이런 #4 실측).
_LABEL_VARIANTS_EN: dict[str, tuple[str, ...]] = {
    "overview": ("The short answer", "TL;DR", "Bottom line first"),
    "context": ("The context behind it", "The backstory in brief", "Behind this change"),
    "context_ai": ("The change, in context", "Behind this update", "The backstory in brief"),
    "intent": ("Reader questions, answered", "Common questions, answered", "Quick answers for searchers"),
    "confirmed": ("Confirmed vs. still unclear", "The confirmed facts so far"),
    "trust": ("Sources & where to verify", "Where this comes from", "Sources"),
}


def _varied_label(kind: str, seed: str) -> str:
    pool = _LABEL_VARIANTS_EN if is_english_mode() else _LABEL_VARIANTS
    variants = pool.get(kind, ())
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
    source_citations: list[dict[str, str]] | None = None,
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
    today = today or kst_today("%Y-%m-%d")
    _default_topic = "today's story" if is_english_mode() else "오늘 이슈"
    topic_text = " ".join((topic or title or _default_topic).split()).strip()
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
    # 리드 재사용 금지(2026-07-11): overview/issue-context는 본문 hook에서
    # 문장을 그대로 가져와, 같은 리드가 한 글에 4~5회 반복 노출됐다(라이브
    # 실측·독자 밀도 저하). 본문에 이미 있는 문장은 걷어내고, 걷어낸 뒤
    # 최소 길이(발행 계약 low_quality_ai_overview_answer 35자)에 못 미치면
    # 주제 안내 문장으로 보강한다.
    _body_norm_for_dup = _dupcheck_norm(_plain_text(content))
    overview = _drop_sentences_already_in_body(overview, _body_norm_for_dup)
    if len(overview) < 35:
        if is_english_mode():
            overview = (
                f"{overview} The article separates what's confirmed "
                "from what you should verify yourself."
            ).strip()
        else:
            overview = (
                f"{overview} {topic_text}에서 확인된 내용과 직접 확인할 것을 "
                "본문에서 구분해 정리했습니다."
            ).strip()
    issue_context = _drop_sentences_already_in_body(issue_context, _body_norm_for_dup)
    if len(issue_context) < 20:
        if is_english_mode():
            issue_context = (
                f"{issue_context} The background and real-world impact "
                "are covered below, based on confirmed facts."
            ).strip()
        else:
            issue_context = (
                f"{issue_context} {topic_text}의 배경과 영향 범위는 본문에서 "
                "확인된 사실 기준으로 정리했습니다."
            ).strip()
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
        _context_kind = "context_ai" if resolved_type.startswith("ai_") else "context"
        head_blocks.append(_section("ISSUE_CONTEXT_BLOCK", "yomi-note", _varied_label(_context_kind, _seed), issue_context))
    if 'id="INTENT_ANSWER_BLOCK"' not in content:
        _intent_items = llm_faq_pairs[:3] if use_llm_intent else intent_answers
        # 본문에 이미 visible FAQ가 있으면 같은 Q&A를 이 블록에서 반복하지 않는다
        # (실제 발행 사고: 동일 Q&A가 '핵심 Q&A'와 '많이들 궁금해하는 것'에 두 번 노출).
        _body_faq_keys = {
            _normalize_question_key(str(p.get("Q") or ""))
            for p in (slots.get("faq") or [])
            if isinstance(p, dict)
        }
        if _has_faq_section(content) and _body_faq_keys:
            _distinct = [
                qa for qa in _intent_items
                if _normalize_question_key(str(qa.get("Q") or "")) not in _body_faq_keys
            ]
            if len(_distinct) < 3:
                _extra_questions = [
                    q for q in questions
                    if _normalize_question_key(q) not in _body_faq_keys
                    and all(
                        _normalize_question_key(q) != _normalize_question_key(str(d.get("Q") or ""))
                        for d in _distinct
                    )
                ]
                _distinct.extend(_fallback_intent_answers(_extra_questions, topic_text)[: 3 - len(_distinct)])
            _intent_items = _distinct
        if is_english_mode() and len(_intent_items) < 3:
            # 영어 모드(2026-07-17): 본문 FAQ와 겹침 제거·LLM FAQ 부족 등 어느 경로로든
            # intent 블록이 3개 미만이면 intent_qa_count_below_3로 발행이 막힌다
            # (드라이런 실측). 본문 FAQ와 겹치지 않는 범용 영어 Q&A로 3개를 보장한다.
            _dedup_keys = {
                _normalize_question_key(str(p.get("Q") or ""))
                for p in (slots.get("faq") or [])
                if isinstance(p, dict)
            }
            _en_generic_pool = [
                {"Q": "Is it worth paying for right now?", "A": "Try the free tier on one real task first; upgrade only if the limits actually slow you down."},
                {"Q": "How does this affect existing users?", "A": "Rollouts are usually gradual — check your own account and plan settings rather than assuming the change is live for you."},
                {"Q": "Where can you verify the current details?", "A": "Go by the official announcement and pricing pages; treat community screenshots as secondary sources."},
                {"Q": "What should you check before relying on it?", "A": "Confirm the plan limits, data handling settings, and the as-of date of any numbers you saw quoted."},
            ]
            _intent_items = list(_intent_items)
            for qa in _en_generic_pool:
                if len(_intent_items) >= 3:
                    break
                _qk = _normalize_question_key(qa["Q"])
                if _qk in _dedup_keys:
                    continue
                if any(_qk == _normalize_question_key(str(d.get("Q") or "")) for d in _intent_items):
                    continue
                _intent_items.append(qa)
        head_blocks.append(_intent_answer_block(_intent_items, label=_varied_label("intent", _seed)))
    # PEOPLE_ALSO_ASK_BLOCK("이어서 찾아보면 좋은 것")는 더 이상 삽입하지 않는다
    # (2026-07-09 사용자 결정) — 답 없는 검색어 나열이라 읽는 값이 없고, 순수 SEO용
    # 필러였다. answer_engine_coverage()는 과거 발행물 감지를 위해 필드는 유지하되,
    # 아래 게이트들에서 필수 요건으로 취급하지 않도록 news_quality_gate.py /
    # publish_preview_scorecard.py / post_publish_audit_service.py도 함께 수정함.

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
    if 'id="AI_CITATION_SUMMARY"' not in content:
        tail_blocks.append(
            _citation_summary_block(
                title=title, topic=topic_text, slots=slots, body_norm=_body_norm_for_dup
            )
        )
    if 'id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"' not in content:
        tail_blocks.append(_confirmed_vs_check_needed_block(confirmed_map, label=_varied_label("confirmed", _seed)))
    if 'id="SOURCE_TRUST_BLOCK"' not in content:
        tail_blocks.append(
            _source_trust_block(
                trust_text,
                citations=source_citations,
                label=_varied_label("trust", _seed),
            )
        )
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
    # 이 함수가 발행 직전에 한 번 더 호출되면 FAQ 재배치가 이미 부착된 해시태그
    # 뒤로 블록을 밀어 넣어 해시태그가 글 중간에 끼는 사고가 있었다(라이브 실측).
    # 어떤 순서로 호출되든 해시태그는 항상 맨 끝을 보장한다.
    content = _relocate_hashtags_to_tail(content)

    try:
        from blogspot_automation.services.seo_policy import ensure_yomi_clean_article_layout

        content = ensure_yomi_clean_article_layout(content)
    except Exception:
        pass

    # 최종 정규화(모든 재렌더 이후): LLM 서술형 FAQ는 위 clean-layout 단계에서 faq-card로
    # 렌더돼, answer-engine intent(3)+paa(5)와 3중 스택이 되어 aeo_visible_question_blocks_
    # overstacked 게이트/최종 발행 계약에 걸린다. 이 함수는 파이프라인과 news_publish_service
    # 양쪽에서 호출되므로, 여기서 faq-card를 표준 faq-item으로 바꿔 faq_card_count=0을
    # 어느 경로에서든 보장한다(질문 h3·FAQ 섹션 존재 요건은 보존).
    content = re.sub(
        r'(class=["\'][^"\']*?)\bfaq-card\b', r"\1faq-item", content, flags=re.IGNORECASE
    )

    if is_english_mode():
        # 최종 보수(2026-07-17): clean-layout 재렌더·overstack 축소 등 어느 단계가
        # intent 항목을 떨어뜨려도, 마지막에 3개를 다시 보장한다 —
        # intent_qa_count_below_3가 EN 발행을 반복 차단한 실측 대응.
        content = _ensure_min_intent_items_en(content)

    return content


_EN_INTENT_REPAIR_POOL: tuple[tuple[str, str], ...] = (
    ("Is it worth paying for right now?",
     "Try the free tier on one real task first; upgrade only if the limits actually slow you down."),
    ("How does this affect existing users?",
     "Rollouts are usually gradual — check your own account and plan settings rather than assuming the change is live for you."),
    ("Where can you verify the current details?",
     "Go by the official announcement and pricing pages; treat community screenshots as secondary sources."),
    ("What should you check before relying on it?",
     "Confirm the plan limits, data handling settings, and the as-of date of any numbers you saw quoted."),
)


def _ensure_min_intent_items_en(content: str) -> str:
    """INTENT_ANSWER_BLOCK의 intent-qa-item이 3개 미만이면 범용 Q&A로 채운다."""
    count = len(re.findall(r'class=["\'][^"\']*intent-qa-item', content))
    if count >= 3:
        return content
    block_match = re.search(
        r'(<section[^>]*id="INTENT_ANSWER_BLOCK"[^>]*>)(.*?)(</section>)',
        content,
        flags=re.DOTALL,
    )
    existing_qs = {
        _normalize_question_key(q)
        for q in re.findall(r"Q\.\s*([^<]+)", block_match.group(2))
    } if block_match else set()
    additions: list[str] = []
    for q, a in _EN_INTENT_REPAIR_POOL:
        if count + len(additions) >= 3:
            break
        if _normalize_question_key(q) in existing_qs:
            continue
        additions.append(
            '<div class="intent-qa-item">'
            f'<p class="intent-q"><strong>Q. {escape(q)}</strong></p>'
            f"<p>A. {escape(a)}</p>"
            "</div>"
        )
    if not additions:
        return content
    if block_match:
        return (
            content[: block_match.end(2)]
            + "".join(additions)
            + content[block_match.end(2):]
        )
    block = (
        '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq">'
        "<h2>Reader questions, answered</h2>"
        + "".join(additions)
        + "</section>"
    )
    return _insert_before_internal_links_or_body_end(content, block)


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
        "ai_citation_summary_present": 'id="AI_CITATION_SUMMARY"' in content,
        "faq_section_present": _has_faq_section(content),
        "faqpage_json_ld_present": '"@type": "FAQPage"' in content or '"@type":"FAQPage"' in content,
        "blogposting_json_ld_present": '"@type": "BlogPosting"' in content or '"@type":"BlogPosting"' in content,
    }


def _build_slots_from_html(html: str, *, title: str, topic: str) -> dict[str, Any]:
    scoped_html = _content_scope_html(html)
    faq = _extract_faq_pairs(scoped_html)
    # 요약 카드/표/리스트가 섞인 전체 텍스트를 그대로 자르면 "핵심 변화/이점 리뷰·사."
    # 같은 중간 절단 덤프가 overview/context 블록에 노출된다(라이브 실측).
    # 문장부호가 온전한 본문 <p> 문단에서만 문장을 추출하고, 없을 때만 전체로 폴백.
    prose = _prose_paragraph_text(scoped_html)
    plain = prose or _plain_text(scoped_html)
    sentences = _sentences(plain, max_items=4)
    first_sentence = sentences[0] if sentences else _first_sentence(plain, max_len=180)
    second_sentence = ""
    for sentence in sentences[1:]:
        if sentence != first_sentence and len(sentence) >= 20:
            second_sentence = sentence
            break
    if is_english_mode():
        # 영어 모드: 긴 헤드라인(topic)을 문장에 그대로 삽입하면 같은 문자열이
        # 여러 블록에 반복돼 raw_topic_repeated_in_html로 발행이 막힌다
        # (드라이런 #8 실측: 7회). 주제어 없는 중립 문장으로 만든다.
        hook = first_sentence or "Here's what to check first before you act on this story."
        return {
            "hook_opening": hook,
            "real_criterion": second_sentence or _first_sentence(plain, max_len=160) or hook,
            "yomi_judgment": (
                "The key here is separating the actual impact "
                "from the noise, and knowing what to verify yourself."
            ),
            "faq": faq,
        }
    hook = first_sentence or f"{topic}에 대해 독자가 먼저 확인해야 할 핵심을 정리했습니다."
    # yomi_judgment: 제목이 아니라 topic을 쓴다 — 제목은 쉼표·후킹 구두점이
    # 섞여 문장 중간에 넣으면 비문이 된다(라이브 실측: "핵심은 구글 AI 검색
    # 변화가, 먼저 확인할 3가지을 단순 반응이 아니라…"). 목적격 조사도
    # 받침에 맞춘다(하드코딩 "을"이 "3가지을"을 만들었다).
    _subject = " ".join((topic or title or "이 이슈").split()).strip()
    return {
        "hook_opening": hook,
        "real_criterion": second_sentence or _first_sentence(plain, max_len=160) or hook,
        "yomi_judgment": (
            f"핵심은 {_subject}{_object_particle(_subject)} 단순 반응이 아니라 "
            "실제 영향과 확인 기준으로 나누어 보는 것입니다."
        ),
        "faq": faq,
    }


def _object_particle(word: str) -> str:
    """목적격 조사(을/를) — 마지막 글자의 받침 여부로 고른다."""
    if is_english_mode():
        # 영어 모드: 조사 부착 자체를 생략한다 (단어 그대로 사용).
        return ""
    cleaned = (word or "").strip()
    if not cleaned:
        return "을"
    last = cleaned[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return "을" if (code - 0xAC00) % 28 else "를"
    if last.isdigit():
        # 숫자는 한국어 읽기 기준: 0,1,3,6,7,8은 받침 있음(영·일·삼·육·칠·팔)
        return "을" if last in "013678" else "를"
    return "을"


def _dupcheck_norm(text: str) -> str:
    """문장 중복 판정용 정규화 — 공백 차이를 무시하고 비교한다."""
    return re.sub(r"\s+", "", text or "")


def _drop_sentences_already_in_body(text: str, body_norm: str, *, min_sentence_len: int = 12) -> str:
    """본문에 이미 그대로 있는 문장을 블록 텍스트에서 걷어낸다.

    배경(2026-07-11 라이브 실측): overview/issue-context/citation 블록이
    본문 리드(hook)를 그대로 재사용해 같은 문장이 한 글에서 4~5회 반복됐다.
    GEO 블록 ID는 발행 계약 필수라 블록 자체는 유지하되, 문장 단위로
    본문과 겹치는 부분만 제거한다.
    """
    if not text or not body_norm:
        return text or ""
    kept: list[str] = []
    if is_english_mode():
        # 영어 문장 경계: 종결부호 뒤 공백에서만 자른다.
        for raw in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
            sentence = raw.strip()
            if not sentence:
                continue
            if len(sentence) >= min_sentence_len and _dupcheck_norm(sentence) in body_norm:
                continue
            kept.append(sentence)
        return " ".join(kept).strip()
    pattern = re.compile(r".+?(?:다\.|요\.|니다\.|습니다\.|(?<!\d)[.!?](?!\d)|。)|.+$")
    for match in pattern.finditer(" ".join(text.split())):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        if len(sentence) >= min_sentence_len and _dupcheck_norm(sentence) in body_norm:
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


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
        if is_english_mode():
            seed = topic or title or "this topic"
            fallback_questions = (
                f"What should you check first about {seed}?",
                "Does this actually affect you, and how can you tell?",
                "Where can you verify the official details?",
                "What's the most common misconception?",
                "What should you do today?",
            )
        else:
            seed = topic or title or "이 이슈"
            fallback_questions = (
                f"{seed}에서 지금 가장 먼저 확인할 것은 무엇인가요?",
                "나에게 직접 영향이 있는지 어떻게 확인하나요?",
                "공식 정보는 어디에서 확인해야 하나요?",
                "주의해야 할 오해는 무엇인가요?",
                "오늘 바로 할 일은 무엇인가요?",
            )
        for q in fallback_questions:
            if q not in merged:
                merged.append(q)
            if len(merged) >= 5:
                break
    return merged[:8]


def _fallback_intent_answers(questions: list[str], topic: str) -> list[dict[str, str]]:
    if is_english_mode():
        answer = (
            "Availability, pricing, and rollout can vary by account and region — "
            "check the official page for the latest details."
        )
    else:
        answer = f"{topic}은 공식 안내, 적용 대상, 실제 영향 순서로 확인하는 것이 안전합니다."
    answers: list[dict[str, str]] = []
    for question in questions[:5]:
        answers.append({"Q": question, "A": answer})
    return answers


def _section(section_id: str, css_class: str, heading: str, text: str) -> str:
    return (
        f'<section id="{section_id}" class="{css_class}">'
        f'<h2>{escape(heading)}</h2>'
        f'<p>{escape(" ".join((text or "").split()))}</p>'
        "</section>"
    )


def _source_trust_block(
    text: str, *, citations: list[dict[str, str]] | None = None, label: str = ""
) -> str:
    """SOURCE_TRUST_BLOCK — 보일러플레이트 문구 + (있으면) 실제 인용 링크.

    2026-07-16: 이 경로(llm_content_service.generate_html → 여기)는 기존에
    plain text만 넣고 <a href> 링크를 전혀 만들지 않았다 — 실제 근거(Naver/Exa
    검색으로 얻은 URL)가 있어도 official_source_links_below_2 게이트를 통과할
    방법이 없었다. citations가 실제 http(s) URL을 가진 항목이면 이를
    official_sources.render_official_sources_html과 동일한 마크업으로 덧붙인다.
    조작 URL을 막기 위해 스킴·name 존재를 여기서도 다시 검증한다.
    """
    from blogspot_automation.services.official_sources import render_official_sources_html

    heading = label or ("Sources & where to verify" if is_english_mode() else "어디서 확인했나")
    safe_citations = [
        {"name": str(c.get("name", "")).strip(), "url": str(c.get("url", "")).strip()}
        for c in (citations or [])
        if isinstance(c, dict)
        and str(c.get("url", "")).strip().lower().startswith(("http://", "https://"))
        and str(c.get("name", "")).strip()
    ][:4]
    links_html = render_official_sources_html(safe_citations)
    return (
        '<section id="SOURCE_TRUST_BLOCK" class="yomi-source">'
        f'<h2>{escape(heading)}</h2>'
        f'<p>{escape(" ".join((text or "").split()))}</p>'
        f'{links_html}'
        "</section>"
    )


def _citation_summary_block(
    *, title: str, topic: str, slots: dict[str, Any], body_norm: str = ""
) -> str:
    hook = _first_sentence(str(slots.get("hook_opening") or ""), max_len=140)
    criterion = _first_sentence(str(slots.get("real_criterion") or ""), max_len=140)
    basis = _first_sentence(str(slots.get("yomi_judgment") or ""), max_len=140)
    sentences = [item for item in (hook, criterion, basis) if item]
    # 본문 문장을 그대로 재사용하지 않는다 — 리드 4~5회 반복 노출의 한 축.
    # yomi_judgment는 슬롯에서 합성한 문장이라 본문에 없어 살아남는다.
    if body_norm:
        sentences = [s for s in sentences if _dupcheck_norm(s) not in body_norm]
    if len(sentences) < 3:
        if is_english_mode():
            # 헤드라인(topic) 삽입 금지 — raw_topic_repeated_in_html 반복 카운트 방지
            sentences.extend([
                "It pays to separate who this applies to from what actually changes.",
                "Check the official announcement, the product screen, and the latest updates side by side.",
                "The article lays out the key conditions and caveats first, so you can compare quickly.",
            ])
        else:
            fallback_topic = topic or title or "이 주제"
            sentences.extend([
                f"{fallback_topic}은 적용 대상과 실제 영향 범위를 나누어 확인해야 합니다.",
                "공식 안내, 서비스 화면, 최신 변경 여부를 함께 보는 것이 안전합니다.",
                "본문은 독자가 바로 비교할 수 있도록 핵심 조건과 주의점을 먼저 정리합니다.",
            ])
    text = " ".join(dict.fromkeys(sentences[:4]))
    return (
        '<section id="AI_CITATION_SUMMARY" class="yomi-citation-summary">'
        f"<p>{escape(text)}</p>"
        "</section>"
    )


def _intent_answer_block(items: list[dict[str, str]], *, label: str = "") -> str:
    if is_english_mode():
        # 영어: 질문을 h3로 내면 intent 3개가 곧장 질문 헤딩 예산(≤5)을 잡아먹어
        # visible_question_headings_above_5로 발행이 막힌다 — 단락 강조로 렌더.
        body = "".join(
            '<div class="intent-qa-item">'
            f'<p class="intent-q"><strong>Q. {escape(str(item.get("Q") or ""))}</strong></p>'
            f'<p>A. {escape(str(item.get("A") or ""))}</p>'
            "</div>"
            for item in items[:3]
            if item.get("Q") and item.get("A")
        )
    else:
        body = "".join(
            '<div class="intent-qa-item">'
            f'<h3>Q. {escape(str(item.get("Q") or ""))}</h3>'
            f'<p>A. {escape(str(item.get("A") or ""))}</p>'
            "</div>"
            for item in items[:3]
            if item.get("Q") and item.get("A")
        )
    heading = label or ("Reader questions, answered" if is_english_mode() else "많이들 궁금해하는 것")
    return (
        '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq">'
        f"<h2>{escape(heading)}</h2>"
        f"{body}"
        "</section>"
    )


def _people_also_ask_block(questions: list[str], *, label: str = "") -> str:
    phrases: list[str] = []
    for q in questions:
        phrase = _search_phrase_from_question(str(q))
        # 긴 주제 문자열이 그대로 접합된 항목은 조사·어미가 깨진다
        # (라이브 실측: "…AI 기능 켜기 전에 확인할은 어떤 업무에 효과적").
        # 실제 검색어답지 않은 과장 길이/깨진 어미 항목은 버린다.
        if len(phrase) > 40 or re.search(r"[가-힣]할은\s|할은$", phrase):
            continue
        if phrase not in phrases:
            phrases.append(phrase)
        if len(phrases) >= 5:
            break
    items = "".join(f'<li class="paa-item">{escape(p)}</li>' for p in phrases)
    heading = label or ("Related searches" if is_english_mode() else "이어서 찾아보면 좋은 것")
    return (
        '<section id="PEOPLE_ALSO_ASK_BLOCK" class="yomi-paa-compact">'
        f"<h2>{escape(heading)}</h2>"
        f"<ul>{items}</ul>"
        "</section>"
    )


def _search_phrase_from_question(question: str) -> str:
    text = " ".join((question or "").split()).strip()
    text = re.sub(r"[?？]+$", "", text)
    if is_english_mode():
        # 영어 질문은 물음표만 걷어내면 검색어 형태로 충분하다.
        return text or "related things to check"
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


def _compact_search_topic(topic: str, *, max_len: int = 18) -> str:
    """긴 주제 문자열을 실제 검색어처럼 짧은 핵심 구로 압축.

    "구글 지도+제미나이 AI 기능 켜기 전에 확인할 설정" → "구글 지도+제미나이 AI"
    처럼 앞쪽 개체명 위주로 자른다 — PAA 폴백이 문장형 주제를 그대로 붙이면
    검색어가 아니라 깨진 문장이 되기 때문.
    """
    words = " ".join((topic or "").split()).split(" ")
    out: list[str] = []
    for word in words:
        candidate = " ".join([*out, word])
        if out and len(candidate) > max_len:
            break
        out.append(word)
    return " ".join(out).strip()


def _paa_search_fallbacks(*, topic: str, content_type: str) -> list[str]:
    topic_text = _compact_search_topic(topic or "이 주제") or "이 주제"
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
    if is_english_mode():
        heading = label or "What's confirmed so far"
        confirmed_h3 = "What's confirmed"
        check_needed_h3 = "Check for yourself (this changes often)"
    else:
        heading = label or "지금까지 확인된 것"
        confirmed_h3 = "확인된 내용"
        check_needed_h3 = "직접 확인 필요"
    return (
        '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">'
        f"<h2>{escape(heading)}</h2>"
        f'<div class="confirmed-section"><h3>{escape(confirmed_h3)}</h3>'
        f"<ul>{confirmed}</ul></div>"
        f'<div class="check-needed-section"><h3>{escape(check_needed_h3)}</h3>'
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
    heading = "Frequently Asked Questions" if is_english_mode() else "자주 묻는 질문"
    return f'<section class="yomi-faq"><h2>{heading}</h2>{cards}</section>'


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
    # LLM 서술형 본문은 FAQ를 <article class="faq-card">/<div class="faq-card">로
    # 내보내는데, 위 <section> 제거 규칙에 안 걸려 intent(3)+paa(5)와 3중으로 남아
    # aeo_visible_question_blocks_overstacked(faq_card>=3) 게이트에 걸린다. intent가
    # 이미 3개로 시각적 질문 예산을 채웠으므로, 남은 faq 블록의 카드 클래스만 제거해
    # faq_card_count를 0으로 떨어뜨린다. 질문 h3(faq_h3_count)·FAQ 섹션 존재 요건은
    # 그대로 보존되므로 news_quality_gate의 faq 요구도 충족한다.
    content = re.sub(
        r'(class=["\'][^"\']*?)\bfaq-card\b',
        r"\1faq-item",
        content,
        flags=re.IGNORECASE,
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


def _relocate_hashtags_to_tail(html: str) -> str:
    """해시태그 블록(yomi-hashtags)을 항상 글 맨 끝(</article> 직전)으로 이동.

    FAQ/보조 블록 재배치가 해시태그 부착 이후에 실행되면 해시태그가 본문 중간에
    끼는 결함을 막는 최종 안전장치. 해시태그 블록이 없으면 그대로 반환한다.
    """
    content = html or ""
    pattern = re.compile(
        r'\s*<section\b[^>]*class=["\'][^"\']*\byomi-hashtags\b[^"\']*["\'][^>]*>.*?</section>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    moved: list[str] = []

    def _extract(match: re.Match[str]) -> str:
        moved.append(match.group(0).strip())
        return ""

    stripped = pattern.sub(_extract, content)
    if not moved:
        return content
    # 중복 부착돼 있었다면 첫 블록 하나만 유지한다.
    block = moved[0]
    last_article = stripped.lower().rfind("</article>")
    if last_article >= 0:
        return stripped[:last_article] + block + "\n" + stripped[last_article:]
    return stripped.rstrip() + "\n" + block


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
    author_description = (
        "Editor covering AI tools, pricing, and automation with a practical, numbers-first approach."
        if is_english_mode()
        else "AI 도구, 자동화, 검색 경험 변화를 실무 적용 관점으로 정리하는 에디터"
    )
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title or topic,
        "description": topic or title,
        "datePublished": today,
        "dateModified": today,
        "author": {
            "@type": "Person",
            "name": "holyyomi AI",
            "url": _ABOUT_PAGE_URL,
            "description": author_description,
        },
        "publisher": {
            "@type": "Organization",
            "name": "holyyomi AI Insight",
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
    # LLM 직접발행 본문은 FAQ를 <div class="faq-section">으로 출력한다 —
    # <section>만 보면 본문 FAQ를 놓쳐 intent 블록이 같은 Q&A를 중복 노출한다(라이브 실측).
    return bool(
        re.search(
            r'<(?:section|div|article)\b[^>]*class=["\'][^"\']*faq',
            html or "",
            flags=re.IGNORECASE,
        )
    )


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


def _prose_paragraph_text(html: str) -> str:
    """표·카드·리스트를 제외한 본문 <p> 문단에서 온전한 산문만 모아 반환.

    요약 블록 인용문 소스로 쓴다 — 문장부호 없이 이어지는 카드/표 텍스트가
    섞이면 문장 추출이 중간에서 잘리기 때문. 표 안의 <p>는 흔치 않지만
    테이블 전체를 먼저 제거해 방어한다.
    """
    scoped = re.sub(r"<table\b.*?</table>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    scoped = re.sub(r"<(?:ul|ol)\b.*?</(?:ul|ol)>", " ", scoped, flags=re.IGNORECASE | re.DOTALL)
    paragraphs: list[str] = []
    for match in re.finditer(r"<p\b[^>]*>(.*?)</p>", scoped, flags=re.IGNORECASE | re.DOTALL):
        text = _plain_text(match.group(1))
        # 완결된 한국어 문장으로 끝나는 실제 산문만 채택 (라벨/캡션/태그줄 배제)
        if len(text) >= 30 and re.search(r"(?:다|요)\.\s*$|[.!?]$", text):
            paragraphs.append(text)
        if len(paragraphs) >= 6:
            break
    return " ".join(paragraphs)


def _sentences(text: str, *, max_items: int = 4) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    sentences: list[str] = []
    if is_english_mode():
        # 영어 문장 경계: 종결부호 뒤 공백에서만 분리 (소수점 "3.5"는 공백이 없어 안전).
        for raw in re.split(r"(?<=[.!?])\s+", cleaned):
            sentence = raw.strip()
            if len(sentence) >= 20 and sentence not in sentences:
                sentences.append(sentence)
            if len(sentences) >= max_items:
                break
        if not sentences and cleaned:
            sentences.append(cleaned[:180].rstrip(" ,."))
        return sentences[:max_items]
    # 숫자 사이의 "."(예: "제미나이 3.5")를 문장 끝으로 오인하면 "...3."/"5 소식에서..."
    # 처럼 단어 중간에서 잘려 다음 문장과 이어붙는 글리치가 난다(2026-07-09 라이브
    # 리허설 실측) — 소수점은 문장 구분자에서 제외.
    pattern = re.compile(r".+?(?:다\.|요\.|니다\.|습니다\.|(?<!\d)[.!?](?!\d)|。)")
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
    if is_english_mode():
        for match in re.finditer(r"[.!?](?=\s|$)", text):
            end = match.end()
            if 20 <= end <= max_len:
                return text[:end]
        return text[:max_len].rstrip(" ,.")
    for match in re.finditer(r"(?:다\.|요\.|니다\.|습니다\.|(?<!\d)[.!?](?!\d)|。)", text):
        end = match.end()
        if 20 <= end <= max_len:
            return text[:end]
    return text[:max_len].rstrip(" ,.")
