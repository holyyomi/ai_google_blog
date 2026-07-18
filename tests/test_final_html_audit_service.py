from __future__ import annotations

from blogspot_automation.services.final_html_audit_service import audit_final_html_quality


def test_audit_blocks_repeated_broken_intent_answers() -> None:
    repeated = "으로 단정하면 안 됩니다. 현재 공개된 공식 정보와 후속 확인이 필요한 내용을 나눠 봐야 합니다."
    html = f"""
    <article>
      <section id="AI_OVERVIEW_TARGET_ANSWER"><p>오늘 이슈는 확인된 사실과 아직 단정하기 어려운 쟁점을 분리해서 봐야 합니다.</p></section>
      <section id="INTENT_ANSWER_BLOCK">
        <div class="intent-qa-item"><h3>질문 1</h3><p>{repeated}</p></div>
        <div class="intent-qa-item"><h3>질문 2</h3><p>{repeated}</p></div>
        <div class="intent-qa-item"><h3>질문 3</h3><p>{repeated}</p></div>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    assert not result["passed"]
    assert any(str(issue).startswith("low_quality_faq_or_intent_answer") for issue in result["issues"])
    assert any(str(issue).startswith("repeated_faq_or_intent_answers") for issue in result["issues"])


def test_audit_blocks_delivery_issue_with_irrelevant_consumer_paa() -> None:
    html = """
    <article>
      <section id="PEOPLE_ALSO_ASK_BLOCK">
        <ul>
          <li class="paa-item">선거일 택배 집화 마감 시간</li>
          <li class="paa-item">택배 휴무 배송조회 멈춤 이유</li>
          <li class="paa-item">새벽배송 선거일 운영 여부</li>
          <li class="paa-item">환불 거부 대응 방법</li>
          <li class="paa-item">개인정보 유출 대응</li>
        </ul>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="선거일 CJ 택배 배송 일정", content_type="consumer_warning")

    assert "delivery_issue_contains_irrelevant_consumer_paa" in result["issues"]


