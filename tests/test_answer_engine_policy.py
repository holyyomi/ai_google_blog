from __future__ import annotations

from blogspot_automation.services.answer_engine_policy import (
    _first_sentence,
    _sentences,
    answer_engine_coverage,
    ensure_answer_engine_optimized_html,
)


def test_sentences_does_not_split_on_decimal_point() -> None:
    # 2026-07-09 라이브 리허설 실측: "제미나이 3.5" 같은 소수점을 문장 끝으로 오인해
    # "...3."/"5 소식에서..."로 잘리면 다음 sentence로 이어져 단어 중간이 끊긴다.
    text = (
        "작업 중 코드 생성을 AI에 맡겼다가 되돌리는 경우가 많습니다. "
        "구글 제미나이 3.5 소식에서 지금 확인해야 할 것은 세 가지입니다."
    )
    sentences = _sentences(text, max_items=4)
    assert any(s.startswith("구글 제미나이 3.5") for s in sentences)
    assert not any(s.strip().endswith("3.") for s in sentences)


def test_first_sentence_does_not_split_on_decimal_point() -> None:
    text = "구글 제미나이 3.5 소식에서 지금 확인해야 할 것은 세 가지입니다."
    result = _first_sentence(text, max_len=100)
    assert result.endswith("세 가지입니다.")
    assert not result.endswith("3.")


def test_ensure_answer_engine_optimized_html_adds_required_blocks() -> None:
    html = """
    <html><head></head><body>
      <article>
        <h1>Samsung service change checklist</h1>
        <p>Readers need a quick answer, a source check, and the next action.</p>
      </article>
    </body></html>
    """

    result = ensure_answer_engine_optimized_html(
        html,
        title="Samsung service change checklist",
        topic="Samsung service change",
        content_type="platform_change",
        topic_group="platform_issue",
        reader_questions=[
            "What changed first?",
            "Who is affected?",
            "Where should readers verify it?",
            "What should readers do today?",
            "What should readers avoid?",
        ],
        today="2026-05-26",
    )
    coverage = answer_engine_coverage(result)

    assert coverage["ai_overview_target_answer_present"]
    assert coverage["issue_context_present"]
    assert coverage["intent_answer_present"]
    assert coverage["intent_qa_count"] >= 3
    # PEOPLE_ALSO_ASK_BLOCK("이어서 찾아보면 좋은 것")는 2026-07-09부터 생성하지 않는다
    # — 답 없는 검색어 나열이라 읽는 값이 없는 순수 SEO 필러로 판단해 제거.
    assert not coverage["people_also_ask_present"]
    assert coverage["confirmed_vs_check_needed_present"]
    assert coverage["source_trust_block_present"]
    assert coverage["ai_citation_summary_present"]
    assert coverage["faq_section_present"]
    assert coverage["faqpage_json_ld_present"]
    assert coverage["blogposting_json_ld_present"]
    assert 'class="yomi-lede"' in result
    # AI가 쓴 티 나는 기계적 라벨은 더 이상 노출되지 않아야 한다.
    assert "관련 검색어" not in result
    assert "검색용 빠른 정리" not in result
    assert "빠른 확인 답변" not in result
    assert "추가로 확인할 검색 질문" not in result
    assert 'class="ai-overview-box"' not in result
    assert 'class="paa-block"' not in result
    assert 'class="yomi-paa-compact"' not in result


def test_ensure_answer_engine_optimized_html_is_idempotent_for_blocks() -> None:
    html = "<html><body><h1>Consumer alert checklist</h1><p>Check the official notice first.</p></body></html>"

    once = ensure_answer_engine_optimized_html(
        html,
        title="Consumer alert checklist",
        topic="Consumer alert",
        content_type="consumer_warning",
        topic_group="refund_consumer",
    )
    twice = ensure_answer_engine_optimized_html(
        once,
        title="Consumer alert checklist",
        topic="Consumer alert",
        content_type="consumer_warning",
        topic_group="refund_consumer",
    )

    for marker in (
        'id="AI_OVERVIEW_TARGET_ANSWER"',
        'id="ISSUE_CONTEXT_BLOCK"',
        'id="INTENT_ANSWER_BLOCK"',
        'id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"',
        'id="SOURCE_TRUST_BLOCK"',
        'id="AI_CITATION_SUMMARY"',
    ):
        assert twice.count(marker) == 1
    assert twice.count('"@type": "FAQPage"') == 1
    assert twice.count('"@type": "BlogPosting"') == 1


