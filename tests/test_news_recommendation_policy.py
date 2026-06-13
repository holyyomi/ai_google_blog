from __future__ import annotations

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.news_quality_gate import NewsQualityGate
from blogspot_automation.services.news_recommendation_policy import evaluate_news_recommendation_policy


def _generic_driver_license_html() -> str:
    return """
    <html><body>
      <article>
        <h1>청년 운전면허 지원금 신청방법과 대상 조건, 신청 전 먼저 볼 3가지</h1>
        <section><h2>핵심 요약</h2><p>정부·지자체 지원금은 대상 조건과 신청 기간을 확인해야 합니다.</p></section>
        <section class="faq">
          <h3>신청 대상은 어디서 확인하나요?</h3><p>정부24, 복지로, 지자체 누리집을 확인합니다.</p>
          <h3>소득 기준은 어떻게 적용되나요?</h3><p>공식 공고에서 소득 기준을 확인합니다.</p>
          <h3>지급 방식은 어떻게 되나요?</h3><p>현금, 카드 포인트, 상품권 등 사업별로 다를 수 있습니다.</p>
        </section>
        <table><tr><th>항목</th><td>대상 조건</td></tr></table>
        <p>체크리스트와 공식 확인 기준을 정리했습니다.</p>
      </article>
    </body></html>
    """


def _specific_driver_license_html() -> str:
    return """
    <html><head>
      <meta name="description" content="청년 운전면허 지원금 신청 전 지역별 대상 조건, 지원 금액, 필요 서류와 공식 확인처를 점검합니다.">
      <script type="application/ld+json">{"@type":"BlogPosting"}</script>
      <script type="application/ld+json">{"@type":"FAQPage"}</script>
    </head><body>
      <article>
        <h1>청년 운전면허 지원금 신청방법과 대상 조건</h1>
        <section id="AI_OVERVIEW_TARGET_ANSWER"><h2>핵심 요약</h2><p>청년 운전면허 지원금은 전국 공통 자동 지급이 아니라 지자체별 청년정책 공고로 확인해야 합니다.</p></section>
        <section id="ISSUE_CONTEXT_BLOCK"><p>2026-05-31 기준, 거주지 시·군·구청 공고와 청년정책 누리집이 최종 기준입니다.</p></section>
        <section id="INTENT_ANSWER_BLOCK" class="faq">
          <h3>청년 운전면허 지원금은 전국 공통 제도인가요?</h3><p>아닙니다. 지자체별 사업이라 거주지, 연령, 거주기간, 예산 소진 여부를 확인해야 합니다.</p>
          <h3>운전면허 취득 전 신청해야 하나요?</h3><p>지역마다 취득 전 신청형과 취득 후 사후 환급형이 달라 신청 시점을 먼저 확인해야 합니다.</p>
          <h3>운전면허 지원금 서류는 무엇인가요?</h3><p>주민등록초본, 신분증, 면허증 사본, 면허학원 영수증, 통장 사본이 필요할 수 있습니다.</p>
        </section>
        <section id="PEOPLE_ALSO_ASK_BLOCK"><h2>함께 묻는 질문</h2><ul><li>운전면허 지원금 금액</li><li>학원비 영수증</li><li>면허증 사본</li><li>지자체별 신청</li><li>사후 환급</li></ul></section>
        <section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"><h2>확인된 내용</h2><p>지원 금액은 20만원, 50만원처럼 지역별 한도가 다를 수 있습니다.</p></section>
        <section id="SOURCE_TRUST_BLOCK"><h2>공식 확인처</h2><p>정부24, 지자체 공고, 시·군·구청, 주민센터, 도로교통공단 안내를 확인합니다.</p></section>
        <table><tr><th>지원 금액</th><td>면허학원 수강료, 응시료, 발급비 중 인정 항목</td></tr></table>
        <p>체크리스트: 신청 기간, 마감, 필요 서류, 접수 번호, 보완 문자 안내를 확인합니다.</p>
        <p>예시: 취득 후 사후 환급형이면 학원비 영수증과 면허증 사본을 보관해야 합니다.</p>
      </article>
    </body></html>
    """


def _scored_policy_candidate() -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(
            topic="청년 운전면허 지원금 신청방법과 대상 조건",
            category="money",
            summary="청년 운전면허 취득비 지원금 신청",
            raw={
                "source_type": "google_news_rss",
                "topic_group": "policy_benefit",
                "content_angle": {"content_type": "policy_deadline"},
                "hook_angle": {"safe_title_keyword": "청년 운전면허 지원금"},
                "click_potential_score": 9,
                "original_topic": "청년 운전면허 지원금 신청방법과 대상 조건",
            },
        ),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=85,
        reason="test",
    )


def test_recommendation_policy_blocks_generic_driver_license_support_article() -> None:
    result = evaluate_news_recommendation_policy(
        title="청년 운전면허 지원금 신청방법과 대상 조건, 신청 전 먼저 볼 3가지",
        topic="청년 운전면허 지원금 신청방법과 대상 조건",
        html=_generic_driver_license_html(),
        content_type="policy_deadline",
        topic_group="policy_benefit",
    )

    assert not result["passed"]
    assert "recommendation_driver_license_specifics_missing" in result["blocking_issues"]
    assert "recommendation_policy_faq_not_topic_specific" in result["blocking_issues"]
    assert result["ai_recommender_score"] < 70