def test_audit_blocks_legacy_visual_layout_markers() -> None:
    html = """
    <article class="golden-preview">
      <section id="AI_OVERVIEW_TARGET_ANSWER" class="ai-overview-box"><p>오늘 이슈는 확인된 사실과 직접 확인할 내용을 나눠 봐야 합니다.</p></section>
      <section id="PEOPLE_ALSO_ASK_BLOCK" class="paa-block">
        <ul><li class="paa-item">무엇을 먼저 확인하나요?</li></ul>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    assert not result["passed"]
    assert any(str(issue).startswith("legacy_visual_layout_markers_present") for issue in result["issues"])


def test_audit_blocks_visible_broken_title_integrity() -> None:
    html = """
    <article>
      <h1>재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지</h1>
      <h2>신청전 많이 묻는 질문</h2>
    </article>
    """

    result = audit_final_html_quality(html, content_type="viral_issue_decode", topic_group="ott_platform")

    assert not result["passed"]
    assert "visible_title_integrity:source_series_name_leaked:재계는 지금" in result["issues"]
    assert "visible_title_integrity:malformed_reaction_phrase" in result["issues"]
    assert "visible_title_integrity:policy_faq_heading_leak" in result["issues"]


def test_audit_warns_when_aeo_question_blocks_are_overstacked() -> None:
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>핵심 답변입니다. 이 문장은 충분히 길고 구체적인 판단 기준을 제공합니다.</p></section>
      <div class="yomi-thesis"><div><b>확인</b>내용</div><div><b>주의</b>내용</div></div>
      <ul class="yomi-list"><li data-step="1">확인할 내용을 정리합니다.</li></ul>
      <section id="INTENT_ANSWER_BLOCK">
        <article class="intent-qa-item"><h3>무엇을 먼저 보나요?</h3><p>공식 발표와 적용 대상을 먼저 나눠 봅니다.</p></article>
        <article class="intent-qa-item"><h3>왜 관심이 커졌나요?</h3><p>시장 기대와 실제 발표가 함께 움직이기 때문입니다.</p></article>
        <article class="intent-qa-item"><h3>어떻게 확인하나요?</h3><p>후속 공지와 공시를 기준으로 확인합니다.</p></article>
      </section>
      <section id="PEOPLE_ALSO_ASK_BLOCK">
        <ul>
          <li class="paa-item">관련 주가 반응은 왜 움직이나요?</li>
          <li class="paa-item">공식 발표는 어디서 보나요?</li>
          <li class="paa-item">국내 기업 영향은 무엇인가요?</li>
          <li class="paa-item">후속 일정은 어떻게 확인하나요?</li>
          <li class="paa-item">투자자는 무엇을 조심하나요?</li>
        </ul>
      </section>
      <section class="faq faq-block">
        <div class="faq-card"><h3>계약을 뜻하나요?</h3><p>아닙니다. 공식 발표가 필요합니다.</p></div>
        <div class="faq-card"><h3>기업 영향은 무엇인가요?</h3><p>공급망 연결 여부를 봐야 합니다.</p></div>
        <div class="faq-card"><h3>저장할 만한가요?</h3><p>후속 발표를 추적할 기준이 됩니다.</p></div>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    # 2026-07-18: INTENT_ANSWER_BLOCK의 질문은 합성 AEO Q&A라 가시 질문 헤딩
    # 예산(visible_question_headings_above_5) 집계에서 제외한다 — 본문 자체
    # 질문(0개)만 세면 여기서는 애초에 초과가 없다. 이 테스트의 핵심 회귀는
    # overstacked(중복 AEO 블록 과다) 탐지이므로 그 검사만 남긴다.
    assert "visible_question_headings_above_5" not in " ".join(result["issues"])
    assert "aeo_visible_question_blocks_overstacked:intent,paa,faq" in result["issues"]


def test_audit_blocks_stale_question_section_labels() -> None:
    html = """
    <article class="yomi-clean-post">
      <h1>무료배송인데 결제금액이 커질 때 확인할 것</h1>
      <section id="PEOPLE_ALSO_ASK_BLOCK"><h2>관련 검색 질문</h2><ul><li class="paa-item">최소주문금액 비교</li></ul></section>
    </article>
    """

    result = audit_final_html_quality(html)

    assert "stale_question_section_labels:관련 검색 질문" in result["issues"]


def test_audit_blocks_question_like_paa_items() -> None:
    html = """
    <article class="yomi-clean-post">
      <h1>무료배송인데 결제금액이 커질 때 확인할 것</h1>
      <section id="PEOPLE_ALSO_ASK_BLOCK"><h2>관련 검색어</h2><ul><li class="paa-item">쿠폰을 쓰면 항상 더 저렴한가요</li></ul></section>
    </article>
    """

    result = audit_final_html_quality(html)

    assert "question_like_paa_items:1" in result["issues"]


def test_audit_allows_delivery_specific_answers() -> None:
    html = """
    <article class="yomi-clean-post">
      <section id="AI_OVERVIEW_TARGET_ANSWER" class="yomi-lede"><p>선거일 택배 일정은 송장 발급보다 실제 집화 단계와 택배사 운영 공지를 나눠 봐야 합니다.</p></section>
      <div class="yomi-thesis"><div><b>배송 전</b>집화 여부를 먼저 봅니다.</div><div><b>배송 후</b>반품 회수 일정을 같이 봅니다.</div></div>
      <ul class="yomi-list"><li data-step="1">배송조회 마지막 상태를 확인합니다.</li></ul>
      <section id="INTENT_ANSWER_BLOCK">
        <div class="intent-qa-item"><h3>택배가 쉬는 날은 언제인가요?</h3><p>일반 택배는 선거일 집화와 배송이 멈출 수 있으므로 실제 집화 단계와 택배사 공지를 확인해야 합니다.</p></div>
        <div class="intent-qa-item"><h3>새벽배송은 운영되나요?</h3><p>새벽배송과 당일배송은 일반 택배와 운영망이 다를 수 있어 앱 공지와 지역별 안내를 따로 봐야 합니다.</p></div>
        <div class="intent-qa-item"><h3>배송조회가 멈췄나요?</h3><p>송장 발급, 집화, 간선 이동, 배송 출발 중 어디에 멈춰 있는지 확인해야 지연 폭을 판단할 수 있습니다.</p></div>
      </section>
      <section id="PEOPLE_ALSO_ASK_BLOCK">
        <ul>
          <li class="paa-item">선거일 택배 집화 마감 시간</li>
          <li class="paa-item">택배 휴무 배송조회 멈춤 이유</li>
          <li class="paa-item">새벽배송 선거일 운영 여부</li>
          <li class="paa-item">반품 회수 선거일 지연 대응</li>
          <li class="paa-item">택배사별 휴무 공지 확인</li>
        </ul>
      </section>
      <section id="SOURCE_TRUST_BLOCK" class="yomi-source">
        <a href="https://www.kca.go.kr">한국소비자원</a>
        <a href="https://www.ftc.go.kr">공정거래위원회</a>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="선거일 CJ 택배 배송 일정", content_type="consumer_warning")

    assert result["passed"], result