def test_ensure_answer_engine_optimized_html_reuses_clean_lede_and_faq() -> None:
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>이번 이슈는 공식 안내와 실제 영향 범위를 나눠 봐야 합니다.</p></section>
      <div class="yomi-thesis"><div><b>확정</b>공식 안내입니다.</div><div><b>확인</b>내 계정 영향입니다.</div></div>
      <ul class="yomi-list"><li data-step="1">공지 화면을 확인합니다.</li></ul>
      <section class="yomi-faq">
        <article class="intent-qa-item"><h3>무엇을 먼저 보나요?</h3><p>공식 안내와 내 적용 여부를 먼저 확인합니다.</p></article>
      </section>
    </article>
    """

    result = ensure_answer_engine_optimized_html(
        html,
        title="서비스 변경 확인 기준",
        topic="서비스 변경",
        content_type="platform_change",
        topic_group="platform_issue",
    )

    assert result.count('class="yomi-lede"') == 1
    assert result.count('id="AI_OVERVIEW_TARGET_ANSWER"') == 1
    assert result.count('id="INTENT_ANSWER_BLOCK"') == 1
    assert result.count('<section class="yomi-engine-support"') <= 1


def test_visible_question_blocks_are_consolidated_to_intent_answers() -> None:
    html = """
    <article class="yomi-clean-post">
      <section id="INTENT_ANSWER_BLOCK" class="yomi-faq">
        <h2>빠른 확인 답변</h2>
        <div class="intent-qa-item"><h3>Q. 첫 질문인가요?</h3><p>A. 첫 답변입니다.</p></div>
        <div class="intent-qa-item"><h3>Q. 둘째 질문인가요?</h3><p>A. 둘째 답변입니다.</p></div>
        <div class="intent-qa-item"><h3>Q. 셋째 질문인가요?</h3><p>A. 셋째 답변입니다.</p></div>
        <div class="intent-qa-item"><h3>Q. 넷째 질문인가요?</h3><p>A. 넷째 답변입니다.</p></div>
        <div class="intent-qa-item"><h3>Q. 다섯째 질문인가요?</h3><p>A. 다섯째 답변입니다.</p></div>
      </section>
      <section id="PEOPLE_ALSO_ASK_BLOCK" class="yomi-paa-compact">
        <h2>관련 검색어</h2>
        <ul>
          <li class="paa-item">젠슨 황 방한은 왜 AI 반도체 이슈로 이어지나요?</li>
        </ul>
      </section>
      <section class="faq faq-block">
        <div class="faq-card"><h3>계약을 뜻하나요?</h3><p>공식 발표가 필요합니다.</p></div>
        <div class="faq-card"><h3>기업 영향은 무엇인가요?</h3><p>공급망 연결 여부를 봅니다.</p></div>
        <div class="faq-card"><h3>저장할 만한가요?</h3><p>후속 발표를 추적할 기준입니다.</p></div>
      </section>
    </article>
    """

    result = ensure_answer_engine_optimized_html(
        html,
        title="젠슨 황 방한 보도, AI 반도체 이슈에서 먼저 볼 3가지",
        topic="젠슨 황 방한 보도와 AI 반도체 이슈",
        content_type="today_issue_explainer",
        topic_group="today_issue",
    )

    assert result.count('class="intent-qa-item"') == 3
    assert "넷째 질문" not in result
    assert 'class="faq-card"' not in result
    assert "관련 검색어" in result
    assert "젠슨 황 방한은 왜 AI 반도체 이슈로 이어지나요?" not in result
    assert "젠슨 황 방한은 AI 반도체 이슈로 이어지" in result


def test_geo_blocks_do_not_repeat_body_lede_verbatim() -> None:
    # 실사례(2026-07-11): overview/issue-context/citation 블록이 본문 리드를
    # 그대로 재사용해 같은 문장이 한 글에서 4~5회 노출됐다. 블록 ID는
    # 유지하되 본문과 문장 단위 중복은 없어야 한다.
    import re
    from html import unescape

    from blogspot_automation.services.answer_engine_policy import (
        ensure_answer_engine_optimized_html,
    )

    lede = "구글 검색 결과 상단에 AI 개요가 자리 잡으면서 클릭 없이 답을 보는 방식이 일상이 됐다."
    body = f"""
    <article class="yomi-clean-post">
    <h1>구글 AI 검색 변화, 업무에 쓰기 전 확인할 것</h1>
    <p>{lede} 검토 없이 AI 요약을 복사해 쓰면 수정 시간이 길어진다.</p>
    <h2>업무 유형별 기준</h2>
    <p>번역과 자료 조사처럼 패턴이 정해진 작업은 초안 시간을 줄일 수 있다.</p>
    </article>
    """
    out = ensure_answer_engine_optimized_html(
        body,
        title="구글 AI 검색 변화, 업무에 쓰기 전 확인할 것",
        topic="구글 AI 검색 변화가 직장인 업무에 미치는 영향",
        content_type="ai_work_tip",
        topic_group="ai_work",
    )
    visible = unescape(re.sub(r"<script\b.*?</script>", " ", out, flags=re.S | re.I))
    visible = re.sub(r"<[^>]+>", " ", visible)
    compact = re.sub(r"\s+", "", visible)
    assert compact.count(re.sub(r"\s+", "", lede)) == 1
    for block_id in (
        "AI_OVERVIEW_TARGET_ANSWER",
        "ISSUE_CONTEXT_BLOCK",
        "INTENT_ANSWER_BLOCK",
        "SOURCE_TRUST_BLOCK",
    ):
        assert f'id="{block_id}"' in out


def test_yomi_judgment_uses_correct_object_particle() -> None:
    # 실사례: 하드코딩 "을"이 "3가지을" 비문을 만들었다.
    from blogspot_automation.services.answer_engine_policy import _object_particle

    assert _object_particle("영향") == "을"
    assert _object_particle("확인할 3가지") == "를"  # '지'는 받침 없음
    assert _object_particle("기준") == "을"
    assert _object_particle("GPT-5.6") == "을"  # 6=육, 받침 있음