def test_recommendation_policy_accepts_specific_driver_license_support_article() -> None:
    result = evaluate_news_recommendation_policy(
        title="청년 운전면허 지원금 신청방법과 대상 조건",
        topic="청년 운전면허 지원금 신청방법과 대상 조건",
        html=_specific_driver_license_html(),
        content_type="policy_deadline",
        topic_group="policy_benefit",
    )

    assert result["passed"], result
    assert result["policy_specificity_score"] >= 70
    assert result["shareability_score"] >= 70


def test_recommendation_policy_blocks_policy_article_missing_source_specific_facts() -> None:
    html = """
    <html><body>
      <article>
        <h1>안심페이 참여 모집 지원금 신청방법과 대상</h1>
        <section><h2>먼저 볼 핵심</h2><p>정부·지자체 지원금은 대상 조건과 신청 기간을 공식 안내에서 확인해야 합니다.</p></section>
        <section class="faq">
          <h3>안심페이 참여 모집 지원금 신청 대상은 누구인가요?</h3><p>공식 공고에서 소득 기준, 연령, 거주지 조건을 확인해야 합니다.</p>
          <h3>안심페이 참여 모집 지원금 소득 기준은 어떻게 적용되나요?</h3><p>지원금마다 기준중위소득, 건강보험료 기준 등이 다를 수 있습니다.</p>
          <h3>안심페이 참여 모집 지원금 지급 방식은 어떻게 되나요?</h3><p>현금, 상품권, 포인트 등 사업별로 다를 수 있습니다.</p>
        </section>
        <table><tr><th>항목</th><td>대상 조건</td></tr></table>
        <p>체크리스트와 공식 공고 확인 방법을 정리했습니다. 2026-06-02 기준입니다.</p>
      </article>
    </body></html>
    """

    result = evaluate_news_recommendation_policy(
        title="안심페이 참여 모집 지원금 신청방법과 대상",
        topic="안심페이 참여 모집 지원금 신청방법과 대상 조건",
        html=html,
        content_type="policy_deadline",
        topic_group="policy_benefit",
        raw={
            "source_title": "2026년 울산형 석유화학업 근로자 안심페이 지원사업 참여자 모집 공고",
            "source_summary": "울산 소재 석유화학업 재직 근로자에게 1인 50만원 울산페이를 지급합니다.",
        },
    )

    assert not result["passed"]
    assert "recommendation_policy_source_specific_facts_below_3" in result["blocking_issues"]
    assert "recommendation_policy_amount_missing_from_body" in result["blocking_issues"]


def test_recommendation_policy_accepts_policy_article_with_source_specific_facts() -> None:
    html = """
    <html><body>
      <article>
        <h1>울산형 석유화학업 근로자 안심페이 지원사업, 신청 전 볼 3가지</h1>
        <section><h2>먼저 볼 핵심</h2><p>울산형 석유화학업 근로자 안심페이 지원사업은 울산 소재 석유화학업 재직 근로자를 대상으로 1인 50만원 울산페이를 지급하는 공고입니다.</p></section>
        <section class="faq">
          <h3>울산형 석유화학업 근로자 안심페이 지원사업 대상은 누구인가요?</h3><p>울산 소재 석유화학업 및 관련 업종 재직 근로자인지 공고문에서 확인해야 합니다.</p>
          <h3>안심페이 지원 금액과 지급 방식은 어떻게 되나요?</h3><p>공고 기준 핵심값은 1인 50만원이며 지급 방식은 울산페이입니다.</p>
          <h3>신청 기간과 문의처는 어디서 확인하나요?</h3><p>울산시 공식 공고의 신청 기간, 접수처, 담당 문의처를 함께 확인해야 합니다.</p>
        </section>
        <section id="SOURCE_TRUST_BLOCK"><h2>공식 공고와 문의처</h2><p>최종 기준은 울산시 공식 공고와 담당 부서 안내입니다.</p></section>
        <table><tr><th>지원 금액</th><td>1인 50만원</td></tr><tr><th>지급 방식</th><td>울산페이</td></tr></table>
        <p>체크리스트: 신청 대상, 신청 기간, 신청 방법, 필요 서류, 사용처, 접수 번호, 문의처를 확인합니다. 2026-06-02 기준입니다.</p>
      </article>
    </body></html>
    """

    result = evaluate_news_recommendation_policy(
        title="울산형 석유화학업 근로자 안심페이 지원사업, 신청 전 볼 3가지",
        topic="안심페이 참여 모집 지원금 신청방법과 대상 조건",
        html=html,
        content_type="policy_deadline",
        topic_group="policy_benefit",
        raw={
            "source_title": "2026년 울산형 석유화학업 근로자 안심페이 지원사업 참여자 모집 공고",
            "source_summary": "울산 소재 석유화학업 재직 근로자에게 1인 50만원 울산페이를 지급합니다.",
        },
    )

    assert result["passed"], result
    assert result["policy_source_specificity"]["matched_source_fact_count"] >= 3


def test_news_quality_gate_includes_recommendation_policy_result() -> None:
    result = NewsQualityGate().evaluate(
        selected=_scored_policy_candidate(),
        selected_title="청년 운전면허 지원금 신청방법과 대상 조건",
        html=_generic_driver_license_html(),
        image_prompt="clean editorial illustration without text",
        image_alt_text="청년 운전면허 지원금 확인 이미지",
        labels=["지원금", "청년", "운전면허"],
        hashtags=["#지원금", "#청년", "#운전면허"],
        dry_run=False,
        news_publish_mode="publish",
    )

    assert "recommendation_policy" in result
    assert "recommendation_driver_license_specifics_missing" in result["blocking_issues"]
    assert result["ai_recommender_score"] < 70