def test_audit_blocks_clean_layout_without_reference_modules() -> None:
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>이번 이슈는 확인 기준을 먼저 봐야 합니다. 단순 소식보다 실제 영향이 중요합니다.</p></section>
      <section><h2>무슨 일이 있었나</h2><p>관련 보도에 따르면 변화가 있었습니다.</p></section>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    assert not result["passed"]
    assert "yomi_clean_layout_lacks_adaptive_modules:0" in result["issues"]


def test_audit_blocks_inline_styles_inside_clean_layout() -> None:
    html = """
    <style>.yomi-clean-post{font-size:16px}</style>
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>이번 이슈는 확인 기준을 먼저 봐야 합니다. 단순 소식보다 실제 영향이 중요합니다.</p></section>
      <div class="yomi-thesis"><div style="color:red"><b>확정</b>확인된 내용입니다.</div><div><b>미확정</b>추가 확인이 필요합니다.</div></div>
      <ul class="yomi-list"><li data-step="1">공식 공지를 확인합니다.</li></ul>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    assert not result["passed"]
    assert "inline_styles_present_in_clean_layout:1" in result["issues"]


def test_audit_reads_article_intent_answers_in_clean_faq() -> None:
    repeated = "확인된 사실과 직접 확인할 내용을 나눠서 보고, 공식 안내가 바뀌는지 마지막으로 확인해야 합니다."
    html = f"""
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>이번 이슈는 확인 기준을 먼저 봐야 합니다. 단순 소식보다 실제 영향이 중요합니다.</p></section>
      <div class="yomi-thesis"><div><b>확정</b>확인된 내용입니다.</div><div><b>미확정</b>추가 확인이 필요합니다.</div></div>
      <ul class="yomi-list"><li data-step="1">공식 공지를 확인합니다.</li></ul>
      <section id="INTENT_ANSWER_BLOCK" class="yomi-faq">
        <article class="intent-qa-item"><h3>질문 1</h3><p>{repeated}</p></article>
        <article class="intent-qa-item"><h3>질문 2</h3><p>{repeated}</p></article>
        <article class="intent-qa-item"><h3>질문 3</h3><p>{repeated}</p></article>
      </section>
    </article>
    """

    result = audit_final_html_quality(html, topic="오늘 이슈", content_type="today_issue_explainer")

    assert not result["passed"]
    assert "repeated_faq_or_intent_answers:3" in result["issues"]


def test_audit_blocks_visible_internal_labels_and_body_hashtags() -> None:
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>공식 공고의 대상과 금액을 먼저 확인해야 합니다.</p></section>
      <section class="preview-hook"><p class="section-label">도입</p><p>본문입니다.</p></section>
      <section class="hashtag-box"><p class="section-label">해시태그</p><p>#지원금 #신청기간</p></section>
      <div class="yomi-thesis"><div><b>대상</b>공고 확인</div><div><b>금액</b>공고 확인</div></div>
      <ul class="yomi-list"><li data-step="1">공고를 확인합니다.</li></ul>
    </article>
    """

    result = audit_final_html_quality(
        html,
        topic="지원금 공고",
        content_type="policy_deadline",
        topic_group="policy_benefit",
    )

    assert "visible_internal_section_labels:도입,해시태그" in result["issues"]
    assert "uncontrolled_visible_body_hashtags:2" in result["issues"]


def test_audit_ignores_url_fragment_hashtags() -> None:
    """실사례(2026-07-10): chrome://flags/#search-ai-overviews 같은 URL 프래그먼트가
    uncontrolled_visible_body_hashtags 오탐으로 발행을 차단했다. 실제 관리형 해시태그
    섹션과 개수가 맞으면 URL '#'은 무시하고 통과해야 한다."""
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>크롬 주소창에서 chrome://flags/#search-ai-overviews 켜짐을 확인합니다.</p></section>
      <div class="yomi-thesis"><div><b>핵심</b>설정 확인</div></div>
      <ul class="yomi-list"><li data-step="1">설정을 확인합니다.</li></ul>
      <section class="yomi-hashtags" data-yomi-block="hashtags"><p>#AI검색 #GEO</p></section>
    </article>
    """

    result = audit_final_html_quality(html, topic="AI 검색 설정", content_type="ai_search_change")

    assert "uncontrolled_visible_body_hashtags:2" not in "".join(result["issues"])


def test_audit_allows_controlled_hashtag_footer() -> None:
    html = """
    <article class="yomi-clean-post">
      <section class="yomi-lede"><p>환불 지연은 결제 기록과 접수 번호를 먼저 나눠 확인해야 합니다.</p></section>
      <div class="yomi-thesis"><div><b>증거</b>결제 내역을 남깁니다.</div><div><b>신고</b>공식 기관을 확인합니다.</div></div>
      <ul class="yomi-list"><li data-step="1">주문번호와 접수번호를 저장합니다.</li></ul>
      <section id="SOURCE_TRUST_BLOCK" class="yomi-source">
        <a href="https://www.kca.go.kr">한국소비자원</a>
        <a href="https://www.ftc.go.kr">공정거래위원회</a>
      </section>
      <section class="yomi-hashtags" data-yomi-block="hashtags"><p>#환불 #소비자피해 #생활정보</p></section>
    </article>
    """

    result = audit_final_html_quality(html, content_type="consumer_warning", topic_group="refund_consumer")

    assert result["passed"], result


def test_audit_blocks_empty_table_cells() -> None:
    html = """
    <article>
      <table><tbody><tr><td>환불 신청했는데 늦다</td><td></td></tr></tbody></table>
    </article>
    """

    result = audit_final_html_quality(html)

    assert "empty_table_cells:1" in result["issues"]


def test_stale_evidence_dates_warns_when_newest_citation_over_a_year_old() -> None:
    # 실사례(2026-07-11): 발행일 기준 14개월 전 조사("2025년 5월")가 글의
    # 유일한 연·월 근거였다. 비차단 경고로 관측한다.
    from blogspot_automation.services.final_html_audit_service import (
        _stale_evidence_warning,
    )
    from blogspot_automation.services.kst_clock import kst_today

    today_year = int(kst_today("%Y"))
    stale = _stale_evidence_warning(f"{today_year - 2}년 5월 기준 직장인 조사에서 확인됐다.")
    assert stale.startswith("stale_evidence_dates:")

    fresh = _stale_evidence_warning(
        f"{today_year}년 1월 발표에 따르면 달라졌다. {today_year - 2}년 5월 조사와 비교된다."
    )
    assert fresh == ""

    assert _stale_evidence_warning("날짜 인용이 없는 본문.") == ""
