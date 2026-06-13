from __future__ import annotations

from datetime import date
import json
import os
import re
from html import escape
from typing import Any

from blogspot_automation.models.news_models import SelectedNewsPlan
from blogspot_automation.services.news_taxonomy import is_delivery_money_text, is_policy_benefit_text, is_tax_refund_text
from blogspot_automation.services.seo_policy import BLOGSPOT_HOME_URL

_BLOG_AUTHOR_NAME = os.getenv("BLOG_AUTHOR_NAME", "holyyomi AI")
_BLOG_BRAND_NAME = os.getenv("BLOG_BRAND_NAME", "holyyomi AI")

# summary에 이 문자열이 포함되면 본문에 절대 사용하지 않음
_RAW_ARTIFACTS = (
    "테스트 후보",
    "fallback",
    "is_test_candidate",
    "관련 테스트",
    "테스트용",
    "raw",
    "scoring",
)

# 금지 표현 (클릭베이트 선정어)
_BLOCKED_WORDS = ("충격", "경악", "발칵", "소름", "역대급")

# ====================================================================== #
#  글 구조 패턴 정의                                                        #
# ====================================================================== #

_PATTERNS: dict[str, dict[str, Any]] = {
    "MONEY_FLOW": {
        "section_titles": [
            ["누가 불만을 말하는가", "돈은 왜 이쪽으로 흐르나"],
            ["비용이 이동하는 경로", "수수료는 어디로 옮겨가나"],
            ["소비자가 놓치는 결제 구조", "할인보다 중요한 최종 결제 금액"],
            ["할인보다 먼저 봐야 할 조건", "지금 확인할 건 결제창이다"],
        ],
        "callout_titles": ["📍 이 글의 핵심", "💡 이 이슈의 진짜 포인트"],
        "guide_titles": ["✅ 손해 보지 않으려면 볼 것", "✅ 지금 확인할 체크포인트"],
        "blockquote_after": 2,
        "preferred_hooks": ["A", "C", "E"],
        "subscribe_variants": [
            "매일 결제하면서 놓치기 쉬운 비용 구조를 짚는다.",
            "겉으로 보이는 할인 뒤, 실제 부담을 추적한다.",
        ],
    },
    "MISREAD": {
        "section_titles": [
            ["사람들이 잘못 읽은 변화", "표면적 변화의 착시"],
            ["기능 업데이트가 아니라 기준 변화다", "실제로 바뀐 기준"],
            ["직장인이 놓치기 쉬운 지점", "내 업무에 생기는 리스크"],
            ["지금 바꿔야 할 사용 습관", "준비할 행동"],
        ],
        "callout_titles": ["🔍 먼저 봐야 할 3가지", "💡 이 변화의 진짜 의미"],
        "guide_titles": ["✅ 지금 당신이 할 수 있는 것", "✅ 놓치기 전에 확인할 것"],
        "blockquote_after": 2,
        "preferred_hooks": ["B", "C", "D"],
        "subscribe_variants": [
            "변화를 뉴스로 소비하지 않고, 내 업무 변수로 읽는 시각을 다룬다.",
            "기능보다 기준이 바뀌는 순간을 짚는다.",
        ],
    },
    "WHO_BENEFITS": {
        "section_titles": [
            ["소비자가 보는 가치", "사람들이 열광하는 이유"],
            ["판매자와 플랫폼이 얻는 것", "구조 안에서 이득을 보는 쪽"],
            ["유행이 가격과 행동을 바꾸는 방식", "소비 구조가 달라지는 지점"],
            ["따라가기 전 확인할 것", "열광 속에서 놓치기 쉬운 비용"],
        ],
        "callout_titles": ["📍 이 글의 핵심", "🔍 열광 뒤에 숨은 구조"],
        "guide_titles": ["✅ 따라가기 전 볼 것", "✅ 소비 전 확인할 체크포인트"],
        "blockquote_after": 3,
        "preferred_hooks": ["D", "E", "B"],
        "subscribe_variants": [
            "유행과 열광 뒤에서 이득을 보는 구조를 짚는다.",
            "소비 트렌드의 이면을 역발상 시각으로 읽는다.",
        ],
    },
    "TREND_DISSECTION": {
        "section_titles": [
            ["왜 갑자기 이게 뜨나", "표면적 인기의 비밀"],
            ["맛보다 강한 건 인증 욕구다", "인증 욕구와 희소성의 구조"],
            ["품절이 만든 유행의 착시", "오래갈 유행인가, 일시적 반응인가"],
            ["따라가기 전에 봐야 할 것", "소비자가 조심할 지점"],
        ],
        "callout_titles": ["💡 이 유행의 진짜 포인트", "🔍 유행 뒤에 숨은 구조"],
        "guide_titles": ["✅ 줄 서기 전에 확인할 것", "✅ 인증 전에 따져볼 것"],
        "blockquote_after": 2,
        "preferred_hooks": ["D", "C", "E"],
        "subscribe_variants": [
            "유행을 따라가기 전, 맛과 마케팅을 구분하는 시각을 다룬다.",
            "인증샷 너머의 소비 구조를 짚는다.",
        ],
    },
    "RISK_WARNING": {
        "section_titles": [
            ["사람들이 가볍게 넘기는 이유", "별일 아닌 듯 보이는 문제"],
            ["실제 손해로 이어지는 지점", "놓치면 커지는 비용"],
            ["기록과 증빙이 결과를 바꾼다", "준비한 사람과 그렇지 않은 사람의 차이"],
            ["지금 바로 할 행동", "지금 놓치면 어떤 손해가 생기나"],
        ],
        "callout_titles": ["⚠️ 지금 확인해야 할 포인트", "📍 이 문제의 핵심"],
        "guide_titles": ["✅ 지금 바로 해둘 것", "✅ 손해 줄이려면 볼 것"],
        "blockquote_after": 3,
        "preferred_hooks": ["A", "E", "C"],
        "subscribe_variants": [
            "가볍게 넘기기 쉬운 생활 리스크의 이면을 짚는다.",
            "증빙과 기록이 결과를 바꾸는 지점을 다룬다.",
        ],
    },
    "DEFAULT_CONTRARIAN": {
        "section_titles": [
            ["표면의 이야기", "대중이 보는 장면"],
            ["놓친 이면", "표면 아래에 있는 것"],
            ["독자에게 생기는 영향", "내 선택에 미치는 변수"],
            ["선택 기준", "지금 할 수 있는 판단"],
        ],
        "callout_titles": ["💡 이 이슈의 진짜 포인트", "📍 이 글의 핵심"],
        "guide_titles": ["✅ 지금 당신이 할 수 있는 것", "✅ 판단 전 확인할 것"],
        "blockquote_after": 2,
        "preferred_hooks": ["B", "E", "C"],
        "subscribe_variants": [
            "겉으로 보이는 결론 대신 이면의 비용·기회·리스크를 짚는다.",
            "대중 반응의 이면에서 선택의 질을 높이는 관점을 다룬다.",
        ],
    },
}


class ContrarianContentService:
    def generate_html(self, plan: SelectedNewsPlan) -> str:
        today = date.today().isoformat()
        title = self._safe_text(plan.selected_title.title)
        topic = self._safe_text(plan.selected_topic.candidate.topic)
        display_topic = self._display_topic(topic)
        category = self._safe_text(plan.selected_topic.candidate.category)
        raw_summary = plan.selected_topic.candidate.summary or ""
        hook_type = self._safe_text(plan.selected_title.hook_type)
        contrarian_angle = self._safe_text(plan.contrarian_angle)
        mainstream_view = self._safe_text(plan.mainstream_view)
        reader_benefit = self._safe_text(plan.reader_benefit)
        labels_text = ", ".join(
            self._safe_text(label) for label in plan.labels[:6] if label.strip()
        )
        raw = plan.selected_topic.candidate.raw if isinstance(plan.selected_topic.candidate.raw, dict) else {}
        content_angle = raw.get("content_angle", {}) if isinstance(raw.get("content_angle"), dict) else {}
        content_type = str(content_angle.get("content_type") or "")
        hashtags = self._hashtags_from_raw(raw, labels_text, content_type, display_topic)

        if content_type:
            return self._generate_content_angle_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text,
                content_angle=content_angle,
                content_type=content_type,
                hashtags=hashtags,
            )

        if self._is_delivery_money_topic(f"{topic} {raw_summary} {category}"):
            return self._generate_delivery_money_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "배달료, 배달앱, 라이더, 생활비, 소비자, 수수료",
            )

        if self._is_policy_benefit_topic(f"{topic} {raw_summary} {category}"):
            return self._generate_policy_benefit_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "AI활용, 업무자동화, AI도구, 프롬프트, 생산성",
            )

        profile = self._get_content_profile(topic, display_topic, category, raw_summary)

        plain_description = self._build_plain_description(
            topic=topic,
            display_topic=display_topic,
            profile=profile,
        )
        meta_description = escape(plain_description)

        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(plan.selected_title.title),
            "description": plain_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
        }

        body_html = self._build_body(
            topic=topic,
            display_topic=display_topic,
            title=title,
            category=category,
            profile=profile,
            labels_text=labels_text or "AI활용, AI도구, 업무자동화, 프롬프트, 선택기준",
        )
        faq_items = self._faq_items_for_content_type("general_life")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)

        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{meta_description}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #F7F7F8;
      color: #1A1A1B;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Arial, sans-serif;
      line-height: 1.75;
      font-size: 16px;
    }}
    .wrap {{
      max-width: 780px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 22px 18px 40px;
    }}
    h1 {{
      margin: 0 0 16px;
      font-size: 30px;
      line-height: 1.35;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    h2 {{
      margin: 34px 0 12px;
      font-size: 22px;
      line-height: 1.4;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    p {{
      margin: 0 0 14px;
      word-break: keep-all;
    }}
    .meta {{
      color: #666;
      font-size: 14px;
      margin-bottom: 18px;
    }}
    .callout {{
      background: #FFF4F3;
      border-left: 4px solid #FF3B30;
      padding: 16px 16px 12px;
      border-radius: 8px;
      margin: 20px 0;
    }}
    .data {{
      color: #007AFF;
      font-weight: 600;
    }}
    blockquote {{
      margin: 20px 0;
      padding: 14px 16px;
      border-left: 4px solid #FF3B30;
      background: #FFF7F6;
      color: #1A1A1B;
    }}
    .guide {{
      margin: 22px 0;
      padding: 16px;
      border: 1px solid #DDE6F7;
      border-radius: 10px;
      background: #F7FAFF;
    }}
    .faq {{
      margin: 28px 0;
      padding: 18px 16px;
      border: 1px solid #E5E7EB;
      border-radius: 10px;
      background: #FFFFFF;
    }}
    .faq h3 {{
      margin: 18px 0 8px;
      font-size: 18px;
      line-height: 1.45;
      word-break: keep-all;
    }}
    .subscribe {{
      margin: 24px 0 0;
      padding: 18px 16px;
      border-radius: 10px;
      border: 1px solid #EFEFEF;
      background: #FAFAFA;
    }}
  </style>
</head>
<body>
  <article class="wrap">
{body_html}
{faq_html}
  </article>
</body>
</html>"""

    # ================================================================== #
    #  패턴 선택                                                           #
    # ================================================================== #

    @staticmethod
    def _select_pattern(text: str) -> str:
        t = text.lower()
        # MONEY_FLOW — 비용·수수료·가격·생활비
        if any(k in t for k in ("수수료", "가격 인상", "요금", "생활비", "배달앱")):
            return "MONEY_FLOW"
        # RISK_WARNING — 피해·환불·지연·보험
        if any(k in t for k in ("피해", "환불", "지연", "분쟁", "카드", "보험")):
            return "RISK_WARNING"
        # MISREAD — AI·서비스 변화·생산성
        if any(k in t for k in ("ai", "요약", "서비스 변화", "생산성", "업무 자동화",
                                 "연봉", "채용", "취업", "이직")):
            return "MISREAD"
        # TREND_DISSECTION — 오픈런·품절·인증샷·밈
        if any(k in t for k in ("오픈런", "품절", "디저트", "인증샷", "밈", "유행", "신조어")):
            return "TREND_DISSECTION"
        # WHO_BENEFITS — 플랫폼·기업·굿즈·팬덤
        if any(k in t for k in ("플랫폼", "기업", "굿즈", "팬덤", "수익", "판매")):
            return "WHO_BENEFITS"
        return "DEFAULT_CONTRARIAN"

    @staticmethod
    def _topic_hash(topic: str, mod: int) -> int:
        """topic에서 결정적이지만 주제마다 달라지는 인덱스."""
        if mod <= 0:
            return 0
        return sum(ord(c) for c in topic) % mod

    # ================================================================== #
    #  콘텐츠 프로필                                                        #
    # ================================================================== #

    def _get_content_profile(
        self, topic: str, display_topic: str, category: str, raw_summary: str
    ) -> dict[str, Any]:
        text = f"{topic} {category} {raw_summary}".lower()

        # display_topic 받침에 맞는 조사
        _eul_reul = self._josa(display_topic, "을/를")
        _eun_neun = self._josa(display_topic, "은/는")
        _i_ga = self._josa(display_topic, "이/가")

        # 패턴 결정
        pattern_name = self._select_pattern(text)

        # A. 배달앱 / 수수료 / 자영업자 / 사장님
        if any(t in text for t in ("배달앱", "수수료", "자영업자", "사장님")):
            return {
                "type": "delivery",
                "pattern": pattern_name,
                "surface_view": "소비자와 자영업자 중 누가 더 억울한가",
                "hidden_angle": (
                    "불만의 크기가 아니라 수수료가 메뉴 가격, 배달비, "
                    "쿠폰 조건으로 어떻게 소비자에게 옮겨가는가"
                ),
                "reader_risk": "겉으로는 할인처럼 보여도 최종 결제 금액은 더 커질 수 있다",
                "reader_point": (
                    "배달비, 메뉴 가격, 쿠폰 조건, 최소 주문 금액을 함께 봐야 "
                    "실제 부담을 판단할 수 있다"
                ),
                "callout_fact": topic,
                "callout_hidden": (
                    "수수료 인상이 메뉴 가격과 배달비, 쿠폰 혜택 축소로 "
                    "이어지는 구조를 보면 부담 주체가 달라진다"
                ),
                "callout_action": (
                    "배달비와 메뉴 가격, 최소 주문 금액을 함께 확인해 "
                    "실제 비용을 비교한다"
                ),
                "action_1": "배달 주문 전 배달비와 매장 직접 주문 가격 차이를 비교한다",
                "action_2": "쿠폰 할인보다 최종 결제 금액 기준으로 판단한다",
                "action_3": "자주 쓰는 플랫폼의 배달비와 최소 주문 금액 변화를 확인한다",
                "comment_question": (
                    "배달앱 수수료 문제, 결국 소비자가 더 부담한다고 보시나요 "
                    "아니면 플랫폼 구조의 문제라고 보시나요?"
                ),
                "hook_openers": {
                    "A": "쿠폰이 많아지는 날, 최종 결제 금액은 오히려 더 조용히 바뀐다.",
                    "B": "이 이슈를 감정 싸움으로만 보면 비용이 어디로 흘러가는지 놓치게 된다.",
                    "C": "진짜 문제는 수수료 자체일까, 아니면 비용이 옮겨가는 방식일까.",
                    "D": "주문 버튼을 누르기 전, 사람들은 쿠폰부터 확인한다. 그런데 봐야 할 건 따로 있다.",
                    "E": "배달앱 수수료가 오를수록 쿠폰은 왜 더 많아질까.",
                },
                "body_p1": (
                    f"{display_topic}{_eul_reul} 보면 대부분은 소비자와 자영업자 중 "
                    "누가 더 억울한지부터 따진다. "
                    "자영업자는 플랫폼 수수료가 너무 높다고 하고, "
                    "소비자는 배달비와 메뉴 가격이 동시에 오른다고 느낀다."
                ),
                "body_p2": (
                    "하지만 이 논란의 진짜 변수는 감정의 크기가 아니다. "
                    "수수료가 배달비, 메뉴 가격, 쿠폰 조건이라는 형태로 "
                    "소비자 결제 화면에 녹아드는 방식이 핵심이다."
                ),
                "body_p3": (
                    "이걸 놓치면 쿠폰으로 할인받았다고 생각하면서도 "
                    "최종 결제 금액에서는 더 비싼 선택을 하게 될 수 있다."
                ),
                "section1_body": [
                    # v0: 이해충돌 프레임 중심
                    (
                        f"표면적으로 {display_topic}{_eun_neun} 플랫폼과 자영업자 사이의 이해충돌로 읽힌다. "
                        "이 프레임은 단순하고 공감이 쉬워서 빠르게 확산되는 경향이 있다."
                        "<br>그런데 이 논란이 반복되는 이유는 분노의 대상이 명확하기 때문이 아니라, "
                        "비용이 어디로 흘러가는지 구조가 잘 안 보이기 때문이다."
                    ),
                    # v1: 최소 주문 금액·배달비 분산 중심
                    (
                        "배달앱 수수료 논란이 반복되는 건 금액의 크기가 아니라 "
                        "구조가 잘 보이지 않기 때문이다. "
                        "소비자는 배달비와 메뉴 가격을 따로 보는 경향이 있지만, "
                        "수수료 부담은 이 두 항목에 동시에 영향을 미칠 수 있다."
                        "<br>최소 주문 금액이 오르거나 쿠폰 혜택이 줄어드는 방식으로 부담이 분산되면, "
                        "소비자가 체감하는 변화는 더 늦게, 더 조용히 나타난다."
                    ),
                    # v2: 소비자 체감·최종 결제 금액 중심
                    (
                        "소비자 입장에서는 쿠폰과 무료배달 문구가 먼저 눈에 들어온다. "
                        "하지만 실제 부담은 메뉴 가격, 배달비, 최소 주문 금액, 쿠폰 조건이 "
                        "합쳐진 최종 결제 금액에서 결정된다."
                        "<br>각 항목을 따로 보면 괜찮아 보여도, 합산하면 달라지는 구조가 여기서 나타난다."
                    ),
                ],
                "section2_body": [
                    # v0: 플랫폼 의존도·결제 구조 중심
                    (
                        "수수료는 플랫폼 내부 비용처럼 보이지만, "
                        "실제로는 배달비, 메뉴 가격, 쿠폰 조건, 최소 주문 금액이라는 형태로 "
                        "소비자 결제 경험에 옮겨올 수 있다. "
                        "자영업자는 플랫폼 의존도 때문에 쉽게 이탈하지 못하는 경우가 많고, "
                        "그 구조 안에서 소비자 부담이 조정되는 방식이 달라진다."
                        "<br>그래서 소비자는 할인 여부보다 최종 결제 금액을 기준으로 판단해야 "
                        "실제 부담을 정확히 알 수 있다."
                    ),
                    # v1: 할인 조건·쿠폰 착시 중심
                    (
                        "할인 금액이 커 보이는 구조일수록 최소 주문 금액이나 배달비가 "
                        "함께 올라가 있을 가능성이 높다. "
                        "쿠폰이 주목을 끄는 사이, 실제 결제 조건이 조용히 바뀌는 방식이다."
                        "<br>소비자가 할인 여부보다 최종 결제 금액을 기준으로 판단해야 하는 이유가 여기에 있다."
                    ),
                    # v2: 자영업자 이면 구조·비용 이동 중심
                    (
                        "이면에는 자영업자가 감당해야 하는 수수료와 광고비, 배달 운영 비용이 있다. "
                        "이 부담이 커지면 메뉴 가격이나 할인 조건이 조정될 가능성이 있다."
                        "<br>소비자가 체감하는 변화는 결국 결제 화면에 나타나기 때문에, "
                        "쿠폰보다 최종 금액을 기준으로 비교하는 습관이 실용적이다."
                    ),
                ],
                "blockquote_text": (
                    "⚠️ 역발상 포인트: 쿠폰 할인이 커 보일수록, "
                    "메뉴 가격·배달비·최소 주문 금액 변화도 함께 봐야 실제 부담을 알 수 있다."
                ),
                "section3_body": [
                    # v0: 협상력·플랫폼 의존도 중심
                    (
                        "수수료 인상 논란에서 이득을 보는 주체는 협상력이 높거나 "
                        "플랫폼 의존도를 줄인 쪽이 될 가능성이 있다. "
                        "반대로 배달앱에만 의존하는 소비자와 플랫폼 없이 주문받기 어려운 소상공인은 "
                        "선택지가 좁다는 점에서 부담을 더 크게 체감할 수 있다."
                        "<br>최종 결제 금액이 달라지는지 확인하는 습관이 이 구조에서 손해를 줄이는 방법이다."
                    ),
                    # v1: 직접 주문·부담 최소화 중심
                    (
                        "플랫폼 의존도가 낮은 매장은 직접 주문 비중을 높이는 방식으로 "
                        "수수료 부담을 줄일 수 있다. "
                        "소비자는 이런 구조를 파악하면 실제 부담이 적은 선택을 할 수 있다."
                        "<br>배달비와 메뉴 가격을 함께 보는 습관이 소비자 입장에서 가장 실용적인 대응이다."
                    ),
                    # v2: 플랫폼 비교·결제 조건 중심
                    (
                        "소비자가 어떤 플랫폼을 선택하느냐에 따라 부담 구조가 달라질 수 있다. "
                        "쿠폰이 많은 플랫폼이 반드시 유리한 선택은 아니다. "
                        "최소 주문 금액과 배달비, 메뉴 가격을 함께 비교하면 실제 차이가 드러난다."
                        "<br>이 정보는 이미 앱 안에 있지만, 조건을 한꺼번에 보는 습관이 없으면 놓치기 쉽다."
                    ),
                ],
                "conclusion": (
                    f"결국 {display_topic}의 핵심은 누가 억울한가보다, "
                    "수수료가 어떤 형태로 이용자 결제에 영향을 주는가다. "
                    "배달비·메뉴 가격·쿠폰 조건을 함께 볼수록 판단이 정확해진다."
                ),
                "echo_sentences": [
                    "문제는 누가 더 억울한지가 아니라, 비용이 누구에게 조용히 옮겨가느냐다.",
                    "겉으로는 할인처럼 보이지만, 실제 판단 기준은 최종 결제 금액이다.",
                    "수수료가 어디로 가는지 모르면, 쿠폰 할인이 손해를 가릴 수 있다.",
                ],
            }

        # B. 환불 / 피해 / 결제
        if any(t in text for t in ("환불", "피해", "결제", "지연")) and any(
            t in text for t in ("소비자", "고객", "이용자", "카드")
        ):
            return {
                "type": "refund",
                "pattern": pattern_name,
                "surface_view": "소비자 피해가 반복되는 문제",
                "hidden_angle": (
                    "환불 지연은 단순 불편이 아니라 결제 신뢰와 소비자 권리의 문제"
                ),
                "reader_risk": "증빙을 남기지 않으면 문제 해결이 길어질 수 있다",
                "reader_point": (
                    "주문 내역, 결제 영수증, 고객센터 기록을 남겨두면 "
                    "환불 처리 속도가 달라질 수 있다"
                ),
                "callout_fact": topic,
                "callout_hidden": (
                    "환불 처리 기준은 플랫폼마다 다르고, 카드사 이의 신청 경로와 "
                    "병행하면 해결 속도가 달라질 수 있다"
                ),
                "callout_action": (
                    "주문 내역과 결제 영수증을 캡처하고 "
                    "고객센터 문의 일시를 기록해 둔다"
                ),
                "action_1": "주문 내역과 결제 영수증을 즉시 캡처해 보관한다",
                "action_2": "고객센터 문의 일시와 내용을 텍스트로 기록한다",
                "action_3": "카드사와 플랫폼 환불 기준을 함께 확인한다",
                "comment_question": (
                    "환불 지연 문제, 플랫폼 책임이 더 크다고 보시나요 "
                    "소비자 확인 책임도 있다고 보시나요?"
                ),
                "hook_openers": {
                    "A": "환불 지연을 가볍게 넘기면, 다음 결제에서도 같은 구조에 걸릴 수 있다.",
                    "B": "이 문제를 플랫폼 탓으로만 보면 소비자가 준비할 수 있는 것을 놓친다.",
                    "C": "환불이 늦어지는 이유는 시스템 문제일까, 아니면 증빙의 차이일까.",
                    "D": "고객센터에 전화를 걸고 대기 음악을 듣는 사이, 환불 기준은 이미 정해져 있다.",
                    "E": "환불을 빠르게 받은 사람들의 공통점은 불만이 아니라 기록이었다.",
                },
                "body_p1": (
                    f"{display_topic}{_eul_reul} 두고 소비자 사이에서는 "
                    "환불이 왜 이렇게 오래 걸리냐는 반응이 빠르게 퍼진다. "
                    "처리 지연이 반복되면서 플랫폼 신뢰에 대한 의문도 함께 커진다."
                ),
                "body_p2": (
                    "그런데 환불 문제의 진짜 변수는 플랫폼의 의지만이 아니라, "
                    "소비자가 남겨둔 증빙의 질이다."
                ),
                "body_p3": (
                    "증빙이 없으면 처리 기준이 불분명해지고, "
                    "결제 취소 여부나 환불 범위가 달라질 수 있다."
                ),
                "section1_body": (
                    f"표면적으로 {display_topic}{_eun_neun} 플랫폼의 처리 기준 문제로 읽힌다. "
                    "특히 환불 지연이 반복될수록 서비스 품질에 대한 불신이 쌓이기 쉽다."
                    "<br>이 감정적 반응은 자연스럽다. 그런데 같은 상황에서도 "
                    "처리 속도나 결과가 달라지는 경우가 있다."
                ),
                "section2_body": (
                    "환불 처리는 플랫폼 내부 기준 외에, "
                    "소비자가 남긴 주문 내역·결제 영수증·문의 기록의 완성도에 영향을 받는다. "
                    "카드사 이의 신청 경로를 병행하면 처리 속도가 달라질 수 있다는 점도 "
                    "알고 있는 소비자와 그렇지 않은 소비자 사이에 결과 차이를 만든다."
                ),
                "blockquote_text": (
                    "⚠️ 역발상 포인트: 환불을 빠르게 받은 사람들의 공통점은 "
                    "증빙을 미리 남겨둔 경우가 많다. 플랫폼 탓보다 먼저 할 일이 있다."
                ),
                "section3_body": (
                    "이득을 보는 쪽은 증빙이 충분하고 카드사 이의 신청도 "
                    "적극 활용하는 소비자다. "
                    "반대로 캡처 없이 기억에만 의존하거나 고객센터 연락 기록이 없는 경우 "
                    "처리 기준이 불리하게 적용될 가능성이 있다."
                ),
                "conclusion": (
                    f"결국 {display_topic}{_eul_reul} 빠르게 해결하는 핵심은 "
                    "플랫폼의 처리 의지만큼이나 소비자가 남겨둔 증빙의 질이다. "
                    "결제하는 순간부터 캡처 습관을 갖는 게 가장 실용적인 대응이다."
                ),
                "echo_sentences": [
                    "증빙을 남기지 않으면, 기다리는 시간이 길어질 뿐이다.",
                    "환불 처리 속도는 플랫폼의 의지보다 소비자 기록의 질에 달려 있다.",
                    "환불이 늦어지는 건 시스템 탓만은 아닐 수 있다.",
                ],
            }

        # C. AI / 생산성 / 서비스 변화
        if any(t in text for t in ("ai", "생산성", "요약", "서비스 변화", "업무 자동화")):
            return {
                "type": "ai",
                "pattern": pattern_name,
                "surface_view": "AI 서비스가 또 바뀌었다는 반응",
                "hidden_angle": (
                    "AI 서비스 변화는 기능 업데이트가 아니라 "
                    "일하는 방식의 기준이 바뀌는 신호"
                ),
                "reader_risk": "하나의 AI 도구에만 의존하면 업무 흐름이 흔들릴 수 있다",
                "reader_point": (
                    "자주 쓰는 AI 기능 변화를 파악하고 "
                    "대체 도구 하나를 미리 확보해두는 것이 실용적이다"
                ),
                "callout_fact": topic,
                "callout_hidden": (
                    "유료 기능 의존도가 높은 작업일수록 "
                    "서비스 변화의 영향이 더 크게 나타날 수 있다"
                ),
                "callout_action": (
                    "자주 쓰는 AI 기능이 바뀌었는지 확인하고 "
                    "대체 가능한 도구를 최소 1개 확보해둔다"
                ),
                "action_1": "자주 쓰는 AI 기능이 바뀌었는지 직접 확인한다",
                "action_2": "업무에서 대체 가능한 도구를 최소 1개 확보한다",
                "action_3": "유료 기능 의존도가 높은 작업을 따로 정리한다",
                "comment_question": (
                    "AI 서비스 변화, 업무 효율을 높이는 기회라고 보시나요 "
                    "도구 의존 리스크라고 보시나요?"
                ),
                "hook_openers": {
                    "A": "자주 쓰던 AI 기능이 갑자기 바뀌면, 업무 흐름 전체가 흔들릴 수 있다.",
                    "B": "이 변화를 기능 업데이트로만 읽으면 진짜 영향을 놓치게 된다.",
                    "C": "AI 기능이 바뀐 날, 진짜 바뀐 건 버튼이 아니라 일하는 기준일 수 있다.",
                    "D": "아침에 출근해서 늘 쓰던 AI 요약 기능을 열었는데 인터페이스가 바뀌어 있다.",
                    "E": "서비스 업데이트라고 쓰고, 유료화라고 읽어야 할 때가 있다.",
                },
                "body_p1": (
                    f"{display_topic}{_eul_reul} 두고 직장인들 사이에서는 "
                    "또 바뀌었네, 유료 기능이 또 줄었다는 반응이 나온다. "
                    "AI 서비스 업데이트 속도가 빨라질수록 이런 반응도 잦아지는 중이다."
                ),
                "body_p2": (
                    "하지만 이 변화의 진짜 변수는 기능 개수가 아니라, "
                    "내 업무 흐름이 특정 AI 도구에 얼마나 묶여 있는가다."
                ),
                "body_p3": (
                    "하나의 도구에 의존도가 높을수록 "
                    "서비스 변화 한 번이 업무 생산성 전체를 흔들 수 있다."
                ),
                "section1_body": (
                    f"표면적으로 {display_topic}{_eun_neun} 서비스 개선이나 기능 조정으로 소개된다. "
                    "업데이트 안내는 긍정적으로 포장되는 경향이 있다."
                    "<br>그런데 실제로는 자주 쓰던 무료 기능이 유료로 전환되거나, "
                    "요약·생성 품질 기준이 달라지는 경우도 생긴다."
                ),
                "section2_body": (
                    "AI 서비스 변화가 반복되는 배경에는 "
                    "유료화 전환과 데이터 품질 경쟁이라는 구조가 있다. "
                    "서비스가 안정화될수록 무료 제공 범위를 줄이고 "
                    "유료 기능 의존도를 높이는 방향으로 움직이는 경향이 있다."
                    "<br>업무 자동화가 특정 AI 도구에 집중되어 있다면 이 변화가 더 크게 느껴진다."
                ),
                "blockquote_text": (
                    "⚠️ 역발상 포인트: 가장 편한 AI 도구가 가장 위험한 의존이 될 수 있다. "
                    "대체 수단을 한 개 이상 파악해두는 것이 리스크를 줄이는 방법이다."
                ),
                "section3_body": (
                    "AI 서비스 변화에서 이득을 보는 쪽은 "
                    "도구를 다양하게 써보고 전환 비용이 낮은 사람이다. "
                    "반대로 특정 AI 기능에 업무 흐름을 완전히 맡겨둔 경우 "
                    "서비스 변화 한 번에 생산성 손실이 커질 수 있다."
                ),
                "conclusion": (
                    f"결국 {display_topic}에서 핵심은 기능의 좋고 나쁨이 아니라, "
                    "내 업무가 특정 AI 도구에 얼마나 묶여 있는가다. "
                    "대체 도구 하나를 미리 확보해두는 것이 가장 실용적인 대응이다."
                ),
                "echo_sentences": [
                    "AI 기능이 바뀐 날, 진짜 바뀐 건 버튼이 아니라 일하는 기준일 수 있다.",
                    "업데이트라고 쓰고, 유료화라고 읽는 경우가 많다.",
                    "편한 도구일수록 의존도를 먼저 확인해야 한다.",
                ],
            }

        # D. 연봉 / 채용 / 취업 / 이직
        if any(t in text for t in ("연봉", "채용", "취업", "이직")):
            return {
                "type": "salary",
                "pattern": pattern_name,
                "surface_view": "평균 연봉이 오르거나 채용이 늘었다는 기사",
                "hidden_angle": (
                    "연봉 체감과 채용 온도차는 개인 능력보다 "
                    "직무별 시장 수요 구조 변화의 신호"
                ),
                "reader_risk": (
                    "평균 연봉 기사만 믿으면 내 직무의 실제 시장가를 "
                    "잘못 판단할 수 있다"
                ),
                "reader_point": (
                    "직무 수요와 요구 역량을 채용 공고 기준으로 직접 확인해야 "
                    "실제 시장가를 알 수 있다"
                ),
                "callout_fact": topic,
                "callout_hidden": (
                    "채용 공고 수와 요구 역량 변화가 "
                    "시장 온도를 더 정확하게 보여주는 경우가 많다"
                ),
                "callout_action": (
                    "내 직무의 최근 채용 공고 수를 직접 확인하고 "
                    "요구 역량 변화를 포트폴리오와 비교한다"
                ),
                "action_1": "내 직무의 최근 채용 공고 수를 직접 확인한다",
                "action_2": "연봉보다 직무 수요와 요구 역량을 같이 본다",
                "action_3": "이직 준비자는 포트폴리오와 성과 지표를 먼저 정리한다",
                "comment_question": (
                    "요즘 채용 시장, 연봉보다 직무 수요가 더 중요하다고 보시나요?"
                ),
                "hook_openers": {
                    "A": "평균 연봉이 오르는데 내 연봉은 그대로라면, 봐야 할 건 통계가 아니다.",
                    "B": "채용이 늘었다는 기사를 그대로 믿으면 내 직무 시장을 잘못 읽을 수 있다.",
                    "C": "연봉이 오른 건 시장이 좋아진 걸까, 특정 직무에 수요가 몰린 걸까.",
                    "D": "채용 공고를 열어보면 같은 직무인데 요구하는 역량이 작년과 다르다.",
                    "E": "채용 시장이 회복됐다는 뉴스 속에서 조용히 줄어드는 직무가 있다.",
                },
                "body_p1": (
                    f"{display_topic}{_eul_reul} 두고 직장인 커뮤니티에서는 "
                    "채용이 늘었다는데 왜 내 직무는 공고가 없지, "
                    "연봉 체감이 통계와 다르다는 반응이 많다."
                ),
                "body_p2": (
                    "하지만 이 온도차의 진짜 변수는 평균값이 아니라 "
                    "직무별 수요 구조다."
                ),
                "body_p3": (
                    "연봉 평균이 오르는 시기에도 특정 직무는 채용이 줄고, "
                    "요구 역량 기준은 오히려 높아지는 패턴이 나타난다."
                ),
                "section1_body": (
                    f"표면적으로 {display_topic}{_eun_neun} 채용 시장이 회복되거나 연봉이 올랐다는 "
                    "긍정 신호로 읽히기 쉽다. 헤드라인 수치는 공감을 얻기 좋다."
                    "<br>그런데 직무별로 나눠 보면 상황이 다른 경우가 많다. "
                    "구인 공고 수가 늘어난 직무와 줄어든 직무가 동시에 존재한다."
                ),
                "section2_body": (
                    "채용 온도차가 생기는 이유는 시장 수요가 특정 직무와 역량으로 "
                    "빠르게 집중되기 때문이다. "
                    "포트폴리오와 성과 지표가 없으면 경쟁에서 밀리는 구조가 강화되는 중이다."
                    "<br>이직 타이밍을 잡으려면 연봉 기사보다 "
                    "직무별 구인 공고 수의 변화를 보는 편이 실용적이다."
                ),
                "blockquote_text": (
                    "⚠️ 역발상 포인트: 평균 연봉이 올라도 내 직무 시장가는 "
                    "떨어질 수 있다. 통계보다 채용 공고가 더 정직한 신호다."
                ),
                "section3_body": (
                    "채용 시장에서 이득을 보는 쪽은 요구 역량 변화에 먼저 반응하고 "
                    "포트폴리오를 갱신한 사람이다. "
                    "반대로 평균 수치만 보고 시장이 좋아졌다고 판단하면 "
                    "이직 타이밍을 놓치거나 협상에서 불리해질 수 있다."
                ),
                "conclusion": (
                    f"결국 {display_topic}에서 핵심은 평균 수치가 아니라 "
                    "내 직무의 채용 공고 수와 요구 역량 변화다. "
                    "이걸 직접 확인하는 사람이 가장 정확한 판단을 할 수 있다."
                ),
                "echo_sentences": [
                    "평균 연봉 기사보다 직무별 채용 공고 수가 더 정직한 신호다.",
                    "채용이 늘었어도 내 직무는 줄었을 수 있다.",
                    "통계는 평균을 말하지만, 시장은 직무를 본다.",
                ],
            }

        # E. 디저트 / 오픈런 / 품절 / 인증샷 / 유행
        if any(t in text for t in ("오픈런", "품절", "디저트", "인증샷", "유행", "밈")):
            return {
                "type": "trend",
                "pattern": pattern_name,
                "surface_view": "맛이 좋아서 줄을 선다",
                "hidden_angle": (
                    "품절과 오픈런은 맛보다 인증 욕구와 "
                    "희소성 마케팅이 만든 현상일 수 있다"
                ),
                "reader_risk": "유행을 따라가다 보면 실제 만족보다 인증 비용이 커질 수 있다",
                "reader_point": (
                    "희소성 마케팅인지 실제 수요인지 구분하면 "
                    "소비 결정의 질이 달라진다"
                ),
                "callout_fact": topic,
                "callout_hidden": (
                    "품절과 재판매가 반복되는 구조는 희소성 마케팅이 "
                    "실제 수요보다 앞서 작동하는 신호일 수 있다"
                ),
                "callout_action": (
                    "재판매가나 과한 대기 비용이 있다면 "
                    "인증 목적인지 실제 소비 목적인지 먼저 구분한다"
                ),
                "action_1": "재판매가나 과한 대기 비용을 경계한다",
                "action_2": "맛보다 인증 목적 소비인지 먼저 구분한다",
                "action_3": "유행이 지속될 제품인지 일시적 화제인지 확인해본다",
                "comment_question": (
                    "오픈런 디저트, 진짜 맛의 힘이라고 보시나요 "
                    "SNS 희소성 마케팅이라고 보시나요?"
                ),
                "hook_openers": {
                    "A": "줄을 서고 대기 시간을 쓴 뒤 돌아보면, 맛보다 인증이 목적이었을 수 있다.",
                    "B": "이 유행을 맛의 검증으로 읽으면 소비 구조를 놓치게 된다.",
                    "C": "오픈런은 맛보다 먼저 희소성을 판다.",
                    "D": "아침 7시, 디저트 매장 앞에 벌써 줄이 늘어서 있다. 오픈까지 한 시간 남았다.",
                    "E": "줄이 길수록 맛있다고 믿지만, 줄이 만든 유행은 맛과 무관할 수 있다.",
                },
                "body_p1": (
                    f"{display_topic}{_eul_reul} 두고 SNS에서는 오늘 몇 시간 줄 섰다, "
                    "벌써 품절이라는 인증샷이 쏟아진다. "
                    "반응이 빠를수록 줄은 더 길어진다."
                ),
                "body_p2": (
                    "그런데 이 현상의 진짜 변수는 맛이 아니라 "
                    "희소성 신호가 얼마나 잘 작동하느냐일 수 있다."
                ),
                "body_p3": (
                    "품절이 인증을 부르고, 인증이 다시 품절을 만드는 구조가 되면 "
                    "소비자의 실제 만족보다 마케팅 효과가 먼저 달성된다."
                ),
                "section1_body": (
                    f"표면적으로 {display_topic}{_eun_neun} 맛있어서 인기를 끄는 음식 이야기로 읽힌다. "
                    "줄 서는 장면과 품절 알림은 검증된 맛이라는 신호처럼 작동한다."
                    "<br>그런데 같은 맛의 제품이 SNS 노출 전후로 대기 시간이 달라지는 경우가 많다. "
                    "맛보다 희소성 마케팅이 먼저 작동하는 구조다."
                ),
                "section2_body": (
                    "오픈런이 반복되는 이면에는 "
                    "의도적으로 수량을 줄여 희소성을 만드는 전략이 있을 수 있다. "
                    "품절이 SNS에서 공유되면 재방문 수요를 자동으로 만들어준다."
                    "<br>소비자는 맛을 경험하기 전에 가야 할 이유를 먼저 소비하게 된다."
                ),
                "blockquote_text": (
                    "⚠️ 역발상 포인트: 줄이 길다고 맛이 좋은 건 아니다. "
                    "줄이 만든 유행인지, 맛이 만든 줄인지 구분할 필요가 있다."
                ),
                "section3_body": (
                    "이 구조에서 이득을 보는 쪽은 희소성 마케팅을 설계한 브랜드다. "
                    "소비자는 대기 시간과 재판매가라는 비용을 부담하면서 "
                    "인증이라는 무형의 만족을 얻는다."
                    "<br>실제 만족 대비 소비 비용을 따져보면 판단이 달라질 수 있다."
                ),
                "conclusion": (
                    f"결국 {display_topic}에서 핵심은 맛보다 희소성 신호가 얼마나 잘 설계됐느냐다. "
                    "인증 목적인지 실제 소비 목적인지 구분하는 습관이 "
                    "불필요한 대기 비용을 줄여준다."
                ),
                "echo_sentences": [
                    "오픈런은 맛보다 먼저 희소성을 판다.",
                    "줄이 마케팅인지 맛인지 구분하면 소비 결정이 달라진다.",
                    "인증샷 욕구가 구매를 결정하는 구조는 소비자에게 불리하다.",
                ],
            }

        # F. 기본 프로필
        return {
            "type": "default",
            "pattern": pattern_name,
            "surface_view": f"{display_topic}에 대한 즉각적 반응과 표면 해석",
            "hidden_angle": (
                f"{display_topic}의 핵심은 감정 반응보다 "
                "비용·시간·선택에 어떤 영향을 주는가"
            ),
            "reader_risk": "표면 정보만 믿고 행동하면 불필요한 비용이 생길 수 있다",
            "reader_point": (
                f"{display_topic}{_i_ga} 내 생활에 직접 영향을 주는 항목이 무엇인지 "
                "먼저 구분해야 판단이 정확해진다"
            ),
            "callout_fact": topic,
            "callout_hidden": (
                f"{display_topic}의 이면에는 이득을 보는 주체와 "
                "부담을 떠안는 주체가 따로 있을 가능성이 있다"
            ),
            "callout_action": (
                "이슈를 소비하기 전에 내 생활에 직접 영향을 주는 항목을 먼저 분리한다"
            ),
            "action_1": f"{display_topic}{_i_ga} 내 비용·시간·선택에 영향을 주는지 먼저 확인한다",
            "action_2": "누가 이득, 누가 부담 관점으로 다시 읽는다",
            "action_3": "오늘 바로 결정하지 않아도 되는 사안은 하루 지연해본다",
            "comment_question": (
                f"{display_topic}, 표면 반응대로 받아들이셨나요 "
                "아니면 다른 각도로 보셨나요?"
            ),
            "hook_openers": {
                "A": "이 이슈를 가볍게 넘기면 내 비용이나 선택에 불필요한 손해가 생길 수 있다.",
                "B": "대중이 이 이슈를 읽는 방식에는 빠진 각도가 있다.",
                "C": "이 이슈의 진짜 변수는 감정 반응일까, 아니면 비용과 선택의 구조일까.",
                "D": "사람들이 이 뉴스를 공유하는 속도는 빠르지만, 질문은 느리다.",
                "E": "모두가 같은 결론으로 달려가는 이슈일수록, 놓친 변수가 있을 가능성이 크다.",
            },
            "body_p1": (
                f"{display_topic}에 대한 반응은 빠르게 한 방향으로 모이는 경향이 있다. "
                "공감하기 쉬운 해석이 먼저 퍼지고, "
                "다른 시각은 천천히 따라오는 구조다."
            ),
            "body_p2": (
                "하지만 같은 이슈를 다른 질문으로 보면 전혀 다른 답이 나올 수 있다. "
                f"{display_topic}의 진짜 변수는 감정 반응의 크기가 아니라 "
                "이 변화가 내 선택과 비용에 어떻게 연결되는가다."
            ),
            "body_p3": (
                "이걸 구분하지 않으면 표면 정보를 기준으로 행동하다가 "
                "불필요한 비용이 생길 수 있다."
            ),
            "section1_body": (
                f"표면적으로 {display_topic}{_eun_neun} 단순한 화제나 논란으로 소비된다. "
                "이해하기 쉽고 공유하기 편한 해석이 먼저 퍼진다."
                "<br>그런데 반응의 속도가 빠를수록 사실 점검은 뒤로 밀리는 경향이 있다. "
                "해석 프레임이 사실 자체보다 먼저 소비되는 구조다."
            ),
            "section2_body": (
                "이슈가 커질 때는 내용의 크기보다 감정의 전염성이 먼저 작동한다. "
                "특히 생활 체감이 닿는 단어가 붙으면 반응은 훨씬 빠르게 확산된다."
                "<br>이 지점에서 이득을 보는 주체와 부담을 떠안는 주체가 나뉘기 시작한다."
            ),
            "blockquote_text": (
                f"⚠️ 역발상 포인트: {display_topic}에서 다수가 동의하는 결론이 "
                "최적의 결론은 아닐 수 있다. "
                "틀릴 가능성을 줄이는 질문이 더 중요하다."
            ),
            "section3_body": (
                "이득은 보통 반응의 타이밍을 먼저 선점하거나 "
                "이면 구조를 먼저 파악한 쪽으로 이동한다. "
                "반대로 표면 정보만 믿고 결정하면 비용이나 선택의 질이 낮아질 수 있다."
            ),
            "conclusion": (
                f"결국 {display_topic}{_eul_reul} 더 빨리 아는 것보다, "
                "더 정확한 질문으로 해석하는 편이 장기적으로 유리하다. "
                "내 생활에 영향을 주는 항목을 먼저 분리하는 것이 첫걸음이다."
            ),
            "echo_sentences": [
                "같은 이슈를 다른 질문으로 보면 전혀 다른 답이 나올 수 있다.",
                "반응의 속도보다 판단의 정확도가 더 중요한 이슈다.",
                "다수가 동의하는 결론이 항상 최적의 결론은 아니다.",
            ],
        }

    # ================================================================== #
    #  plain description (JSON-LD용)                                       #
    # ================================================================== #

    def _build_plain_description(
        self,
        *,
        topic: str,
        display_topic: str,
        profile: dict[str, Any],
    ) -> str:
        ptype = profile.get("type", "default")
        _eun_neun = self._josa(display_topic, "은/는")
        _eul_reul = self._josa(display_topic, "을/를")

        if ptype == "delivery":
            text = (
                f"{display_topic}의 진짜 변수는 불만의 크기가 아니다. "
                "배달비와 메뉴 가격, 쿠폰 조건이 최종 결제 금액으로 이어지는 구조를 짚는다."
            )
        elif ptype == "refund":
            text = (
                f"{display_topic}에서 환불 지연의 핵심은 플랫폼만이 아니다. "
                "소비자 증빙 습관이 처리 속도를 바꾸는 구조를 짚는다."
            )
        elif ptype == "ai":
            text = (
                f"{display_topic}{_eun_neun} 기능 업데이트 소식이 아니다. "
                "내 업무가 특정 AI 도구에 묶여 있을수록 서비스 변화의 영향이 더 커진다."
            )
        elif ptype == "salary":
            text = (
                f"{display_topic}에서 평균 수치보다 직무별 채용 공고 수가 더 정직한 신호다. "
                "직무 수요와 요구 역량으로 시장 온도를 직접 읽는 방법을 짚는다."
            )
        elif ptype == "trend":
            text = (
                f"{display_topic}{_eun_neun} 맛보다 희소성 마케팅이 먼저 작동하는 구조일 수 있다. "
                "인증 비용이 실제 만족보다 커지는 지점을 짚는다."
            )
        else:
            text = (
                f"{display_topic}{_eul_reul} 다수가 보는 방식과 다른 각도로 읽는다. "
                "비용과 선택에 영향을 주는 이면 구조를 짚는다."
            )

        for word in _BLOCKED_WORDS:
            text = text.replace(word, "")
        lower = text.lower()
        for artifact in _RAW_ARTIFACTS:
            if artifact.lower() in lower:
                text = f"{display_topic}의 이면 구조를 역발상 관점에서 짚는다."
                break

        return self._truncate_desc(text)

    # ================================================================== #
    #  제목 echo                                                           #
    # ================================================================== #

    def _extract_title_echo(self, title: str) -> str:
        echo_phrases = (
            "진짜 변수", "이면", "숨은 이유", "함정",
            "놓친", "역발상", "진짜 이유",
        )
        for phrase in echo_phrases:
            if phrase in title:
                return phrase
        return ""

    @staticmethod
    def _faq_items_for_content_type(content_type: str) -> list[dict[str, str]]:
        faq_map: dict[str, list[tuple[str, str]]] = {
            "policy_deadline": [
                ("지원금 신청 전에 가장 먼저 확인할 것은 무엇인가요?", "대상 조건, 신청 기간, 필요 서류를 먼저 확인해야 합니다."),
                ("지원금 신청 마감이 지나면 다시 받을 수 있나요?", "사업마다 다르지만, 대부분 신청 기간이 지나면 해당 회차 접수가 어렵습니다."),
                ("비슷한 지원금을 중복으로 받을 수 있나요?", "일부 사업은 중복 지원이 제한되므로 공식 안내의 중복 지원 기준을 확인해야 합니다."),
            ],
            "money_checklist": [
                ("무료배달이면 항상 더 저렴한가요?", "아닙니다. 최소주문금액과 쿠폰 조건까지 합친 최종 결제금액을 봐야 합니다."),
                ("배달앱 가격은 어떻게 비교해야 하나요?", "같은 메뉴를 기준으로 배달비, 쿠폰, 최소주문금액을 함께 비교해야 합니다."),
                ("쿠폰을 쓰면 무조건 이득인가요?", "쿠폰 조건 때문에 총액이 커질 수 있어 적용 전후 금액을 비교해야 합니다."),
            ],
            "consumer_warning": [
                ("환불이 늦어질 때 가장 먼저 할 일은 무엇인가요?", "결제내역, 주문번호, 상담 기록을 캡처해 증거를 먼저 남겨야 합니다."),
                ("고객센터 답변이 늦으면 어떻게 해야 하나요?", "같은 내용으로 접수 번호와 날짜를 남기고 결제수단 고객센터도 확인해야 합니다."),
                ("배송 중단 피해는 어떻게 기록해야 하나요?", "상품 페이지, 결제내역, 배송 상태, 판매자 답변을 순서대로 캡처해야 합니다."),
            ],
            "platform_change": [
                ("서비스 종료 공지를 보면 먼저 무엇을 확인해야 하나요?", "내 계정, 결제 정보, 백업 가능 여부, 대체 서비스 일정을 먼저 확인해야 합니다."),
                ("구형 기기 지원 종료는 왜 중요한가요?", "앱 업데이트와 보안 기능이 막혀 실제 사용에 문제가 생길 수 있기 때문입니다."),
                ("플랫폼 정책 변경은 어디서 확인해야 하나요?", "공식 공지, 앱 업데이트 안내, 고객센터 도움말을 함께 확인해야 합니다."),
            ],
            "ai_work_tip": [
                ("AI 기능이 바뀌면 먼저 무엇을 확인해야 하나요?", "기존 업무 흐름에서 자동화가 깨지는 부분과 새 설정값을 먼저 확인해야 합니다."),
                ("AI 도구가 업무를 줄여주지 못하는 이유는 무엇인가요?", "입력 방식과 검수 기준이 없으면 오히려 수정 시간이 늘어날 수 있습니다."),
                ("직장인이 AI 도구를 쓸 때 가장 중요한 기준은 무엇인가요?", "빠른 생성보다 반복 업무를 줄이고 결과 검수 시간을 줄이는 기준이 중요합니다."),
            ],
            "trend_decode": [
                ("오픈런이나 품절 유행은 왜 빠르게 퍼지나요?", "희소성, 인증 욕구, SNS 확산이 겹치면 소비 속도가 빨라집니다."),
                ("트렌드 소비 전에 무엇을 확인해야 하나요?", "실제 필요성, 가격, 재판매 가능성, 유행 지속성을 먼저 확인해야 합니다."),
                ("인증샷 소비가 과소비로 이어지는 이유는 무엇인가요?", "제품 가치보다 보여주는 가치가 커지면 지출 판단이 흐려질 수 있습니다."),
            ],
            "viral_issue_decode": [
                ("이 이슈가 커진 핵심 이유는 무엇인가요?", "공식 콘텐츠·경기·방송 반응이 공감과 논쟁을 동시에 만들 때 빠르게 퍼집니다."),
                ("반응이 갈린 이유는 무엇인가요?", "기대치와 실제 결과의 차이, 또는 해석 기준이 달라지면 반응이 분리됩니다."),
                ("이 이슈와 연결된 소비·플랫폼 변화는 무엇인가요?", "팬덤 소비, OTT 요금제, 티켓팅, 플랫폼 알고리즘 중 해당 구조를 확인해야 합니다."),
            ],
        }
        faq_map["today_issue_explainer"] = [
            ("지금 확인된 내용은 무엇인가요?", "현재 공개된 내용과 아직 단정하기 어려운 쟁점을 나눠 봐야 합니다. 이슈의 의미는 후속 발표와 추가 보도에 따라 달라질 수 있습니다."),
            ("왜 오늘 이슈가 됐나요?", "사건 자체보다 지금 관심이 모이는 이유, 관련 이해관계, 이후 파급 가능성이 겹쳤기 때문입니다."),
            ("독자가 바로 봐야 할 지점은 무엇인가요?", "확정된 사실, 아직 확인이 필요한 주장, 내 생활이나 선택에 영향을 줄 수 있는 부분을 분리해 보는 것이 좋습니다."),
        ]
        fallback = [
            ("이 이슈를 볼 때 가장 먼저 확인할 것은 무엇인가요?", "내 돈, 시간, 선택에 직접 영향을 주는 조건부터 확인해야 합니다."),
            ("공식 안내는 어디에서 확인해야 하나요?", "서비스 공지, 신청 페이지, 고객센터 도움말처럼 기준이 되는 원문을 확인해야 합니다."),
            ("오늘 바로 할 수 있는 행동은 무엇인가요?", "내 계정, 결제내역, 신청 조건, 증빙 자료 중 해당되는 항목을 먼저 점검해야 합니다."),
        ]
        return [
            {"question": question, "answer": answer}
            for question, answer in faq_map.get(content_type, fallback)
        ]

    @staticmethod
    def _faq_html(faq_items: list[dict[str, str]]) -> str:
        blocks = ['    <section class="faq faq-block">', "      <h2>자주 묻는 질문</h2>"]
        for item in faq_items[:3]:
            question = escape(str(item.get("question") or "").strip())
            answer = escape(str(item.get("answer") or "").strip())
            blocks.append('      <div class="faq-card">')
            blocks.append(f"      <h3>{question}</h3>")
            blocks.append(f"      <p>{answer}</p>")
            blocks.append("      </div>")
        blocks.append("    </section>")
        return "\n".join(blocks)

    @staticmethod
    def _faq_json_ld(faq_items: list[dict[str, str]]) -> str:
        faq_ld = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": str(item.get("question") or "").strip(),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": str(item.get("answer") or "").strip(),
                    },
                }
                for item in faq_items[:3]
                if str(item.get("question") or "").strip() and str(item.get("answer") or "").strip()
            ],
        }
        return json.dumps(faq_ld, ensure_ascii=False)

    @staticmethod
    def _template_variant(topic: str, content_type: str) -> str:
        seed = sum(ord(char) for char in f"{content_type}:{topic}")
        return ("cards", "table", "guide")[seed % 3]

    @staticmethod
    def _visual_css() -> str:
        return """
    :root { --ink: #18212F; --muted: #5F6B7A; --line: #E3E8EF; --soft: #F6F8FB; --accent: #2563EB; --accent-soft: #EFF6FF; --warn: #B45309; --warn-soft: #FFF7ED; }
    body { margin: 0; padding: 0; background: #F3F5F7; color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Arial, sans-serif; line-height: 1.72; font-size: 16px; }
    .wrap { max-width: 800px; margin: 0 auto; background: #FFFFFF; padding: 22px 18px 42px; }
    h1 { margin: 0 0 16px; font-size: 30px; line-height: 1.32; letter-spacing: 0; color: var(--ink); word-break: keep-all; }
    h2 { margin: 34px 0 14px; font-size: 22px; line-height: 1.38; letter-spacing: 0; color: var(--ink); word-break: keep-all; }
    h3 { letter-spacing: 0; }
    p { margin: 0 0 14px; word-break: keep-all; }
    .meta { color: var(--muted); font-size: 14px; margin-bottom: 16px; }
    .hero-summary-box, .summary { margin: 20px 0 22px; padding: 18px; border: 1px solid #BFDBFE; border-left: 5px solid var(--accent); border-radius: 12px; background: linear-gradient(180deg, #F8FBFF 0%, #EFF6FF 100%); }
    .hero-summary-box .eyebrow, .box-label { margin: 0 0 8px; color: var(--accent); font-size: 13px; font-weight: 700; }
    .hero-summary-box p, .summary p { margin-bottom: 10px; }
    .key-fact-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }
    .fact-card { padding: 15px; border: 1px solid var(--line); border-radius: 12px; background: #FFFFFF; box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05); }
    .fact-card strong { display: block; margin-bottom: 7px; color: var(--accent); font-size: 14px; }
    .fact-card span { display: block; color: var(--ink); font-size: 15px; line-height: 1.55; }
    .guide, .example, .warning, .action-guide-box, .checklist { margin: 24px 0; padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--soft); }
    .target-reader-box, .core-message-box, .hashtag-box { margin: 18px 0; padding: 16px 18px; border: 1px solid var(--line); border-radius: 12px; background: #FFFFFF; }
    .target-reader-box { border-left: 4px solid var(--accent); }
    .core-message-box { border-left: 4px solid #10B981; background: #F0FDF4; }
    .hashtag-box p { margin: 0; color: #334155; font-weight: 700; line-height: 1.9; word-break: keep-all; }
    .warning { border-color: #FED7AA; background: var(--warn-soft); }
    .warning h2, .warning .box-label { color: var(--warn); }
    .example { border-color: #D8B4FE; background: #FAF5FF; }
    .checklist p, .action-guide-box p { padding: 9px 0 9px 12px; border-top: 1px solid rgba(148, 163, 184, 0.24); margin: 0; }
    .checklist p:first-of-type, .action-guide-box p:first-of-type { border-top: 0; }
    .info-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .info-table, .guide-table, .compare-table { width: 100%; border-collapse: collapse; min-width: 620px; font-size: 15px; background: #FFFFFF; }
    .info-table th, .info-table td, .guide-table th, .guide-table td, .compare-table th, .compare-table td { border: 1px solid var(--line); padding: 11px; vertical-align: top; text-align: left; word-break: keep-all; }
    .info-table th, .guide-table th, .compare-table th { background: #EEF2FF; color: #1E3A8A; }
    .faq-block { margin: 30px 0; padding: 0; border: 0; background: transparent; }
    .faq-card { margin: 12px 0; padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: #FFFFFF; box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04); }
    .faq-card h3 { margin: 0 0 8px; font-size: 18px; line-height: 1.45; color: var(--ink); word-break: keep-all; }
    .faq-card p { margin: 0; color: #344054; }
    .variant-table .key-fact-cards { grid-template-columns: 1fr; }
    .variant-guide .fact-card { background: #F8FAFC; }
    .related-ai-blog-box { margin: 24px 0; padding: 18px; border: 1px solid #BBF7D0; border-left: 4px solid #10B981; border-radius: 12px; background: #F0FDF4; }
    .related-ai-blog-box h2 { margin: 0 0 10px; font-size: 18px; color: #065F46; }
    .related-ai-blog-box p { margin: 0 0 10px; color: #134E4A; }
    .related-ai-blog-box a { display: inline-block; margin-top: 6px; padding: 9px 18px; background: #10B981; color: #FFFFFF; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 15px; }
    .related-ai-blog-box a:hover { background: #059669; }
    .yomi-judgment-box { margin: 18px 0; padding: 16px 20px; border: 1px solid #C7D2FE; border-left: 5px solid #6366F1; border-radius: 12px; background: #F5F3FF; }
    .yomi-judgment-box .box-label { margin: 0 0 8px; color: #6366F1; font-size: 13px; font-weight: 700; letter-spacing: 0.02em; }
    .yomi-judgment-box p { margin: 0; color: #1E1B4B; font-size: 15.5px; line-height: 1.7; font-weight: 500; }
    .misconception-box { margin: 18px 0; padding: 16px 20px; border: 1px solid #FCA5A5; border-left: 5px solid #EF4444; border-radius: 12px; background: #FFF5F5; }
    .misconception-box .box-label { margin: 0 0 10px; color: #DC2626; font-size: 13px; font-weight: 700; }
    .misconception-row { margin-bottom: 10px; padding: 10px 12px; border-radius: 8px; }
    .misconception-row.wrong { background: #FEE2E2; color: #7F1D1D; }
    .misconception-row.right { background: #DCFCE7; color: #14532D; font-weight: 600; }
    .misconception-row .label { font-size: 12px; font-weight: 700; margin-bottom: 4px; }
    .quick-decision-table { margin: 18px 0; padding: 16px 20px; border: 1px solid var(--line); border-left: 5px solid #0EA5E9; border-radius: 12px; background: #F0F9FF; }
    .quick-decision-table .box-label { margin: 0 0 12px; color: #0369A1; font-size: 13px; font-weight: 700; }
    .quick-decision-table .qdt-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .quick-decision-table .qdt-table th { background: #E0F2FE; color: #0C4A6E; border: 1px solid #BAE6FD; padding: 8px 10px; text-align: left; }
    .quick-decision-table .qdt-table td { border: 1px solid #BAE6FD; padding: 8px 10px; word-break: keep-all; }
    .quick-decision-table .qdt-table tr:nth-child(even) td { background: #F0F9FF; }
    @media (max-width: 640px) {
      .wrap { padding: 18px 15px 34px; }
      h1 { font-size: 26px; }
      h2 { font-size: 20px; margin-top: 30px; }
      .hero-summary-box, .summary, .guide, .example, .warning, .action-guide-box, .checklist, .target-reader-box, .core-message-box, .hashtag-box, .related-ai-blog-box, .yomi-judgment-box, .misconception-box, .quick-decision-table { padding: 15px; border-radius: 10px; }
      .key-fact-cards { grid-template-columns: 1fr; gap: 10px; }
      .info-table, .guide-table, .compare-table { min-width: 560px; font-size: 14px; }
      .quick-decision-table .qdt-table { min-width: 340px; font-size: 13px; }
    }
"""

    def _hero_summary_box(
        self,
        *,
        content_type: str,
        topic: str,
        reader_question: str,
        reader_loss: str,
        practical_value: str,
    ) -> str:
        target_map = {
            "policy_deadline": "신청 대상자",
            "tax_refund": "세금 환급 대상 여부와 조회 경로를 먼저 확인하고 싶은 사람",
            "consumer_warning": "환불·결제 피해가 걱정되는 소비자",
            "platform_change": "해당 앱이나 서비스를 쓰는 이용자",
            "ai_work_tip": "AI 기능을 업무에 쓰는 직장인",
            "money_checklist": "결제 전 최종 금액을 줄이고 싶은 사람",
            "trend_decode": "유행을 따라가기 전 판단 기준이 필요한 사람",
            "today_issue_explainer": "오늘 이슈의 확정 사실과 해석을 분리해 보고 싶은 사람",
        }
        target = target_map.get(content_type, "오늘 이슈를 내 선택 기준으로 보고 싶은 사람")
        return f"""    <section class="hero-summary-box">
      <p class="eyebrow">먼저 보는 핵심</p>
      <p><strong>누가 봐야 하나:</strong> {escape(target)}</p>
      <p><strong>왜 지금 중요한가:</strong> {escape(reader_loss)}</p>
      <p><strong>이 글의 이득:</strong> {escape(practical_value or reader_question)}</p>
    </section>"""

    @staticmethod
    def _key_fact_cards_html(*, content_type: str, topic: str) -> str:
        cards_by_type = {
            "viral_issue_decode": [
                ("이슈 요약", "공식 기사·공개 콘텐츠 기반으로 한 줄로 정리한다."),
                ("반응 구조", "호평·비판·중간 독자 반응이 갈린 이유를 3개로 나눈다."),
                ("다음 포인트", "팬덤·플랫폼·소비 구조에서 연결된 evergreen 가이드를 확인한다."),
            ],
            "policy_deadline": [
                ("신청 대상", "내 조건이 공고 기준에 맞는지 먼저 본다."),
                ("신청 기간", "마감일과 접수 시간을 놓치면 이번 회차에서 빠질 수 있다."),
                ("사용처·지급", "지급 방식과 제외 업종을 같이 확인해야 실제로 쓸 수 있다."),
            ],
            "tax_refund": [
                ("환급 대상", "내 신고·납부 내역이 환급 대상인지 먼저 본다."),
                ("조회 경로", "홈택스·손택스에서 조회와 신청 경로를 분리해 확인한다."),
                ("계좌·서류", "환급 계좌와 필요 서류가 맞아야 처리 지연을 줄일 수 있다."),
            ],
            "consumer_warning": [
                ("증거", "결제내역·주문번호·상담 기록을 먼저 남긴다."),
                ("기한", "환불 예정일과 답변 지연 날짜를 분리해 기록한다."),
                ("다음 행동", "판매자와 결제수단 고객센터를 함께 확인한다."),
            ],
            "platform_change": [
                ("영향 범위", "내 계정, 기기, 결제 정보에 영향이 있는지 본다."),
                ("마감일", "지원 종료일과 백업 가능 기간을 확인한다."),
                ("대체 경로", "업데이트, 이전, 해지 중 무엇이 필요한지 나눈다."),
            ],
            "ai_work_tip": [
                ("설정", "새 기능의 기본값과 데이터 사용 범위를 먼저 본다."),
                ("업무 영향", "자동화가 깨지는 작업과 줄어드는 작업을 나눈다."),
                ("검수", "사람이 마지막에 확인할 기준을 정한다."),
            ],
            "money_checklist": [
                ("최종 금액", "할인 문구보다 결제창 마지막 금액을 본다."),
                ("조건", "쿠폰, 최소주문금액, 수수료를 함께 계산한다."),
                ("비교", "같은 메뉴 기준으로 앱과 직접 주문을 비교한다."),
            ],
            "trend_decode": [
                ("확산 이유", "희소성, 인증 욕구, 가격 신호를 분리한다."),
                ("소비 기준", "필요성, 가격, 유행 지속성을 함께 본다."),
                ("주의점", "보여주기 가치가 실제 사용 가치보다 커지는지 본다."),
            ],
            "today_issue_explainer": [
                ("확인된 것", "공개된 사실과 아직 해석 단계인 내용을 먼저 분리한다."),
                ("오늘 뜬 이유", "사건 자체보다 지금 관심이 모인 배경과 이해관계를 본다."),
                ("다음 관전점", "후속 발표, 당사자 입장, 실제 영향이 생기는 시점을 본다."),
            ],
        }
        cards = cards_by_type.get(content_type, cards_by_type["trend_decode"])
        card_html = "\n".join(
            f"""      <div class="fact-card"><strong>{escape(label)}</strong><span>{escape(text)}</span></div>"""
            for label, text in cards
        )
        return f"""    <section class="key-fact-cards" aria-label="{escape(topic)} 핵심 카드">
{card_html}
    </section>"""

    @staticmethod
    def _action_guide_html(content_type: str) -> str:
        actions_by_type = {
            "viral_issue_decode": ("이슈의 공식 기사나 공개 콘텐츠 출처를 확인한다.", "반응이 갈린 포인트 3개를 기억한다.", "관련 evergreen 가이드 내부링크를 탐색한다."),
            "policy_deadline": ("공식 공고의 사업명과 마감일을 확인한다.", "내 조건과 필요 서류를 표시한다.", "신청 완료 화면과 접수 번호를 보관한다."),
            "tax_refund": ("홈택스·손택스에서 환급 대상 여부를 조회한다.", "환급 계좌와 본인 인증 정보를 확인한다.", "필요 서류와 신고 완료 내역을 보관한다."),
            "consumer_warning": ("결제내역과 주문번호를 캡처한다.", "고객센터 접수 번호와 날짜를 남긴다.", "환불 예정일과 카드사 문의 결과를 정리한다."),
            "platform_change": ("지원 종료일과 내 기기 버전을 확인한다.", "계정·결제·백업 영향을 나눠 본다.", "업데이트 또는 대체 서비스 일정을 정한다."),
            "ai_work_tip": ("새 기능의 기본 설정을 확인한다.", "업무에 바로 넣을 작업 하나만 고른다.", "검수 기준과 보안 주의점을 기록한다."),
            "money_checklist": ("같은 메뉴를 장바구니까지 담아 비교한다.", "쿠폰 적용 전후 금액을 따로 본다.", "최소주문금액 때문에 추가한 메뉴를 빼고 다시 계산한다."),
            "trend_decode": ("내가 실제로 쓸 이유를 적는다.", "가격과 재고, 재판매 가능성을 확인한다.", "오늘 사지 않아도 되는 이유를 한 줄로 적는다."),
            "today_issue_explainer": ("확정된 사실과 해석을 나눠 읽는다.", "후속 발표로 바뀔 수 있는 부분을 표시한다.", "내 선택이나 관심사에 실제 영향이 있는지 본다."),
        }
        actions = actions_by_type.get(content_type)
        if not actions:
            return ""
        lines = "\n".join(f"      <p>{index}) {escape(action)}</p>" for index, action in enumerate(actions, start=1))
        return f"""    <section class="action-guide-box">
      <h2>지금 바로 할 일 3개</h2>
{lines}
    </section>"""

    @staticmethod
    def _type_warning_box_html(content_type: str) -> str:
        warnings_by_type = {
            "viral_issue_decode": "루머·사생활 중심이 아닌지 확인한다. 확인 안 된 정보를 사실처럼 공유하면 명예훼손 리스크가 있다.",
            "consumer_warning": "기다리기만 하면 기록이 사라질 수 있다. 날짜, 금액, 답변을 먼저 남겨야 한다.",
            "tax_refund": "환급 가능 문구만 보고 끝내면 계좌 오류, 신고 누락, 필요 서류 미비 때문에 처리가 늦어질 수 있다.",
            "platform_change": "공지 제목만 보고 넘기면 백업, 결제, 계정 이전 기한을 놓칠 수 있다.",
            "ai_work_tip": "새 기능을 바로 켜기보다 데이터 사용 범위와 검수 책임을 먼저 나눠야 한다.",
            "money_checklist": "무료, 할인, 쿠폰 문구만 보면 최종 결제금액이 더 커지는 구조를 놓치기 쉽다.",
            "trend_decode": "남들이 산다는 이유만으로 결제하면 실제 사용 가치보다 인증 비용이 커질 수 있다.",
            "today_issue_explainer": "첫 보도와 커뮤니티 반응을 같은 무게로 보면 사실과 해석이 섞인다. 확정된 내용과 관측을 분리해야 한다.",
        }
        warning = warnings_by_type.get(content_type, "기사 제목보다 내 돈, 시간, 선택에 직접 닿는 조건을 먼저 봐야 한다.")
        return f"""    <section class="warning">
      <p class="box-label">놓치기 쉬운 손해 포인트</p>
      <p>{escape(warning)}</p>
    </section>"""

    @staticmethod
    def _target_reader_box_html(*, content_type: str, topic: str) -> str:
        if content_type == "tax_refund":
            message = f"이 글은 {topic} 대상 여부, 조회 경로, 환급 계좌와 필요 서류를 먼저 확인하고 싶은 분에게 필요합니다."
        elif content_type == "policy_deadline":
            message = f"이 글은 {topic} 대상 조건, 신청 기간, 지급 방식, 사용처를 빠르게 확인하고 싶은 분에게 필요합니다."
        else:
            message = f"이 글은 {topic}을 내 돈, 시간, 불안, 선택 기준으로 판단하고 싶은 분에게 필요합니다."
        return f"""    <section class="target-reader-box">
      <p class="box-label">이 글이 필요한 사람</p>
      <p>{escape(message)}</p>
    </section>"""

    @staticmethod
    def _core_message_box_html(*, content_type: str, topic: str) -> str:
        if content_type == "tax_refund":
            message = f"{topic}은 먼저 내가 환급 대상인지, 어디서 조회·신청해야 하는지, 환급 계좌와 필요 서류가 맞는지 확인하는 것이 핵심입니다."
        elif content_type == "policy_deadline":
            message = f"{topic}은 금액보다 대상 조건, 신청 기간, 지급 방식, 사용처를 먼저 확인하는 것이 핵심입니다."
        else:
            message = f"{topic}은 기사 반응보다 내 상황에서 바로 확인할 조건을 먼저 나누는 것이 핵심입니다."
        return f"""    <section class="core-message-box">
      <p class="box-label">먼저 알아야 할 한 가지</p>
      <p>{escape(message)}</p>
    </section>"""

    @staticmethod
    def _target_reader_box_html(*, content_type: str, topic: str) -> str:
        if content_type == "tax_refund":
            message = (
                f"이 글은 세금 환급 대상 여부와 홈택스 조회 경로를 먼저 확인하려는 "
                f"30~50대 직장인에게 필요합니다. {topic}은 계좌, 서류, 신고 내역을 "
                "함께 봐야 처리 지연을 줄일 수 있습니다."
            )
        elif content_type == "policy_deadline":
            message = (
                f"이 글은 {topic} 대상 조건, 신청 기간, 지급 방식, 사용처를 빠르게 "
                "확인하려는 30~50대 직장인과 소비자에게 필요합니다."
            )
        elif content_type == "viral_issue_decode":
            message = (
                f"이 글은 {topic} 반응이 왜 갈렸는지, 팬덤·플랫폼·소비 구조가 어떻게 작동하는지 "
                "이해하고 싶은 30~50대 독자와 대중 이슈 소비자에게 필요합니다."
            )
        elif content_type == "today_issue_explainer":
            message = (
                f"이 글은 {topic}에서 확인된 사실, 아직 단정하기 어려운 주장, 이후 파급 가능성을 "
                "한 번에 구분해 읽고 싶은 독자에게 필요합니다."
            )
        else:
            message = (
                f"이 글은 {topic}을 돈, 시간, 생산성, 생활비, 디지털 변화 기준으로 "
                "판단하려는 30~50대 직장인과 소비자에게 필요합니다."
            )
        return f"""    <section class="target-reader-box">
      <p class="box-label">이 글이 필요한 사람</p>
      <p>{escape(message)}</p>
    </section>"""

    @staticmethod
    def _core_message_box_html(*, content_type: str, topic: str) -> str:
        if content_type == "tax_refund":
            message = f"{topic}의 핵심은 환급 대상 여부, 홈택스·손택스 조회 경로, 환급 계좌와 필요 서류를 먼저 맞추는 것입니다."
        elif content_type == "policy_deadline":
            message = f"{topic}의 핵심은 금액보다 대상 조건, 신청 기간, 지급 방식, 사용처를 먼저 확인해 받을 수 있는 혜택을 놓치지 않는 것입니다."
        elif content_type == "consumer_warning":
            message = f"{topic}의 핵심은 기다리는 것이 아니라 결제내역, 주문번호, 상담 기록을 먼저 남겨 환불 지연 손해를 줄이는 것입니다."
        elif content_type == "platform_change":
            message = f"{topic}의 핵심은 공지 제목이 아니라 내 기기, 계정, 결제, 백업에 실제 영향이 있는지 확인하는 것입니다."
        elif content_type == "ai_work_tip":
            message = f"{topic}의 핵심은 새 기능 소개가 아니라 반복 업무 시간과 검수 시간을 줄일 설정을 고르는 것입니다."
        elif content_type == "money_checklist":
            message = f"{topic}의 핵심은 할인 문구가 아니라 최종 결제금액, 조건, 해지 가능성을 한 번에 비교하는 것입니다."
        elif content_type == "viral_issue_decode":
            message = f"{topic}의 핵심은 단순 반응 소비가 아니라 반응이 갈린 구조와 팬덤·플랫폼·소비 흐름을 이해하는 것입니다."
        elif content_type == "today_issue_explainer":
            message = f"{topic}의 핵심은 빠른 결론이 아니라 확인된 사실, 아직 확인할 쟁점, 다음 관전 포인트를 분리해 보는 것입니다."
        else:
            message = f"{topic}의 핵심은 기사 반응보다 내 상황에서 바로 확인할 조건과 선택 기준을 먼저 나누는 것입니다."
        action = ContrarianContentService._immediate_action_sentence(content_type)
        return f"""    <section class="core-message-box">
      <p class="box-label">먼저 알아야 할 한 가지</p>
      <p>{escape(message)}</p>
      <p><strong>읽고 나서 바로 할 일:</strong> {escape(action)}</p>
    </section>"""

    @staticmethod
    def _immediate_action_sentence(content_type: str) -> str:
        actions = {
            "tax_refund": "홈택스나 손택스에서 환급 대상 여부, 환급 계좌, 신고 완료 내역을 차례로 확인하세요.",
            "policy_deadline": "공식 공고에서 대상 조건, 신청 기간, 지급 방식, 사용처를 체크하고 신청 완료 화면을 보관하세요.",
            "consumer_warning": "결제내역과 상담 기록을 캡처한 뒤 판매자, 플랫폼, 결제수단 고객센터 순서로 확인하세요.",
            "platform_change": "내 기기와 계정이 변경 대상인지 확인하고 결제, 백업, 대체 서비스 일정을 정리하세요.",
            "ai_work_tip": "내 반복 업무 하나를 골라 새 AI 기능의 설정값과 검수 기준을 먼저 정하세요.",
            "money_checklist": "결제 전 최종 금액, 쿠폰 조건, 최소 주문금액을 같은 기준으로 비교하세요.",
            "trend_decode": "지금 사야 하는 이유와 오늘 안 사도 되는 이유를 각각 한 줄로 적어보세요.",
            "viral_issue_decode": "이슈 출처를 확인하고, 반응이 갈린 이유 3개를 기억하고, 관련 evergreen 가이드로 이동하세요.",
            "today_issue_explainer": "확정된 사실, 아직 확인할 주장, 후속 발표로 바뀔 수 있는 부분을 나눠 표시하세요.",
        }
        return actions.get(content_type, "오늘 바로 확인할 조건, 미뤄도 되는 일, 손해를 줄일 행동을 나눠보세요.")

    @staticmethod
    def _yomi_judgment_box_html(content_type: str, topic: str) -> str:
        judgments: dict[str, str] = {
            "tax_refund": (
                f"세금 환급은 '대상 확인'보다 '환급 유형 구분'이 먼저입니다. "
                "국세환급금·종합소득세 환급·연말정산 환급을 한 덩어리로 보면 메뉴부터 헷갈립니다."
            ),
            "policy_deadline": (
                f"지원금은 신청 여부보다 '대상 조건 확인'이 먼저입니다. "
                "이름이 비슷한 지원사업을 혼동하거나 기간을 착각하면 신청 자체가 무의미해집니다."
            ),
            "viral_issue_decode": (
                "이 이슈는 단순 가십이 아닙니다. "
                "반응이 갈린 이유를 팬덤·플랫폼·소비 구조로 보면 다음 이슈도 미리 보입니다."
            ),
            "ai_work_tip": (
                "AI 기능 변화는 '새 기능 소개'보다 '내 업무에서 줄일 반복 작업'이 먼저입니다. "
                "기능보다 기준이 바뀌는 순간을 짚어야 실제로 시간이 줄어듭니다."
            ),
            "money_checklist": (
                "할인 여부보다 '최종 결제금액'을 먼저 봐야 합니다. "
                "쿠폰·배달비·최소주문금액을 따로 보면 싸 보이지만 합산하면 달라집니다."
            ),
            "platform_change": (
                "서비스 변경 공지는 내용보다 '내 계정·기기·결제·백업 영향'을 먼저 봐야 합니다. "
                "공지 제목만 보고 넘기면 실제 불편은 내가 먼저 겪습니다."
            ),
            "consumer_warning": (
                "환불·소비자 피해는 '대응 방법'보다 '기록을 먼저 남기는 것'이 핵심입니다. "
                "날짜와 결제내역은 시간이 지나면 더 찾기 어려워집니다."
            ),
            "today_issue_explainer": (
                "오늘 이슈는 '무슨 일이 있었나'보다 '무엇이 아직 확정되지 않았나'를 먼저 봐야 합니다. "
                "가장 빠른 결론이 아니라 가장 덜 흔들리는 맥락이 오래 남습니다."
            ),
        }
        text = judgments.get(content_type)
        if not text:
            return ""
        return f"""    <section class="yomi-judgment-box">
      <p class="box-label">핵심 관점</p>
      <p>{escape(text)}</p>
    </section>"""

    @staticmethod
    def _misconception_box_html(content_type: str, topic: str) -> str:
        pairs: dict[str, tuple[str, str]] = {
            "tax_refund": (
                "세금 환급은 대상 여부만 확인하면 된다.",
                "대상 여부보다 먼저 환급 유형, 조회 메뉴, 환급 계좌, 보완 요청을 나눠 봐야 한다.",
            ),
            "policy_deadline": (
                "대상이 되면 신청만 하면 받을 수 있다.",
                "대상 조건 외에 신청 기간·접수 시간·지급 방식·사용처 제한·중복 지원 여부를 순서대로 확인해야 한다.",
            ),
            "viral_issue_decode": (
                "이 이슈는 단순 화제성 가십이다.",
                "반응이 갈린 이유를 팬덤·플랫폼·소비 구조로 보면 다음 포인트와 소비 변화가 보인다.",
            ),
            "ai_work_tip": (
                "새 AI 기능을 쓰면 업무가 자동으로 줄어든다.",
                "기능보다 입력 방식·검수 기준·자동화할 반복 작업을 먼저 정해야 실제로 시간이 줄어든다.",
            ),
            "money_checklist": (
                "무료배달이면 무조건 더 저렴하다.",
                "무료배달 여부보다 최소주문금액·메뉴 가격·쿠폰 조건을 합산한 최종 결제금액이 판단 기준이다.",
            ),
            "platform_change": (
                "서비스 종료 공지는 대부분 나와 무관하다.",
                "공지가 나오면 내 계정·결제·기기·백업이 해당되는지 먼저 확인해야 불편을 미리 막을 수 있다.",
            ),
            "consumer_warning": (
                "환불은 요청하면 자동으로 처리된다.",
                "결제내역·주문번호·상담 기록을 먼저 남기지 않으면 처리 지연 때 손해를 줄이기 어렵다.",
            ),
            "today_issue_explainer": (
                "많이 공유된 말이면 이미 사실에 가깝다.",
                "확산 속도와 사실 여부는 다르다. 공개된 사실, 당사자 입장, 아직 확인 중인 해석을 나눠야 한다.",
            ),
        }
        pair = pairs.get(content_type)
        if not pair:
            return ""
        wrong, right = pair
        return f"""    <section class="misconception-box">
      <p class="box-label">🔁 흔한 착각 vs 실제 기준</p>
      <div class="misconception-row wrong">
        <p class="label">흔한 착각</p>
        <p>{escape(wrong)}</p>
      </div>
      <div class="misconception-row right">
        <p class="label">실제 기준</p>
        <p>{escape(right)}</p>
      </div>
    </section>"""

    @staticmethod
    def _quick_decision_table_html(content_type: str, topic: str) -> str:
        rows_by_type: dict[str, list[tuple[str, str]]] = {
            "tax_refund": [
                ("환급금이 보이는데 입금이 안 됨", "계좌번호·예금주 확인 → 보완 요청 조회"),
                ("종합소득세 신고 후 기다리는 중", "신고·납부 내역, 환급 계좌 재확인"),
                ("연말정산 환급이 궁금함", "회사 정산 시점, 급여명세서 반영 확인"),
                ("지방세 환급 같음", "위택스 또는 해당 지자체 안내 별도 확인"),
            ],
            "policy_deadline": [
                ("신청 대상인지 확인하고 싶음", "공식 공고의 대상 조건 먼저 확인"),
                ("마감 기간을 모름", "신청 시작일·마감일·접수 시간 공고 확인"),
                ("신청 후 언제 받는지 궁금함", "지급 방식·지급 예정일 확인"),
                ("어디서 쓸 수 있는지 궁금함", "사용처·제외 업종·지역 제한 확인"),
            ],
            "viral_issue_decode": [
                ("반응이 갈린 이유가 궁금함", "호평·비판 포인트 3개 확인"),
                ("OTT·드라마 이슈가 궁금함", "플랫폼 전략, 시청자 반응 구조 해석"),
                ("팬덤 소비 이슈가 궁금함", "굿즈·티켓팅 구조, 소비 패턴 확인"),
                ("다음 이슈가 어떻게 될지 궁금함", "관련 evergreen 가이드 내부링크"),
            ],
            "ai_work_tip": [
                ("새 AI 기능이 내 업무에 영향을 줌", "설정값, 자동화 범위 먼저 확인"),
                ("반복 업무를 줄이고 싶음", "자동화 후보 작업 1개 선정 후 테스트"),
                ("AI 결과물을 그대로 쓰는 중", "검수 기준, 데이터 사용 범위 정리"),
                ("무료·유료 기능 차이가 궁금함", "기능 한계·비용 비교 후 판단"),
            ],
            "money_checklist": [
                ("무료배달이 정말 싼지 의심됨", "최종 결제금액 두 앱 비교"),
                ("쿠폰 할인이 체감 안 됨", "쿠폰 적용 전후 금액 직접 비교"),
                ("최소주문금액을 채워야 함", "추가 메뉴 비용과 배달비 합산 계산"),
                ("직접 주문이 나은지 궁금함", "매장 직접 주문 가격 확인"),
            ],
            "platform_change": [
                ("내 기기가 지원 종료 대상인지", "기기 버전·공식 지원 목록 확인"),
                ("결제·구독이 영향을 받는지", "자동결제 상태·환불 조건 확인"),
                ("백업이 필요한지", "백업 가능 기간·방법 확인"),
                ("대체 서비스가 있는지", "공식 대체 서비스·이전 일정 확인"),
            ],
            "consumer_warning": [
                ("환불이 안 됨", "결제내역·주문번호 캡처 먼저"),
                ("고객센터 답변이 없음", "접수 번호·날짜 기록 후 재문의"),
                ("배송 중단·연락두절", "플랫폼 고객센터 접수 후 기록"),
                ("카드사 취소가 안 됨", "카드사 고객센터 연락 후 사유 확인"),
            ],
            "today_issue_explainer": [
                ("지금 사실관계가 궁금함", "공개된 사실과 해석을 분리"),
                ("왜 오늘 커졌는지 궁금함", "타이밍, 이해관계, 확산 경로 확인"),
                ("결론이 바뀔 수 있는지 궁금함", "후속 발표와 당사자 입장 표시"),
                ("내게 영향이 있는지 궁금함", "생활·소비·관심사 영향 범위 확인"),
            ],
        }
        rows = rows_by_type.get(content_type)
        if not rows:
            return ""
        row_html = "\n".join(
            f"          <tr><td>{escape(situation)}</td><td>{escape(action)}</td></tr>"
            for situation, action in rows
        )
        return f"""    <section class="quick-decision-table">
      <p class="box-label">⚡ 30초 판단표</p>
      <div style="overflow-x:auto;">
      <table class="qdt-table">
        <thead><tr><th>내 상황</th><th>먼저 볼 것</th></tr></thead>
        <tbody>
{row_html}
        </tbody>
      </table>
      </div>
    </section>"""

    @staticmethod
    def _hashtag_box_html(hashtags: list[str]) -> str:
        cleaned = [str(tag or "").strip() for tag in hashtags if str(tag or "").strip()]
        if not cleaned:
            return ""
        return f"""    <section class="hashtag-box">
      <h2>함께 볼 키워드</h2>
      <p>{escape(" ".join(cleaned[:10]))}</p>
    </section>"""

    @staticmethod
    def _naver_blog_url() -> str:
        return os.getenv("RELATED_AI_BLOG_URL", BLOGSPOT_HOME_URL)

    @staticmethod
    def _naver_blog_box_html(content_type: str, naver_blog_url: str) -> str:
        cta_map = {
            "tax_refund": "AI 도구와 업무 자동화 글은 holyyomi AI 블로그에서 주제별로 이어서 정리합니다.",
            "policy_deadline": "AI 업무 활용, 자동화, 보안 체크 글은 holyyomi AI 블로그에서 계속 정리합니다.",
            "policy_benefit": "AI 업무 활용과 자동화 실험은 holyyomi AI 블로그에서 주제별로 이어서 볼 수 있습니다.",
            "ai_work_tip": "AI 도구 비교, 프롬프트, 자동화 워크플로는 holyyomi AI 블로그에서 계속 업데이트합니다.",
            "money_checklist": "AI 콘텐츠 운영과 생산성 자동화 글은 holyyomi AI 블로그에서 이어서 확인할 수 있습니다.",
            "platform_change": "AI 서비스 변경과 업무 설정 체크리스트는 holyyomi AI 블로그에서 계속 정리합니다.",
            "consumer_warning": "AI 보안, 개인정보, 저작권 리스크 글은 holyyomi AI 블로그에서 이어서 정리합니다.",
        }
        cta_text = cta_map.get(
            content_type or "",
            "holyyomi AI 블로그에서는 AI 도구, 업무 자동화, 프롬프트, 보안 체크 기준을 주제별로 정리합니다.",
        )
        safe_url = escape(naver_blog_url)
        return f"""    <section class="related-ai-blog-box">
      <h2>AI 업무 자동화 글 더 보기</h2>
      <p>{cta_text}</p>
      <p><a href="{safe_url}" target="_blank" rel="noopener noreferrer">holyyomi AI 블로그에서 더 보기</a></p>
    </section>"""

    @staticmethod
    def _hashtags_from_raw(raw: dict[str, Any], labels_text: str, content_type: str, topic: str) -> list[str]:
        raw_hashtags = raw.get("hashtags")
        if isinstance(raw_hashtags, list):
            hashtags = [str(item or "").strip() for item in raw_hashtags]
        else:
            base = {
                "tax_refund": ["AI활용", "체크리스트", "생산성", "AI도구"],
                "policy_deadline": ["AI활용", "업무자동화", "체크리스트", "생산성"],
            }.get(content_type, [])
            label_parts = [part.strip() for part in (labels_text or "").split(",") if part.strip()]
            hashtags = [*base, *label_parts]
            if "청년" in topic:
                hashtags.insert(0, "청년지원금")
        cleaned: list[str] = []
        banned = ("v.daum.net", "n.news.naver.com", ".com", ".co.kr", "뉴스", "일보")
        for tag in hashtags:
            text = "".join(tag.replace("#", "").split()).strip(" ,.-_/\\")
            if not text or len(text) > 14:
                continue
            if any(fragment.lower() in text.lower() for fragment in banned):
                continue
            value = f"#{text}"
            if value not in cleaned:
                cleaned.append(value)
        return cleaned[:10]

    @staticmethod
    def _money_compare_table_html() -> str:
        return """    <section class="guide">
      <h2>비교표로 보는 결제 기준</h2>
      <div class="info-table-wrap">
      <table class="compare-table">
        <thead><tr><th>비교 항목</th><th>볼 내용</th><th>판단 기준</th></tr></thead>
        <tbody>
          <tr><td>최종 결제금액</td><td>메뉴값, 배달비, 수수료, 쿠폰 적용 후 금액</td><td>가장 낮은 금액이 실제 절약이다.</td></tr>
          <tr><td>쿠폰 조건</td><td>최소주문금액, 카드 조건, 시간 제한</td><td>조건을 맞추려고 더 사면 할인 효과가 줄어든다.</td></tr>
          <tr><td>직접 주문</td><td>매장 가격, 포장 할인, 자체 쿠폰</td><td>앱보다 단순한 계산이 더 쌀 수 있다.</td></tr>
        </tbody>
      </table>
      </div>
    </section>"""

    @staticmethod
    def _policy_subject(display_topic: str, content_angle: dict[str, Any]) -> str:
        text = " ".join(
            str(part or "")
            for part in (
                display_topic,
                content_angle.get("reader_question"),
                content_angle.get("reader_loss"),
                content_angle.get("practical_value"),
            )
        )
        patterns = (
            r"[가-힣A-Za-z0-9]+피해지원금",
            r"[가-힣A-Za-z0-9]+청년지원금",
            r"청년\s*운전면허\s*(?:취득비\s*)?지원금",
            r"운전면허\s*(?:취득비\s*)?지원금",
            r"청년지원금",
            r"근로장려금",
            r"자녀장려금",
            r"부모급여",
            r"민생지원금",
            r"생활지원금",
            r"소상공인 지원금",
            r"통신비 환급",
            r"보험료 환급",
            r"국세 환급",
            r"종합소득세 환급",
            r"연말정산 환급",
            r"세금 환급",
            r"환급금",
            r"전기요금 할인",
            r"난방비 지원",
            r"교통비 지원",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()

        topic = (display_topic or "").strip()
        replacements = (
            "신청방법과 대상 조건",
            "신청방법과 사용처 확인",
            "신청 전 이것부터 확인하세요",
            "대상 조건, 놓치기 전 확인할 것",
            "지급일과 신청방법 정리",
            "사용처, 결제 전 확인할 것",
            "대상 조건",
            "신청방법",
            "사용처 확인",
            "확인",
            "정리",
        )
        for phrase in replacements:
            topic = topic.replace(phrase, "")
        topic = re.sub(r"\s+", " ", topic).strip(" ,")
        return topic or "지원금"

    @staticmethod
    def _policy_faq_items(topic: str) -> list[dict[str, str]]:
        if "운전면허" in topic:
            return [
                {
                    "question": f"{topic}은 전국 공통 제도인가요?",
                    "answer": f"{topic}은 보통 전국 공통 자동 지급 제도가 아니라 지자체별 청년 정책으로 운영됩니다. 거주지 시·군·구청 공고와 청년정책 누리집에서 사업명과 예산 소진 여부를 먼저 확인해야 합니다.",
                },
                {
                    "question": f"{topic}은 면허 취득 전 신청해야 하나요?",
                    "answer": "지역에 따라 취득 전 사전 신청형과 취득 후 사후 환급형이 나뉩니다. 자동차운전학원 수강료, 응시료, 면허증 발급일, 영수증 인정 범위가 공고마다 달라 신청 시점을 먼저 확인해야 합니다.",
                },
                {
                    "question": f"{topic} 신청에 필요한 서류는 무엇인가요?",
                    "answer": "주민등록초본, 신분증, 운전면허증 사본, 자동차운전학원 영수증, 통장 사본, 구직·청년 자격 증빙이 요구될 수 있습니다. 최종 서류는 담당 지자체 공고문 기준으로 확인해야 합니다.",
                },
            ]
        return [
            {
                "question": f"{topic} 신청 대상은 누구인가요?",
                "answer": f"{topic} 대상은 소득, 거주지, 연령, 업종 같은 기준에 따라 달라질 수 있어 공식 신청 안내에서 본인 조건을 먼저 대조해야 합니다.",
            },
            {
                "question": f"{topic} 신청 기간은 언제까지인가요?",
                "answer": f"{topic} 신청 기간은 회차와 지역별 공고에 따라 달라질 수 있으니 마감일, 접수 시간, 추가 접수 여부를 함께 확인해야 합니다.",
            },
            {
                "question": f"{topic}은 어디에서 사용할 수 있나요?",
                "answer": f"{topic} 사용처는 카드, 상품권, 계좌 지급 등 지급 방식에 따라 제한될 수 있어 결제 전 가맹점과 제외 업종을 확인해야 합니다.",
            },
        ]

    @staticmethod
    def _tax_refund_faq_items(topic: str) -> list[dict[str, str]]:
        return [
            {
                "question": f"{topic} 대상은 어떻게 확인하나요?",
                "answer": f"{topic} 대상 여부는 홈택스나 손택스의 조회 메뉴에서 본인 신고·납부 내역을 기준으로 확인해야 합니다.",
            },
            {
                "question": f"{topic}은 어디에서 조회하나요?",
                "answer": f"{topic} 조회는 홈택스, 손택스, 국세청 안내 페이지에서 경로와 본인 인증 방식을 먼저 확인하는 것이 안전합니다.",
            },
            {
                "question": f"{topic} 신청 전에 어떤 정보를 준비해야 하나요?",
                "answer": "본인 인증 수단, 신고 내역, 환급 계좌, 필요 서류와 연락처 정보를 미리 확인해야 처리 지연을 줄일 수 있습니다.",
            },
        ]

    @staticmethod
    def _policy_info_table_html(topic: str) -> str:
        if "운전면허" in topic:
            rows = [
                ("전국 공통 여부", "전국 일괄 지급이 아니라 지자체별 청년 운전면허 취득비 지원으로 확인", "지역마다 예산과 조건이 달라 같은 청년이어도 결과가 달라진다."),
                ("신청 대상", "연령, 거주지, 거주기간, 미취업·구직 상태, 소득 기준, 면허 종류", "대상 조건에서 빠지면 학원비를 냈어도 환급이 어렵다."),
                ("지원 금액", "면허학원 수강료, 응시료, 발급비 중 인정 항목과 1인 한도", "공고별로 20만원·50만원처럼 한도와 인정 비용이 다를 수 있다."),
                ("신청 시점", "면허 취득 전 사전 신청인지, 취득 후 사후 환급인지", "신청 순서가 틀리면 영수증이 있어도 반려될 수 있다."),
                ("필요 서류", "주민등록초본, 신분증, 면허증 사본, 학원비 영수증, 통장 사본", "서류 발급과 영수증 보관을 놓치면 마감 전에 보완이 어렵다."),
                ("공식 확인처", "거주지 시·군·구청 공고, 지자체 청년정책 누리집, 주민센터, 담당 부서", "블로그 요약보다 최신 공고문과 담당자 안내가 최종 기준이다."),
                ("제외·반려", "거주기간 부족, 이미 취득한 면허의 소급 불가, 예산 소진, 중복 지원 제한", "받을 수 있는 조건보다 못 받는 조건을 먼저 봐야 실패를 줄인다."),
            ]
            row_html = "\n".join(
                "        <tr>"
                f"<th>{escape(item)}</th>"
                f"<td>{escape(detail)}</td>"
                f"<td>{escape(reason)}</td>"
                "</tr>"
                for item, detail, reason in rows
            )
            return f"""    <section class="guide">
      <h2>{escape(topic)} 지역별 확인표</h2>
      <div class="info-table-wrap">
      <table class="info-table">
        <thead>
          <tr><th>항목</th><th>확인할 내용</th><th>왜 중요한가</th></tr>
        </thead>
        <tbody>
{row_html}
        </tbody>
      </table>
      </div>
    </section>"""
        rows = [
            ("신청 대상", "연령, 거주지, 소득, 업종, 피해 기준", "대상에서 빠지면 금액이나 마감보다 먼저 신청이 막힌다."),
            ("신청 기간", "시작일, 마감일, 접수 시간, 추가 접수 여부", "마감 뒤에는 같은 조건이어도 이번 회차 접수가 어려울 수 있다."),
            ("지급 금액", "1인당 금액, 가구별 한도, 차등 지급 기준", "최종 금액은 발표 기준과 예산에 따라 달라질 수 있다."),
            ("신청 방법", "온라인 신청, 방문 접수, 대리 신청 가능 여부", "접수 방식에 따라 준비할 인증 수단과 서류가 달라진다."),
            ("지급 방식", "계좌 입금, 카드 포인트, 지역상품권, 바우처", "지급 방식에 따라 사용 기한과 사용처 제한이 생긴다."),
            ("사용처", "가능 업종, 제외 업종, 지역 제한, 가맹점 여부", "받아도 실제 결제할 곳이 제한되면 체감 이득이 줄어든다."),
            ("중복 지원 여부", "비슷한 사업과 중복 수급 가능 여부", "중복 제한을 놓치면 환수나 신청 반려가 생길 수 있다."),
            ("필요 서류", "신분 확인, 소득 증빙, 피해 증빙, 통장 사본", "서류 발급이 늦으면 신청 기간 안에 접수가 어려워진다."),
            ("공식 확인처", "정부24, 복지로, 지자체 공고, 전담 콜센터", "기사 제목보다 최신 공고가 최종 기준이다."),
        ]
        row_html = "\n".join(
            "        <tr>"
            f"<th>{escape(item)}</th>"
            f"<td>{escape(detail)}</td>"
            f"<td>{escape(reason)}</td>"
            "</tr>"
            for item, detail, reason in rows
        )
        return f"""    <section class="guide">
      <h2>{escape(topic)} 핵심 정보표</h2>
      <div class="info-table-wrap">
      <table class="info-table">
        <thead>
          <tr><th>항목</th><th>확인할 내용</th><th>왜 중요한가</th></tr>
        </thead>
        <tbody>
{row_html}
        </tbody>
      </table>
      </div>
    </section>"""

    @staticmethod
    def _policy_checklist_html(topic: str) -> str:
        if "운전면허" in topic:
            items = [
                f"{topic}이 전국 공통인지 지자체별 사업인지 먼저 구분한다.",
                "거주지 시·군·구청 공고와 청년정책 누리집에서 사업명, 접수 기간, 예산 소진 여부를 확인한다.",
                "연령, 거주기간, 미취업·구직 상태, 소득 기준, 면허 종류가 대상 조건에 맞는지 표시한다.",
                "면허 취득 전 신청형인지 취득 후 사후 환급형인지 확인하고 학원 등록 순서를 정한다.",
                "자동차운전학원 수강료, 응시료, 발급비 중 어떤 비용이 인정되는지 확인한다.",
                "학원비 영수증, 면허증 사본, 주민등록초본, 신분증, 통장 사본을 마감 전에 준비한다.",
                "중복 지원 제한과 이미 취득한 면허의 소급 가능 여부를 담당 기관에 확인한다.",
                "신청 완료 화면, 접수 번호, 담당 부서 연락처를 캡처해 보관한다.",
            ]
            checklist_items = "\n".join(
                f"      <p>{index}) {escape(item)}</p>" for index, item in enumerate(items, start=1)
            )
            return f"""    <section class="guide checklist">
      <h2>운전면허 지원금 신청 전 체크리스트</h2>
{checklist_items}
    </section>"""
        items = [
            f"{topic} 공식 공고의 사업명과 담당 기관을 먼저 확인한다.",
            "본인 나이, 거주지, 소득, 업종, 피해 기준이 대상 조건에 맞는지 표시한다.",
            "신청 시작일, 마감일, 접수 시간을 캘린더에 넣고 마감 전날 알림을 걸어 둔다.",
            "요일제 접수, 방문 접수 시간, 온라인 본인인증 가능 여부를 확인한다.",
            "신분 확인, 소득 증빙, 피해 증빙, 통장 사본처럼 필요한 서류를 미리 준비한다.",
            "계좌 입금, 카드 포인트, 지역상품권 등 지급 방식을 보고 내가 쓰기 쉬운지 판단한다.",
            "사용처, 제외 업종, 지역 제한, 사용 기한을 결제 전에 다시 확인한다.",
            "다른 지원사업과 중복 수급이 가능한지 공식 안내의 제한 문구를 읽는다.",
            "신청 완료 화면, 접수 번호, 문자 안내를 캡처해 나중에 확인할 수 있게 보관한다.",
        ]
        checklist_items = "\n".join(
            f"      <p>{index}) {escape(item)}</p>" for index, item in enumerate(items, start=1)
        )
        return f"""    <section class="guide checklist">
      <h2>오늘 바로 할 체크리스트</h2>
{checklist_items}
    </section>"""

    @staticmethod
    def _tax_refund_info_table_html(topic: str) -> str:
        rows = [
            ("환급 유형 구분", "국세환급금, 미수령 환급금, 종합소득세 환급, 연말정산 환급, 지방세 환급 가능성", "유형을 나누지 않으면 조회 메뉴와 필요한 조치가 엇갈릴 수 있다."),
            ("조회 메뉴", "홈택스·손택스 환급금 조회, 국세환급금 찾기, 신고·납부 내역", "환급금 조회와 정정 신고는 목적이 달라 먼저 메뉴를 구분해야 한다."),
            ("본인 인증", "공동인증서, 간편인증, 휴대폰 인증 가능 여부", "인증이 막히면 환급금이 보여도 계좌 수정이나 보완 확인을 바로 하기 어렵다."),
            ("신고/납부 내역", "종합소득세 신고, 연말정산 반영, 공제 자료 반영 여부", "신고 내역이 누락되면 환급 대상이라고 생각해도 금액이 잡히지 않을 수 있다."),
            ("환급 계좌", "본인 명의 계좌, 계좌번호, 예금주 정보", "계좌번호 오류나 예금주 불일치는 환급 지연의 가장 흔한 원인이다."),
            ("보완 요청", "홈택스 알림, 손택스 안내, 문자, 우편 또는 전자고지", "보완 요청을 놓치면 처리 순서가 뒤로 밀리거나 지급이 늦어진다."),
            ("지연 원인", "계좌번호 오류, 예금주 불일치, 공제 자료 누락, 중복 신고, 연락처 오류", "지연 원인을 먼저 좁히면 세무서 문의 전에 확인할 항목이 분명해진다."),
            ("필요 서류", "소득 자료, 공제 증빙, 신고서, 안내문, 접수 번호", "증빙이 빠지면 환급액이 달라지거나 처리가 늦어질 수 있다."),
            ("문의 경로", "홈택스 상담, 손택스, 국세청 안내, 관할 세무서, 지방세는 위택스·지자체", "국세와 지방세는 확인처가 달라 같은 메뉴에서 모두 해결되지 않는다."),
            ("공식 확인처", "국세청, 홈택스, 손택스, 위택스, 관할 세무서", "블로그나 기사보다 공식 조회 화면과 안내 문구가 최종 기준이다."),
        ]
        row_html = "\n".join(
            "        <tr>"
            f"<th>{escape(item)}</th>"
            f"<td>{escape(detail)}</td>"
            f"<td>{escape(reason)}</td>"
            "</tr>"
            for item, detail, reason in rows
        )
        return f"""    <section class="guide">
      <h2>{escape(topic)} 핵심 정보표</h2>
      <div class="info-table-wrap">
      <table class="info-table">
        <thead>
          <tr><th>항목</th><th>확인할 내용</th><th>왜 중요한가</th></tr>
        </thead>
        <tbody>
{row_html}
        </tbody>
      </table>
      </div>
    </section>
    <section class="guide action-guide-box">
      <h2>홈택스·손택스에서 보는 순서</h2>
      <p>1) 먼저 {escape(topic)}이 국세환급금, 미수령 환급금, 종합소득세 환급, 연말정산 환급, 지방세 환급 가능성 중 어디에 가까운지 나눈다.</p>
      <p>2) 홈택스나 손택스에서 본인 인증이 되는지 확인한 뒤 환급금 조회 메뉴와 신고·납부 내역을 차례로 본다.</p>
      <p>3) 환급금이 보이면 환급 계좌의 예금주와 계좌번호, 보완 요청 여부, 연락처 정보를 함께 확인한다.</p>
      <p>4) 환급이 늦어지면 계좌번호 오류, 예금주 불일치, 공제 자료 누락, 중복 신고, 연락처 오류, 검토·보완 요청 순서로 좁혀 본다.</p>
    </section>
    <section class="guide example-box">
      <h2>구체 상황 예시</h2>
      <p>홈택스에서 환급금은 보이는데 계좌 정보가 틀린 경우에는 대상 여부보다 계좌 수정과 보완 요청 확인이 먼저다.</p>
      <p>환급 대상인 줄 알았지만 신고 내역이 누락된 경우에는 환급금 조회와 정정 신고를 구분해야 한다.</p>
      <p>손택스에서는 조회했지만 보완 요청을 못 본 경우에는 문자, 전자고지, 홈택스 알림을 다시 확인해야 지연을 줄일 수 있다.</p>
      <p><strong>상황별 확인 경로:</strong> 미수령 국세환급금이 궁금하면 홈택스 '국세환급금 찾기'를 먼저 확인한다. 종합소득세 환급은 신고·납부 내역과 환급 계좌를 함께 본다. 연말정산 환급은 회사 정산 시점과 급여 반영 여부를 함께 확인한다. 지방세 환급은 위택스 또는 해당 지자체 안내를 별도로 확인한다.</p>
    </section>"""

    @staticmethod
    def _tax_refund_checklist_html(topic: str) -> str:
        items = [
            "내가 보는 환급이 국세환급금, 미수령 환급금, 종합소득세 환급, 연말정산 환급, 지방세 환급 가능성 중 무엇인지 먼저 구분한다.",
            "홈택스/손택스 로그인 가능 여부와 본인 인증 수단을 확인한다.",
            "환급금 조회 메뉴에서 미수령 환급금 여부를 확인한다.",
            "신고·납부 내역에서 환급 사유와 신고 반영 여부를 확인한다.",
            "환급 계좌의 예금주와 계좌번호를 다시 본다.",
            "보완 요청, 안내 문자, 전자고지, 연락처 오류가 있는지 확인한다.",
            "환급이 늦어질 때 계좌번호 오류, 예금주 불일치, 공제 자료 누락, 중복 신고를 순서대로 점검한다.",
            "정정 신고가 필요한 상황인지 단순 조회 상황인지 메뉴명으로 구분한다.",
            "접수 번호와 조회 화면을 캡처해 보관한다.",
        ]
        checklist_items = "\n".join(
            f"      <p>{index}) {escape(item)}</p>" for index, item in enumerate(items, start=1)
        )
        return f"""    <section class="guide checklist">
      <h2>오늘 바로 할 체크리스트</h2>
{checklist_items}
    </section>"""

    def _generate_policy_deadline_content_angle_html(
        self,
        *,
        title: str,
        display_topic: str,
        labels_text: str,
        content_angle: dict[str, Any],
        hashtags: list[str] | None = None,
    ) -> str:
        today = date.today().isoformat()
        topic = self._safe_text(self._policy_subject(display_topic, content_angle))
        is_tax_refund = str(content_angle.get("content_type") or "") == "tax_refund" or is_tax_refund_text(topic)
        render_type = "tax_refund" if is_tax_refund else "policy_deadline"
        reader_loss = self._safe_text(
            str(
                content_angle.get("reader_loss")
                or (
                    f"{topic}은 환급 대상 여부와 조회 경로, 환급 계좌를 놓치면 돌려받을 수 있는 금액 확인이 늦어질 수 있다."
                    if is_tax_refund
                    else f"{topic}은 대상 조건과 신청 기간을 놓치면 받을 수 있는 지원을 놓칠 수 있다."
                )
            )
        )
        practical_value = self._safe_text(
            str(
                content_angle.get("practical_value")
                or (
                    f"{topic} 조회 전 확인할 대상, 홈택스·손택스 경로, 환급 계좌와 필요 서류 체크리스트를 제공한다."
                    if is_tax_refund
                    else f"{topic} 신청 전 확인할 대상, 기간, 지급 방식, 사용처 체크리스트를 제공한다."
                )
            )
        )
        meta_description = (
            f"{topic} 환급 대상, 조회 방법, 신청 경로, 홈택스·손택스 확인, 필요 서류와 환급 계좌를 공식 안내 기준으로 점검하는 체크리스트."
            if is_tax_refund
            else f"{topic} 신청 전 대상, 신청 기간, 지급 금액, 신청 방법, 지급 방식, 사용처, 제외 조건을 공식 안내 기준으로 점검하는 체크리스트."
        )
        faq_items = self._tax_refund_faq_items(topic) if is_tax_refund else self._policy_faq_items(topic)
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        variant = self._template_variant(topic, render_type)
        visual_css = self._visual_css()
        hero_html = self._hero_summary_box(
            content_type=render_type,
            topic=topic,
            reader_question=f"{topic}은 누가, 어디서, 어떻게 조회해야 할까?" if is_tax_refund else f"{topic}은 누가, 언제, 어떻게 신청해야 할까?",
            reader_loss=reader_loss,
            practical_value=practical_value,
        )
        target_reader_html = self._target_reader_box_html(content_type=render_type, topic=topic)
        core_message_html = self._core_message_box_html(content_type=render_type, topic=topic)
        yomi_judgment_html = self._yomi_judgment_box_html(render_type, topic)
        key_fact_cards_html = self._key_fact_cards_html(content_type=render_type, topic=topic)
        misconception_html = self._misconception_box_html(render_type, topic)
        quick_decision_html = self._quick_decision_table_html(render_type, topic)
        info_table_html = self._tax_refund_info_table_html(topic) if is_tax_refund else self._policy_info_table_html(topic)
        checklist_html = self._tax_refund_checklist_html(topic) if is_tax_refund else self._policy_checklist_html(topic)
        action_guide_html = self._action_guide_html(render_type)
        hashtag_html = self._hashtag_box_html(hashtags or self._hashtags_from_raw({}, labels_text, render_type, topic))
        naver_blog_html = self._naver_blog_box_html(render_type, self._naver_blog_url())
        summary_html = (
            f"""    <section class="summary hero-summary-box">
      <h2>3줄 요약</h2>
      <p>대상: {topic}은 신고·납부 내역, 소득 자료, 공제 반영 여부를 먼저 대조해야 한다.</p>
      <p>조회: 홈택스·손택스에서 환급 대상 여부와 신청/신고 경로를 확인한다.</p>
      <p>핵심: 환급 계좌, 필요 서류, 지급 예상 시점, 입력 오류를 같이 봐야 처리 지연을 줄일 수 있다.</p>
    </section>"""
            if is_tax_refund
            else f"""    <section class="summary hero-summary-box">
      <h2>3줄 요약</h2>
      <p>대상: {topic}은 소득, 거주지, 연령, 업종, 피해 기준처럼 발표된 자격 조건을 먼저 대조해야 한다.</p>
      <p>기간: 신청 시작일, 마감일, 접수 시간, 추가 접수 여부를 공식 신청 페이지에서 확인한다.</p>
      <p>지급/사용: 금액, 지급 방식, 사용처, 제외 업종, 중복 지원 제한을 함께 봐야 실제로 받을 수 있는지 판단할 수 있다.</p>
    </section>"""
        )
        example_html = (
            ""
            if is_tax_refund
            else f"""    <section class="guide">
      <h2>독자 상황 예시</h2>
      <p>예를 들어 {topic} 대상 조건에는 맞더라도 신청 기간을 놓치면 지급 대상이어도 이번 회차에서 빠질 수 있다. 반대로 신청은 했지만 사용처나 제외 업종을 늦게 보면 받은 뒤에도 실제 결제에서 막힐 수 있다.</p>
      <p>{reader_loss}</p>
      <p>{practical_value}</p>
    </section>"""
        )
        warning_html = (
            f"""    <section class="warning">
      <h2>놓치기 쉬운 함정</h2>
      <p>환급 대상이라는 말만 보고 끝내면 조회 메뉴, 신고 경로, 환급 계좌 확인을 놓칠 수 있다. 특히 계좌번호나 예금주 정보가 맞지 않으면 지급이 늦어질 수 있다.</p>
      <p>공제 자료 누락, 중복 신고, 연락처 오류, 보완 요청 미확인은 환급 지연으로 이어진다. 최종 기준은 기사 문장이 아니라 국세청, 홈택스, 손택스의 공식 조회 화면이다.</p>
    </section>"""
            if is_tax_refund
            else """    <section class="warning">
      <h2>놓치기 쉬운 함정</h2>
      <p>이름이 비슷한 지원사업을 혼동하면 대상 조건과 신청 기관을 잘못 볼 수 있다. 신청 기간을 월말까지로 착각하거나 접수 시간을 놓치는 경우도 많다.</p>
      <p>지급 방식을 선택한 뒤 변경이 제한될 수 있고, 사용처가 지역이나 업종으로 제한될 수도 있다. 서류 발급이 늦어지면 마감 전에 접수를 끝내기 어렵기 때문에 미리 준비하는 편이 낫다.</p>
    </section>"""
        )
        official_html = (
            f"""    <section class="guide">
      <h2>공식 확인 순서</h2>
      <p>기사 제목은 출발점일 뿐 최종 기준은 공식 조회 화면이다. 국세청, 홈택스, 손택스, 관할 세무서 안내에서 환급 대상, 신청/신고 경로, 환급 계좌, 지급 예상 시점을 함께 확인한다.</p>
      <p>세부 대상, 환급 금액, 지급 예상 시점은 신고 내용과 검토 상태에 따라 달라질 수 있다. 그래서 신청 전에는 기사 문장보다 공식 안내와 조회 화면의 최신 기준을 마지막으로 맞춰 보는 편이 안전하다.</p>
      <p>관련 키워드: {labels_text}</p>
    </section>"""
            if is_tax_refund
            else f"""    <section class="guide">
      <h2>공식 확인 순서</h2>
      <p>기사 제목은 출발점일 뿐 최종 기준은 공식 공고다. 정부24, 복지로, 지자체 공고, 전담 콜센터, 신청 페이지에서 사업명과 최신 수정 공지를 함께 확인한다.</p>
      <p>세부 대상, 지급 금액, 신청 기간은 공고마다 달라질 수 있다. 그래서 신청 전에는 기사 문장보다 공식 공지와 신청 페이지의 최신 기준을 마지막으로 맞춰 보는 편이 안전하다.</p>
      <p>관련 키워드: {labels_text}</p>
    </section>"""
        )
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
{visual_css}
  </style>
</head>
<body>
  <article class="wrap visual-article variant-{variant}">
    <h1>{title}</h1>
    <p class="meta">카테고리: AI활용 · 유형: {render_type} · 기준일: {today}</p>
{hero_html}
{target_reader_html}
{core_message_html}
{yomi_judgment_html}
{key_fact_cards_html}
{misconception_html}
{quick_decision_html}
{summary_html}
{info_table_html}
{example_html}
{checklist_html}
{warning_html}
{faq_html}
{action_guide_html}
{official_html}
{naver_blog_html}
{hashtag_html}
  </article>
</body>
</html>"""

    # ================================================================== #
    #  본문 HTML 조립                                                       #
    # ================================================================== #

    def _generate_content_angle_html(
        self,
        *,
        title: str,
        display_topic: str,
        labels_text: str,
        content_angle: dict[str, Any],
        content_type: str,
        hashtags: list[str] | None = None,
    ) -> str:
        if content_type in {"policy_deadline", "tax_refund"}:
            return self._generate_policy_deadline_content_angle_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "AI활용, 업무자동화, AI도구, 프롬프트, 생산성",
                content_angle=content_angle,
                hashtags=hashtags,
            )

        if content_type == "money_checklist":
            return self._generate_money_checklist_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "배달앱, 무료배달, 쿠폰, 최종 결제금액, 생활비",
                content_angle=content_angle,
                hashtags=hashtags,
            )

        if content_type == "viral_issue_decode":
            return self._generate_viral_issue_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "AI뉴스해석, 콘텐츠AI, AI트렌드, 반응분석, 이슈해석",
                content_angle=content_angle,
                hashtags=hashtags,
            )

        if content_type == "today_issue_explainer":
            return self._generate_timeline_context_html(
                title=title,
                display_topic=display_topic,
                labels_text=labels_text or "AI뉴스해석, 맥락정리, 사실확인, 관전포인트, AI트렌드",
                content_angle=content_angle,
                hashtags=hashtags,
            )

        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "오늘 생활 이슈")
        reader_question = self._safe_text(str(content_angle.get("reader_question") or "지금 무엇을 확인해야 할까?"))
        reader_loss = self._safe_text(str(content_angle.get("reader_loss") or "늦게 확인하면 손해가 커질 수 있다."))
        practical_value = self._safe_text(str(content_angle.get("practical_value") or "오늘 바로 확인할 기준을 정리한다."))
        meta_description = self._plain_text(f"{reader_question} {reader_loss} {practical_value}")
        variant = self._template_variant(safe_display_topic, content_type)
        visual_css = self._visual_css()
        hero_html = self._hero_summary_box(
            content_type=content_type,
            topic=safe_display_topic,
            reader_question=reader_question,
            reader_loss=reader_loss,
            practical_value=practical_value,
        )
        key_fact_cards_html = self._key_fact_cards_html(content_type=content_type, topic=safe_display_topic)
        target_reader_html = self._target_reader_box_html(content_type=content_type, topic=safe_display_topic)
        core_message_html = self._core_message_box_html(content_type=content_type, topic=safe_display_topic)
        yomi_judgment_html = self._yomi_judgment_box_html(content_type, safe_display_topic)
        misconception_html = self._misconception_box_html(content_type, safe_display_topic)
        quick_decision_html = self._quick_decision_table_html(content_type, safe_display_topic)
        section_html = self._content_angle_sections(content_type=content_type)
        checklist_html = self._action_checklist_html(content_type=content_type)
        warning_html = self._type_warning_box_html(content_type)
        action_guide_html = self._action_guide_html(content_type)
        hashtag_html = self._hashtag_box_html(hashtags or self._hashtags_from_raw({}, labels_text, content_type, safe_display_topic))
        naver_blog_html = self._naver_blog_box_html(content_type, self._naver_blog_url())
        faq_items = self._faq_items_for_content_type(content_type)
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
{visual_css}
  </style>
</head>
<body>
  <article class="wrap visual-article variant-{variant}">
    <h1>{title}</h1>
    <p class="meta">카테고리: AI활용 · 유형: {content_type} · 기준일: {today}</p>
{hero_html}
{target_reader_html}
{core_message_html}
{yomi_judgment_html}
{key_fact_cards_html}
{misconception_html}
{quick_decision_html}
{section_html}
{warning_html}
{checklist_html}
{action_guide_html}
{faq_html}
    <section class="guide">
      <p><strong>관련 키워드</strong></p>
      <p>{labels_text}</p>
    </section>
{naver_blog_html}
{hashtag_html}
  </article>
</body>
</html>"""

    def _action_checklist_html(self, *, content_type: str) -> str:
        items_by_type = {
            "policy_deadline": [
                "공식 공지나 신청 페이지에서 사업명, 신청 기간, 접수 기관을 확인한다.",
                "대상 조건, 소득/거주 기준, 중복 지원 제한을 내 상황에 맞춰 체크한다.",
                "필요 서류, 지급 방식, 사용처를 캡처해 신청 전후에 바로 확인할 수 있게 남긴다.",
            ],
            "consumer_warning": [
                "주문번호, 결제내역, 상담 날짜처럼 분쟁 기준이 되는 기록을 먼저 모은다.",
                "판매자 답변과 고객센터 접수 번호를 같은 순서로 캡처해 둔다.",
                "환불 예정일, 배송 상태, 결제수단 문의 결과를 한곳에 정리한다.",
            ],
            "platform_change": [
                "공식 공지에서 종료일, 지원 기기, 계정 영향 범위를 확인한다.",
                "내 기기 버전, 결제 정보, 백업 가능 여부를 바로 점검한다.",
                "대체 서비스나 업데이트 일정이 필요한지 캘린더에 표시한다.",
            ],
            "ai_work_tip": [
                "새 AI 기능이 바꾼 설정값과 내 업무 흐름의 영향을 나눠 확인한다.",
                "자동화가 실패했을 때 사람이 검수할 기준을 먼저 정한다.",
                "반복 작업 하나를 골라 입력 방식, 검수 시간, 보안 주의점을 기록한다.",
            ],
            "trend_decode": [
                "지금 사야 하는 이유와 기다려도 되는 이유를 각각 적어 본다.",
                "가격, 재고, 재판매 가능성, 유행 지속성을 함께 비교한다.",
                "인증샷 가치보다 실제 사용 시간이 긴지 확인하고 결제한다.",
            ],
        }
        items = items_by_type.get(content_type)
        if not items:
            return ""
        checklist_items = "\n".join(
            f"      <p>{index}) {escape(item)}</p>" for index, item in enumerate(items, start=1)
        )
        return f"""    <section class="guide">
      <p><strong>오늘 바로 할 체크리스트</strong></p>
{checklist_items}
    </section>"""

    def _content_angle_sections(self, *, content_type: str) -> str:
        if content_type == "consumer_warning":
            return """    <h2>문제 상황</h2>
    <p>환불, 배송 중단, 결제 취소 문제는 처음에는 단순 지연처럼 보인다. 하지만 시간이 지나면 주문번호, 결제 승인 내역, 고객센터 답변 기록이 손해를 줄이는 기준이 된다.</p>
    <h2>소비자가 늦게 확인하는 지점</h2>
    <p>가장 늦게 보는 것은 증빙이다. 화면 캡처, 결제내역, 문자 알림, 고객센터 접수 번호가 없으면 같은 말을 반복해야 하고 처리 순서도 늦어진다.</p>
    <h2>바로 남길 기록</h2>
    <p>주문 화면, 결제 금액, 취소 요청 시간, 고객센터 대화, 환불 예정일을 한곳에 모아둔다. 분쟁이 길어질수록 기억보다 기록이 더 강하다.</p>"""
        if content_type == "policy_deadline":
            return """    <h2>마감이 중요한 이유</h2>
    <p>지원금은 금액보다 신청 마감과 대상 조건이 먼저다. 같은 청년 지원금이라도 소득 기준, 거주 요건, 필요 서류, 중복 지원 제한에 따라 결과가 달라진다.</p>
    <h2>신청 전 확인할 항목</h2>
    <p>공식 신청 페이지에서 사업명, 접수 기관, 신청 기간, 필요 서류를 확인한다. 비슷한 이름의 지원사업을 혼동하면 받을 수 있는 지원을 놓칠 수 있다.</p>
    <h2>놓치면 다시 못 받을 수 있는 항목</h2>
    <p>마감일, 소득 기준, 증빙 서류 발급 기간, 중복 지원 여부는 뒤늦게 고치기 어렵다. 신청 전에 체크리스트로 한 번에 확인해야 한다.</p>"""
        if content_type == "ai_work_tip":
            return """    <h2>기능 변화보다 업무 방식 변화</h2>
    <p>AI 도구가 바뀌면 새 기능보다 업무 기준이 먼저 바뀐다. 무엇을 자동화하고 무엇을 사람이 확인할지 정하지 않으면 오히려 검토와 재작업이 늘 수 있다.</p>
    <h2>직장인이 바로 확인할 것</h2>
    <p>반복 작성, 요약, 분류는 자동화 후보가 될 수 있다. 다만 고객 정보, 회사 내부 자료, 최종 판단이 필요한 업무는 검토 기준을 먼저 세워야 한다.</p>
    <h2>줄어드는 일과 늘어나는 일</h2>
    <p>초안 작성 시간은 줄어도 사실 확인, 보안 검토, 결과 편집은 늘 수 있다. AI는 시간을 없애는 도구가 아니라 일의 순서를 바꾸는 도구에 가깝다.</p>"""
        if content_type == "trend_decode":
            return """    <h2>왜 뜨는지</h2>
    <p>유행은 품질만으로 움직이지 않는다. 인증샷, 희소성, 줄 서는 경험, 남들이 샀다는 신호가 가격과 관심을 함께 끌어올린다.</p>
    <h2>가격 착시가 생기는 지점</h2>
    <p>한정판, 품절, 오픈런이라는 말이 붙으면 원래 가격보다 지금 사야 한다는 압박이 커진다. 실제 만족보다 참여했다는 표시가 더 비싸질 수 있다.</p>
    <h2>따라가기 전 확인할 것</h2>
    <p>일주일 뒤에도 필요할지, 대체재가 있는지, 인증 목적이 사라져도 만족할지 확인한다. 오래갈 유행인지 보는 기준은 반복 구매 의사다.</p>"""
        if content_type == "viral_issue_decode":
            return """    <h2>왜 사람들이 클릭하는가</h2>
    <p>반응이 갈리는 이슈는 공감과 논쟁을 동시에 만든다. 기대치와 실제 결과의 차이, 또는 해석 기준이 달라지면 빠르게 퍼진다.</p>
    <h2>반응이 갈린 포인트</h2>
    <p>호평 측은 기대 이상의 결과에 주목하고, 비판 측은 구조적 한계를 지적한다. 중간 독자는 배경 맥락을 먼저 확인한다.</p>
    <h2>플랫폼·팬덤·소비 구조 해석</h2>
    <p>단순 감상이 아니라 팬덤 소비, OTT 전략, 플랫폼 알고리즘, 티켓팅 구조로 연결해 보면 패턴이 보인다.</p>"""
        if content_type == "platform_change":
            return """    <h2>서비스 변경이 불편을 만드는 이유</h2>
    <p>플랫폼 변경이나 종료는 공지보다 내 사용 환경에서 먼저 문제가 된다. 계정, 기기, 결제, 백업이 연결되어 있으면 작은 변경도 불편으로 번진다.</p>
    <h2>내가 받을 영향</h2>
    <p>자동결제, 저장 데이터, 로그인 기기, 알림 설정, 백업 상태를 확인해야 한다. 특히 서비스 종료나 정책 변경은 뒤늦게 알면 복구 시간이 길어진다.</p>
    <h2>오늘 확인할 체크리스트</h2>
    <p>공지 원문, 종료일, 대체 서비스, 환불 조건, 데이터 백업 가능 여부를 확인한다. 결제가 걸린 서비스라면 자동결제 상태를 먼저 본다.</p>"""
        return """    <h2>먼저 확인할 것</h2>
    <p>이슈의 핵심은 반응보다 내 생활에 미치는 영향이다. 비용, 시간, 계정, 신청 조건처럼 직접 바뀌는 항목을 먼저 봐야 한다.</p>"""

    def _generate_timeline_context_html(
        self,
        *,
        title: str,
        display_topic: str,
        labels_text: str,
        content_angle: dict[str, Any],
        hashtags: list[str] | None = None,
    ) -> str:
        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "오늘 이슈")
        reader_question = self._safe_text(
            str(content_angle.get("reader_question") or f"{safe_display_topic}에서 지금 확인된 내용은 무엇일까?")
        )
        reader_loss = self._safe_text(
            str(content_angle.get("reader_loss") or "초기 반응만 보면 사실, 주장, 해석이 한 덩어리로 섞일 수 있다.")
        )
        practical_value = self._safe_text(
            str(content_angle.get("practical_value") or "확인된 사실, 아직 확인할 쟁점, 다음 관전 포인트를 분리한다.")
        )
        meta_description = (
            f"{safe_display_topic}에서 확인된 내용과 아직 단정하기 어려운 쟁점, "
            "오늘 이슈가 된 이유와 다음 관전 포인트를 정리했습니다."
        )
        faq_items = self._faq_items_for_content_type("today_issue_explainer")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        visual_css = self._visual_css()
        hero_html = self._hero_summary_box(
            content_type="today_issue_explainer",
            topic=safe_display_topic,
            reader_question=reader_question,
            reader_loss=reader_loss,
            practical_value=practical_value,
        )
        target_reader_html = self._target_reader_box_html(content_type="today_issue_explainer", topic=safe_display_topic)
        core_message_html = self._core_message_box_html(content_type="today_issue_explainer", topic=safe_display_topic)
        yomi_judgment_html = self._yomi_judgment_box_html("today_issue_explainer", safe_display_topic)
        key_fact_cards_html = self._key_fact_cards_html(content_type="today_issue_explainer", topic=safe_display_topic)
        misconception_html = self._misconception_box_html("today_issue_explainer", safe_display_topic)
        quick_decision_html = self._quick_decision_table_html("today_issue_explainer", safe_display_topic)
        warning_html = self._type_warning_box_html("today_issue_explainer")
        action_guide_html = self._action_guide_html("today_issue_explainer")
        hashtag_html = self._hashtag_box_html(
            hashtags or self._hashtags_from_raw({}, labels_text, "today_issue_explainer", safe_display_topic)
        )
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
{visual_css}
  </style>
</head>
<body>
  <article class="wrap visual-article variant-timeline">
    <h1>{title}</h1>
    <p class="meta">카테고리: AI뉴스해석 · 유형: today_issue_explainer · 기준일: {today}</p>
{hero_html}
{target_reader_html}
{core_message_html}
{yomi_judgment_html}
{key_fact_cards_html}
{misconception_html}
{quick_decision_html}
    <section class="body-section">
      <h2>핵심은 결론보다 분리입니다</h2>
      <p>{escape(safe_display_topic)}을 볼 때 가장 먼저 할 일은 빠른 판단이 아닙니다. 확인된 사실, 당사자 입장, 아직 확인 중인 주장, 커뮤니티 해석을 서로 다른 층으로 나누는 것입니다.</p>
      <p>{escape(reader_question)} 이 질문에 답하려면 오늘 나온 말 전체를 한 문장으로 압축하기보다, 어떤 정보가 이미 공개됐고 어떤 정보가 후속 확인을 기다리는지 먼저 봐야 합니다.</p>

      <h2>오늘 이슈가 된 이유</h2>
      <p>이슈는 사건 자체만으로 커지지 않습니다. 공개 시점, 이해관계, 기존 기대치, 온라인 확산 경로가 겹칠 때 같은 소식도 더 크게 보입니다. 그래서 오늘의 관심은 '새로운 사실'과 '새롭게 붙은 의미'를 함께 봐야 이해됩니다.</p>

      <div class="checklist-box">
        <p class="checklist-title">확인 순서 체크리스트</p>
        <ul>
          <li>첫째, 현재 공개된 사실과 인용 가능한 발언을 분리합니다.</li>
          <li>둘째, 아직 확인이 필요한 주장과 해석을 따로 표시합니다.</li>
          <li>셋째, 후속 발표가 나오면 바뀔 수 있는 결론을 성급히 고정하지 않습니다.</li>
        </ul>
      </div>

      <h2>다른 관점에서 보면 보이는 것</h2>
      <div class="info-table-wrap">
        <table class="info-table">
          <thead><tr><th>관점</th><th>볼 지점</th><th>오해하기 쉬운 부분</th></tr></thead>
          <tbody>
            <tr><td>사실관계</td><td>공개된 내용, 날짜, 당사자 입장</td><td>초기 보도와 최종 결론을 같은 것으로 보는 것</td></tr>
            <tr><td>확산 구조</td><td>왜 오늘 관심이 몰렸는지</td><td>많이 공유됐다는 이유로 사실성을 높게 보는 것</td></tr>
            <tr><td>독자 영향</td><td>생활, 소비, 관심사에 실제 변화가 있는지</td><td>나와 무관한 해석까지 불안으로 받아들이는 것</td></tr>
          </tbody>
        </table>
      </div>

      <h2>독자 상황 예시</h2>
      <p>예를 들어 어떤 발표가 나왔을 때, 제목만 보면 이미 결론이 난 것처럼 보일 수 있습니다. 하지만 본문을 보면 확정된 부분은 제한적이고, 나머지는 반응과 전망일 때가 많습니다.</p>
      <p>{escape(reader_loss)} 그래서 이 글은 결론을 대신 정해주기보다, 독자가 흔들리지 않고 읽을 순서를 제공합니다.</p>

      <h2>다음 관전 포인트</h2>
      <p>다음에 볼 것은 새로운 주장보다 확인 가능한 변화입니다. 후속 발표, 정정 보도, 관련 기관 또는 당사자 입장, 실제 영향이 생기는 시점이 나오면 이 이슈의 무게는 달라질 수 있습니다.</p>
    </section>
{warning_html}
{faq_html}
{action_guide_html}
    <section class="guide">
      <p><strong>관련 키워드</strong></p>
      <p>{labels_text}</p>
    </section>
{hashtag_html}
  </article>
</body>
</html>"""

    def _generate_viral_issue_html(
        self,
        *,
        title: str,
        display_topic: str,
        labels_text: str,
        content_angle: dict[str, Any],
        hashtags: list[str] | None = None,
    ) -> str:
        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "오늘 이슈")
        reader_question = self._safe_text(str(content_angle.get("reader_question") or f"{safe_display_topic} 반응이 왜 갈렸을까?"))
        reader_loss = self._safe_text(str(content_angle.get("reader_loss") or "반응 구조를 모르면 다음 포인트를 놓칠 수 있다."))
        practical_value = self._safe_text(str(content_angle.get("practical_value") or "이슈 해석, 반응 포인트, 팬덤·플랫폼·소비 구조를 정리한다."))
        meta_description = f"{safe_display_topic} 반응이 갈린 이유와 팬덤·플랫폼·소비 구조 해석. 공식 콘텐츠 기반으로 클릭 이유와 다음 포인트를 정리한다."
        faq_items = self._faq_items_for_content_type("viral_issue_decode")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        evergreen_links = list(content_angle.get("evergreen_link_suggestions") or ["관련 생활 선택 기준 가이드"])
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        visual_css = self._visual_css()
        hero_html = self._hero_summary_box(
            content_type="viral_issue_decode",
            topic=safe_display_topic,
            reader_question=reader_question,
            reader_loss=reader_loss,
            practical_value=practical_value,
        )
        target_reader_html = self._target_reader_box_html(content_type="viral_issue_decode", topic=safe_display_topic)
        core_message_html = self._core_message_box_html(content_type="viral_issue_decode", topic=safe_display_topic)
        yomi_judgment_html = self._yomi_judgment_box_html("viral_issue_decode", safe_display_topic)
        key_fact_cards_html = self._key_fact_cards_html(content_type="viral_issue_decode", topic=safe_display_topic)
        misconception_html = self._misconception_box_html("viral_issue_decode", safe_display_topic)
        quick_decision_html = self._quick_decision_table_html("viral_issue_decode", safe_display_topic)
        warning_html = self._type_warning_box_html("viral_issue_decode")
        action_guide_html = self._action_guide_html("viral_issue_decode")
        hashtag_html = self._hashtag_box_html(hashtags or self._hashtags_from_raw({}, labels_text, "viral_issue_decode", safe_display_topic))
        naver_blog_html = self._naver_blog_box_html("viral_issue_decode", self._naver_blog_url())
        evergreen_html = "".join(f'      <li>{escape(s)}</li>\n' for s in evergreen_links)
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
{visual_css}
  </style>
</head>
<body>
  <article class="wrap visual-article variant-viral">
    <h1>{title}</h1>
    <p class="meta">카테고리: 연예·스포츠·OTT · 유형: viral_issue_decode · 기준일: {today}</p>
{hero_html}
{target_reader_html}
{core_message_html}
{yomi_judgment_html}
{key_fact_cards_html}
{misconception_html}
{quick_decision_html}
    <section class="body-section">
      <h2>왜 사람들이 클릭하는가</h2>
      <p>{escape(safe_display_topic)} 이슈는 공감과 논쟁을 동시에 만든다. 기대치와 실제 결과의 차이, 또는 해석 기준이 달라지면 빠르게 퍼진다.</p>
      <h2>반응이 갈린 포인트 3가지</h2>
      <div class="checklist-box">
        <p class="checklist-title">체크리스트 — 반응 구조</p>
        <ul>
          <li>호평 측: 기대 이상의 결과 또는 새로운 시도에 주목</li>
          <li>비판 측: 구조적 한계 또는 기대와 다른 결과 지적</li>
          <li>중간 독자: 배경 맥락과 다음 포인트 확인</li>
        </ul>
      </div>
      <h2>돈·플랫폼·팬덤·콘텐츠 구조 해석</h2>
      <p>단순 감상이 아니라 팬덤 소비, OTT 전략, 플랫폼 알고리즘, 티켓팅 구조로 연결해 보면 반복 패턴이 보인다. 이 구조를 알면 다음 이슈도 미리 예측할 수 있다.</p>
      <h2>독자가 볼 다음 포인트</h2>
      <p>이 이슈의 다음 단계는 팬덤 소비 변화, OTT 플랫폼 대응, 또는 커뮤니티 반응 흐름에서 나온다. 아래 관련 가이드에서 더 깊이 확인할 수 있다.</p>
      <div class="key-fact-cards">
        <p class="key-fact-title">🔗 관련 evergreen 내부링크 후보</p>
        <ul>
{evergreen_html}        </ul>
      </div>
    </section>
{warning_html}
{faq_html}
{action_guide_html}
{naver_blog_html}
{hashtag_html}
  </article>
</body>
</html>"""

    def _generate_money_checklist_html(
        self,
        *,
        title: str,
        display_topic: str,
        labels_text: str,
        content_angle: dict[str, Any],
        hashtags: list[str] | None = None,
    ) -> str:
        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "배달앱 결제금액")
        meta_description = (
            "무료배달과 쿠폰이 있어도 최종 결제금액은 달라질 수 있다. 최소주문금액, 쿠폰 조건, 메뉴 가격 차이, "
            "직접 주문 가격을 비교하는 실전 체크리스트를 정리한다."
        )
        faq_items = self._faq_items_for_content_type("money_checklist")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        variant = self._template_variant(safe_display_topic, "money_checklist")
        visual_css = self._visual_css()
        hero_html = self._hero_summary_box(
            content_type="money_checklist",
            topic=safe_display_topic,
            reader_question="결제 전 어떤 조건을 비교해야 실제로 더 저렴할까?",
            reader_loss="쿠폰, 수수료, 최소 조건을 놓치면 할인받고도 더 낼 수 있다.",
            practical_value="최종 결제금액을 비교하는 기준과 체크 순서를 얻는다.",
        )
        key_fact_cards_html = self._key_fact_cards_html(content_type="money_checklist", topic=safe_display_topic)
        target_reader_html = self._target_reader_box_html(content_type="money_checklist", topic=safe_display_topic)
        core_message_html = self._core_message_box_html(content_type="money_checklist", topic=safe_display_topic)
        yomi_judgment_html = self._yomi_judgment_box_html("money_checklist", safe_display_topic)
        misconception_html = self._misconception_box_html("money_checklist", safe_display_topic)
        quick_decision_html = self._quick_decision_table_html("money_checklist", safe_display_topic)
        compare_table_html = self._money_compare_table_html()
        warning_html = self._type_warning_box_html("money_checklist")
        action_guide_html = self._action_guide_html("money_checklist")
        hashtag_html = self._hashtag_box_html(hashtags or self._hashtags_from_raw({}, labels_text, "money_checklist", safe_display_topic))
        naver_blog_html = self._naver_blog_box_html("money_checklist", self._naver_blog_url())
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
{visual_css}
  </style>
</head>
<body>
  <article class="wrap visual-article variant-{variant}">
    <h1>{title}</h1>
    <p class="meta">카테고리: 생활비 · 유형: money_checklist · 기준일: {today}</p>
{hero_html}
{target_reader_html}
{core_message_html}
{yomi_judgment_html}
{key_fact_cards_html}
{misconception_html}
{quick_decision_html}

    <p>무료배달, 쿠폰, 배달비를 따로 보면 싸 보인다. 그런데 결제 버튼 앞에서 중요한 숫자는 하나다. 바로 최종 결제금액이다.</p>
    <p>{safe_display_topic}은 라이더가 얼마를 받느냐의 논쟁으로만 보면 내 생활과 멀어진다. 독자에게 필요한 질문은 "오늘 같은 메뉴를 어디서 시켜야 덜 쓰는가"다.</p>

    <section class="summary">
      <p><strong>핵심 요약</strong></p>
      <p>1) 무료배달 문구보다 최종 결제금액을 먼저 본다.</p>
      <p>2) 최소주문금액 때문에 필요 없는 메뉴를 추가하면 할인은 사라진다.</p>
      <p>3) 쿠폰 조건은 적용 전 금액과 적용 후 금액을 나눠서 봐야 한다.</p>
    </section>
{compare_table_html}

    <section class="example">
      <p><strong>가상의 계산 예시</strong></p>
      <p>A앱: 메뉴 18,000원 + 배달비 3,000원 - 쿠폰 2,000원 = 최종 결제금액 19,000원</p>
      <p>B앱: 메뉴 20,000원 + 무료배달 = 최종 결제금액 20,000원</p>
      <p>직접 주문: 메뉴 18,000원, 배달비와 앱 쿠폰 없음</p>
      <p>결론: 무료배달 문구보다 최종 결제금액을 비교해야 한다. 쿠폰이 있어도 메뉴 가격이 오르면 더 비쌀 수 있다.</p>
    </section>

{warning_html}
    <h2>사람들이 놓치는 함정</h2>
    <p>첫째는 최소주문금액이다. 15,000원만 먹고 싶은데 19,000원을 채워야 무료배달이 된다면 이미 4,000원을 더 쓰는 구조다.</p>
    <p>둘째는 쿠폰 적용 조건이다. 특정 카드, 특정 시간, 특정 가게, 일정 금액 이상 같은 조건이 붙으면 실제 할인은 생각보다 좁다.</p>
    <p>셋째는 메뉴 가격 차이다. 같은 메뉴라도 앱마다 메뉴 가격이 다를 수 있고, 직접 주문 가격과 앱 주문 가격이 다를 수 있다.</p>
    <p>넷째는 배달비 별도 표기다. 메뉴가 싸 보여도 마지막 결제창에서 배달비와 서비스 비용이 붙으면 최종 결제금액이 바뀐다.</p>

    <h2>오늘 바로 할 체크리스트</h2>
    <section class="guide">
      <p>1) 같은 메뉴를 최소 2개 앱에서 장바구니까지 담고 최종 결제금액을 비교한다.</p>
      <p>2) 쿠폰 적용 전 금액과 적용 후 금액을 따로 본다.</p>
      <p>3) 무료배달의 최소주문금액 때문에 추가한 메뉴가 있는지 확인한다.</p>
      <p>4) 자주 시키는 가게는 직접 주문 가격이나 포장 가격도 한 번 확인한다.</p>
    </section>

    <p>배달료 논란은 남의 이야기가 아니라 내 결제창의 숫자 문제다. 오늘 아낄 수 있는 돈은 논쟁 댓글이 아니라 마지막 결제금액 비교에서 나온다.</p>
{action_guide_html}
{faq_html}

    <section class="guide">
      <p><strong>관련 키워드</strong></p>
      <p>{labels_text}</p>
    </section>
{naver_blog_html}
{hashtag_html}
  </article>
</body>
</html>"""

    def _generate_policy_benefit_html(self, *, title: str, display_topic: str, labels_text: str) -> str:
        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "지원금 신청 마감")
        meta_description = (
            "지원금 이슈의 핵심은 금액만이 아니다. 신청 마감, 대상 조건, 소득 기준, 필요 서류, "
            "중복 지원 여부를 공식 신청 페이지에서 확인해야 받을 수 있는 지원을 놓치지 않는다."
        )
        faq_items = self._faq_items_for_content_type("policy_deadline")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        naver_blog_html = self._naver_blog_box_html("policy_benefit", self._naver_blog_url())
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #F7F7F8;
      color: #1A1A1B;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Arial, sans-serif;
      line-height: 1.75;
      font-size: 16px;
    }}
    .wrap {{
      max-width: 780px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 22px 18px 40px;
    }}
    h1 {{
      margin: 0 0 16px;
      font-size: 30px;
      line-height: 1.35;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    h2 {{
      margin: 34px 0 12px;
      font-size: 22px;
      line-height: 1.4;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    p {{
      margin: 0 0 14px;
      word-break: keep-all;
    }}
    .meta {{
      color: #666;
      font-size: 14px;
      margin-bottom: 18px;
    }}
    .callout {{
      background: #FFF4F3;
      border-left: 4px solid #FF3B30;
      padding: 16px 16px 12px;
      border-radius: 8px;
      margin: 20px 0;
    }}
    .guide {{
      margin: 22px 0;
      padding: 16px;
      border: 1px solid #DDE6F7;
      border-radius: 10px;
      background: #F7FAFF;
    }}
    .subscribe {{
      margin: 24px 0 0;
      padding: 18px 16px;
      border-radius: 10px;
      border: 1px solid #EFEFEF;
      background: #FAFAFA;
    }}
    .faq {{
      margin: 28px 0;
      padding: 18px 16px;
      border: 1px solid #E5E7EB;
      border-radius: 10px;
      background: #FFFFFF;
    }}
    .faq h3 {{
      margin: 18px 0 8px;
      font-size: 18px;
      line-height: 1.45;
      word-break: keep-all;
    }}
    .related-ai-blog-box {{ margin: 24px 0; padding: 18px; border: 1px solid #BBF7D0; border-left: 4px solid #10B981; border-radius: 12px; background: #F0FDF4; }}
    .related-ai-blog-box h2 {{ margin: 0 0 10px; font-size: 18px; color: #065F46; }}
    .related-ai-blog-box p {{ margin: 0 0 10px; color: #134E4A; }}
    .related-ai-blog-box a {{ display: inline-block; margin-top: 6px; padding: 9px 18px; background: #10B981; color: #FFFFFF; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 15px; }}
  </style>
</head>
<body>
  <article class="wrap">
    <h1>{title}</h1>
    <p class="meta">카테고리: AI활용 · 유형: policy_benefit · 기준일: {today}</p>

    <p>{safe_display_topic}은 단순히 돈을 준다는 이야기가 아니라 대상 조건, 신청 기간, 증빙 기준에서 갈리는 문제다. 핵심은 누가 받을 수 있느냐보다, 내가 조건을 놓치지 않았는지 확인하는 것이다.</p>
    <p>특히 청년 지원금이나 정부 지원 사업은 이름이 비슷해도 소득 기준, 거주 요건, 신청 마감, 필요 서류가 다르면 결과가 달라진다. 환급 성격의 사업인지, 새로 신청해야 하는 지원금인지도 먼저 구분해야 한다.</p>

    <section class="callout">
      <p><strong>먼저 볼 부분</strong></p>
      <p>금액보다 중요한 것은 공식 신청 페이지에 적힌 대상 조건과 신청 기간이다. 마감일만 보고 움직이면 소득 기준, 필요 서류, 중복 지원 제한을 놓칠 수 있다.</p>
    </section>

    <h2>표면의 이야기</h2>
    <p>사람들은 지원금 액수나 신청 마감을 먼저 본다. 하지만 실제 신청 단계에서는 청년 여부, 연령 기준, 주소지, 소득 기준, 기존 수급 이력 같은 항목이 먼저 걸러진다. 그래서 같은 지원금 안내를 봐도 받을 수 있는 사람과 받을 수 없는 사람이 나뉜다.</p>

    <h2>놓친 이면</h2>
    <p>실제로는 대상 조건, 소득 기준, 신청 기간, 필요 서류, 중복 지원 여부가 핵심이다. 비슷한 이름의 지원사업이라도 지방자치단체 사업인지, 중앙정부 사업인지, 환급 방식인지에 따라 확인해야 할 서류와 접수 경로가 달라진다.</p>

    <h2>독자에게 생기는 영향</h2>
    <p>조건 하나를 놓치면 받을 수 있는 지원을 놓칠 수 있다. 청년 대상 사업은 나이와 소득 기준이 함께 붙는 경우가 많고, 자영업자나 소상공인 지원은 매출 증빙과 사업자 상태가 중요하다. 중복 지원 제한이 있으면 이미 받은 지원금 때문에 새 신청이 막힐 수도 있다.</p>

    <h2>선택 기준</h2>
    <section class="guide">
      <p><strong>신청 전 체크리스트</strong></p>
      <p>1) 공식 신청 페이지에서 사업명과 접수 기관을 확인한다.</p>
      <p>2) 대상 조건, 소득 기준, 연령 기준, 거주 요건을 따로 체크한다.</p>
      <p>3) 신청 마감과 필요 서류를 캘린더에 적고, 중복 지원 제한을 확인한다.</p>
      <p>4) 비슷한 이름의 지원사업을 혼동하지 않도록 신청 링크와 공고 번호를 다시 본다.</p>
    </section>

    <p>{safe_display_topic}을 볼 때는 "받을 수 있다"는 문구보다 "어떤 조건이면 제외되는가"를 먼저 봐야 한다. 지원금, 신청, 마감, 대상 조건, 소득 기준, 필요 서류, 중복 지원, 공식 신청 페이지를 한 번에 확인해야 실제로 놓치지 않는다.</p>
{faq_html}

    <section class="subscribe">
      <p><strong>관련 키워드</strong></p>
      <p>{labels_text}</p>
    </section>
{naver_blog_html}
  </article>
</body>
</html>"""

    def _generate_delivery_money_html(self, *, title: str, display_topic: str, labels_text: str) -> str:
        today = date.today().isoformat()
        safe_display_topic = self._safe_text(display_topic or "배달료 논란")
        meta_description = (
            "배달료 논란의 핵심은 라이더 비용만이 아니다. 무료배달, 쿠폰, 최소주문금액, "
            "수수료가 최종 결제금액으로 이동하는 구조를 짚는다."
        )
        faq_items = self._faq_items_for_content_type("money_checklist")
        faq_html = self._faq_html(faq_items)
        faq_json_ld = self._faq_json_ld(faq_items)
        naver_blog_html = self._naver_blog_box_html("money_checklist", self._naver_blog_url())
        json_ld = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._plain_text(title),
            "description": meta_description,
            "author": {"@type": "Person", "name": _BLOG_AUTHOR_NAME},
            "datePublished": today,
            "dateModified": today,
            "publisher": {"@type": "Organization", "name": _BLOG_BRAND_NAME, "url": BLOGSPOT_HOME_URL.rstrip("/")},
            "inLanguage": "ko",
            "keywords": labels_text,
        }
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{escape(meta_description)}">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{faq_json_ld}</script>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #F7F7F8;
      color: #1A1A1B;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Arial, sans-serif;
      line-height: 1.75;
      font-size: 16px;
    }}
    .wrap {{
      max-width: 780px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 22px 18px 40px;
    }}
    h1 {{
      margin: 0 0 16px;
      font-size: 30px;
      line-height: 1.35;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    h2 {{
      margin: 34px 0 12px;
      font-size: 22px;
      line-height: 1.4;
      color: #1A1A1B;
      word-break: keep-all;
    }}
    p {{
      margin: 0 0 14px;
      word-break: keep-all;
    }}
    .meta {{
      color: #666;
      font-size: 14px;
      margin-bottom: 18px;
    }}
    .callout {{
      background: #FFF4F3;
      border-left: 4px solid #FF3B30;
      padding: 16px 16px 12px;
      border-radius: 8px;
      margin: 20px 0;
    }}
    .guide {{
      margin: 22px 0;
      padding: 16px;
      border: 1px solid #DDE6F7;
      border-radius: 10px;
      background: #F7FAFF;
    }}
    .subscribe {{
      margin: 24px 0 0;
      padding: 18px 16px;
      border-radius: 10px;
      border: 1px solid #EFEFEF;
      background: #FAFAFA;
    }}
    .faq {{
      margin: 28px 0;
      padding: 18px 16px;
      border: 1px solid #E5E7EB;
      border-radius: 10px;
      background: #FFFFFF;
    }}
    .faq h3 {{
      margin: 18px 0 8px;
      font-size: 18px;
      line-height: 1.45;
      word-break: keep-all;
    }}
    .related-ai-blog-box {{ margin: 24px 0; padding: 18px; border: 1px solid #BBF7D0; border-left: 4px solid #10B981; border-radius: 12px; background: #F0FDF4; }}
    .related-ai-blog-box h2 {{ margin: 0 0 10px; font-size: 18px; color: #065F46; }}
    .related-ai-blog-box p {{ margin: 0 0 10px; color: #134E4A; }}
    .related-ai-blog-box a {{ display: inline-block; margin-top: 6px; padding: 9px 18px; background: #10B981; color: #FFFFFF; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 15px; }}
  </style>
</head>
<body>
  <article class="wrap">
    <h1>{title}</h1>
    <p class="meta">카테고리: 생활비 · 유형: delivery_money · 기준일: {today}</p>

    <p>{safe_display_topic}은 단순히 라이더 비용 문제가 아니라 소비자 결제금액, 자영업자 수수료, 플랫폼 쿠폰 정책이 한 번에 얽힌 문제다.</p>
    <p>핵심은 누가 더 받느냐보다, 비용이 어떤 이름으로 이동하느냐다. 배달료가 오르는 것처럼 보이는 순간에도 실제 부담은 메뉴 가격, 배달비, 쿠폰 조건, 무료배달 기준, 최소주문금액으로 나뉘어 표시된다.</p>

    <section class="callout">
      <p><strong>핵심 요약</strong></p>
      <p>소비자는 쿠폰 금액보다 최종 결제금액을 봐야 하고, 자영업자는 수수료와 광고비가 주문당 이익을 얼마나 줄이는지 확인해야 한다. 라이더는 단건 수익과 이동 거리 기준이 맞지 않으면 같은 배달료라도 체감 수익이 달라진다.</p>
    </section>

    <h2>표면의 이야기</h2>
    <p>먼저 눈에 들어오는 것은 라이더 수락 금액, 배달료, 무료배달 문구다. 소비자는 앱 화면에서 배달비가 얼마인지 보고, 자영업자는 플랫폼 수수료와 광고비를 보고, 라이더는 한 건을 수행했을 때 남는 금액과 이동 거리를 본다.</p>
    <p>그래서 배달료 논란은 한쪽의 불만으로만 설명하기 어렵다. 같은 주문이라도 소비자 화면에는 쿠폰과 무료배달이 보이고, 매장 화면에는 수수료와 광고비가 보이며, 라이더에게는 거리와 대기 시간이 보인다.</p>

    <h2>놓친 이면</h2>
    <p>실제 비용은 메뉴 가격, 배달비, 최소주문금액, 쿠폰 조건, 광고비, 수수료가 합쳐진 최종 결제금액에서 드러난다. 무료배달이라고 표시돼도 최소주문금액이 높아졌거나 쿠폰 조건이 좁아졌다면 소비자가 내는 총액은 줄지 않을 수 있다.</p>
    <p>자영업자에게도 계산은 단순하지 않다. 플랫폼 수수료와 광고비가 커지면 메뉴 가격을 조정하거나 쿠폰을 줄이거나 직접 주문을 유도할 수밖에 없다. 그 변화는 다시 소비자의 최종 결제금액으로 이동한다.</p>

    <h2>독자에게 생기는 영향</h2>
    <p>소비자는 쿠폰보다 최종 결제금액을 기준으로 봐야 한다. 같은 메뉴라도 배달앱별 배달료, 무료배달 기준, 최소주문금액, 쿠폰 적용 조건이 다르면 실제 지출은 달라진다.</p>
    <p>자영업자는 주문 수만 볼 것이 아니라 수수료와 광고비를 뺀 주문당 이익을 봐야 한다. 라이더는 단건 수익뿐 아니라 이동 거리, 대기 시간, 배차 조건을 함께 봐야 한다. 이 세 기준이 어긋날 때 배달료 논란은 반복된다.</p>

    <h2>선택 기준</h2>
    <section class="guide">
      <p><strong>주문 전 확인할 것</strong></p>
      <p>1) 같은 메뉴를 2개 배달앱에서 최종 결제금액 기준으로 비교한다.</p>
      <p>2) 무료배달 문구보다 최소주문금액과 배달비가 함께 바뀌었는지 확인한다.</p>
      <p>3) 쿠폰 적용 전 총액과 적용 후 총액을 나눠서 본다.</p>
      <p>4) 자주 쓰는 매장은 직접 주문 가격과 배달앱 가격 차이를 한 번씩 비교한다.</p>
    </section>

    <p>결국 {safe_display_topic}에서 독자가 볼 지점은 하나다. 할인처럼 보이는 금액이 실제로는 어디에서 다시 붙는지 확인해야 한다. 배달료, 쿠폰, 무료배달, 최소주문금액, 수수료를 따로 보면 싸 보일 수 있지만, 최종 결제금액으로 합치면 판단이 달라질 수 있다.</p>
{faq_html}

    <section class="subscribe">
      <p><strong>계속 볼 키워드</strong></p>
      <p>{labels_text}</p>
    </section>
{naver_blog_html}
  </article>
</body>
</html>"""

    def _build_body(
        self,
        *,
        topic: str,
        display_topic: str,
        title: str,
        category: str,
        profile: dict[str, Any],
        labels_text: str,
    ) -> str:
        today = date.today().isoformat()
        pattern_name = profile.get("pattern", "DEFAULT_CONTRARIAN")
        pattern = _PATTERNS.get(pattern_name, _PATTERNS["DEFAULT_CONTRARIAN"])

        # -- 결정적 변이 인덱스 (topic 기반) --
        vi = self._topic_hash(topic, 60)

        # -- 도입 hook 선택 --
        preferred = pattern["preferred_hooks"]
        hook_key = preferred[vi % len(preferred)]
        hook_openers = profile.get("hook_openers", {})
        hook_opener = hook_openers.get(hook_key, "")

        p1 = profile.get("body_p1", "")
        p2 = profile.get("body_p2", "")
        p3 = profile.get("body_p3", "")

        # echo 문단 — profile별 강한 문장, 없으면 생략
        echo_note = ""
        echo_pool = profile.get("echo_sentences")
        if echo_pool:
            echo_note = f"<p>{self._safe_text(echo_pool[vi % len(echo_pool)])}</p>\n    "

        # -- 섹션 제목 선택 --
        st = pattern["section_titles"]
        s_titles = [pool[vi % len(pool)] for pool in st]

        # -- callout / guide 제목 선택 --
        callout_title = pattern["callout_titles"][vi % len(pattern["callout_titles"])]
        guide_title = pattern["guide_titles"][vi % len(pattern["guide_titles"])]

        # -- subscribe 변형 --
        sub_variants = pattern["subscribe_variants"]
        subscribe_text = sub_variants[vi % len(sub_variants)]

        # -- blockquote 위치 (section 2 뒤 또는 section 3 뒤) --
        bq_after = pattern["blockquote_after"]

        # -- 컴포넌트 내용 --
        callout_fact = self._safe_text(profile.get("callout_fact", topic))
        callout_hidden = self._safe_text(profile.get("callout_hidden", ""))
        callout_action = self._safe_text(profile.get("callout_action", ""))

        section1 = self._safe_html(self._pick_variant(profile.get("section1_body", ""), vi))
        section2 = self._safe_html(self._pick_variant(profile.get("section2_body", ""), vi))
        blockquote_text = self._safe_text(profile.get("blockquote_text", ""))
        section3 = self._safe_html(self._pick_variant(profile.get("section3_body", ""), vi))

        action_1 = self._safe_text(profile.get("action_1", ""))
        action_2 = self._safe_text(profile.get("action_2", ""))
        action_3 = self._safe_text(profile.get("action_3", ""))

        conclusion = self._safe_text(profile.get("conclusion", ""))
        comment_q = self._safe_text(profile.get("comment_question", ""))

        profile_type = self._safe_text(profile.get("type", "역발상"))

        # -- blockquote HTML --
        bq_html = f"""
    <blockquote>
      {blockquote_text}
    </blockquote>
"""

        # -- 섹션 2+3 조립 (blockquote 위치에 따라) --
        if bq_after == 2:
            mid_sections = f"""
    <h2>{s_titles[1]}</h2>
    <p>{section2}</p>
{bq_html}
    <h2>{s_titles[2]}</h2>
    <p>{section3}</p>
"""
        else:
            mid_sections = f"""
    <h2>{s_titles[1]}</h2>
    <p>{section2}</p>

    <h2>{s_titles[2]}</h2>
    <p>{section3}</p>
{bq_html}"""

        # -- 전체 본문 조립 --
        return f"""    <h1>{title}</h1>
    <p class="meta">📍 카테고리: {category} · 유형: {profile_type} · 기준일: {today}</p>

    <p>{self._safe_text(hook_opener)}</p>
    <p>{self._safe_text(p1)}</p>
    <p>{self._safe_text(p2)}</p>
    <p>{self._safe_text(p3)}</p>
    {echo_note}
    <section class="callout">
      <p><strong>{callout_title}</strong> <span class="data">{callout_fact}</span></p>
      <p><strong>🔍 대중이 모르는 이면:</strong> {callout_hidden}</p>
      <p><strong>✅ 지금 할 행동:</strong> {callout_action}</p>
    </section>

    <h2>{s_titles[0]}</h2>
    <p>{section1}</p>
{mid_sections}
    <h2>{s_titles[3]}</h2>

    <section class="guide">
      <p><strong>{guide_title}</strong></p>
      <p>1) {action_1}</p>
      <p>2) {action_2}</p>
      <p>3) {action_3}</p>
    </section>

    <p>{conclusion}</p>

    <section class="subscribe">
      <p><strong>✅ 이런 시각이 필요했다면</strong></p>
      <p>{self._safe_text(subscribe_text)}</p>
      <p>키워드: {labels_text}</p>
    </section>

    <h2>댓글로 남겨볼 질문</h2>
    <p>{comment_q}</p>"""

    # ================================================================== #
    #  변이 선택 유틸                                                        #
    # ================================================================== #

    @staticmethod
    def _pick_variant(pool: Any, idx: int) -> str:
        """list pool에서 idx % len으로 변이를 결정적으로 선택.
        str이면 그대로 반환. 빈 값이면 빈 문자열 반환."""
        if isinstance(pool, list):
            return pool[idx % len(pool)] if pool else ""
        return pool or ""

    # ================================================================== #
    #  텍스트 정제 유틸                                                      #
    # ================================================================== #

    def _safe_text(self, value: str) -> str:
        cleaned = " ".join((value or "").split()).strip()
        for word in _BLOCKED_WORDS:
            cleaned = cleaned.replace(word, "")
        lower = cleaned.lower()
        for artifact in _RAW_ARTIFACTS:
            if artifact.lower() in lower:
                cleaned = ""
                break
        return escape(" ".join(cleaned.split()))

    def _plain_text(self, value: str) -> str:
        """HTML escape 없이 텍스트만 정제한다. JSON-LD 값에 사용."""
        cleaned = " ".join((value or "").split()).strip()
        for word in _BLOCKED_WORDS:
            cleaned = cleaned.replace(word, "")
        lower = cleaned.lower()
        for artifact in _RAW_ARTIFACTS:
            if artifact.lower() in lower:
                return ""
        return " ".join(cleaned.split())

    def _display_topic(self, topic: str) -> str:
        """본문 표시용 topic 정제."""
        cleaned = " ".join((topic or "").split()).strip()
        if not cleaned:
            return "오늘 이슈"

        if self._is_policy_benefit_topic(cleaned):
            compact = cleaned.replace(" ", "")
            if "청년" in compact and "지원금" in compact and ("신청" in compact or "마감" in compact):
                return "청년 지원금 신청 마감"
            if "청년" in compact and "지원금" in compact and ("대상" in compact or "조건" in compact):
                return "청년 지원금 대상 조건"
            if "교통비" in compact and "지원" in compact:
                return "교통비 지원 신청"
            if "세금" in compact and "환급" in compact:
                return "세금 환급 신청"
            if "소상공인" in compact and "지원" in compact:
                return "소상공인 지원금 신청"
            if "자영업자" in compact and "지원" in compact:
                return "자영업자 지원금 신청"
            if "환급" in compact:
                return "환급 신청 조건"
            if "지원금" in compact and "마감" in compact:
                return "지원금 신청 마감"
            if "지원금" in compact:
                return "지원금 대상 조건"
            return "지원금 신청 마감"

        if self._is_delivery_money_topic(cleaned):
            if "실시간" in cleaned and "배달료" in cleaned and "논란" in cleaned:
                return "실시간 배달료 논란"
            if "배달료" in cleaned and "논란" in cleaned:
                return "배달료 논란"
            if "배달비" in cleaned and "논란" in cleaned:
                return "배달비 논란"
            if "배달앱" in cleaned and "수수료" in cleaned:
                return "배달앱 수수료 논란"
            if "무료배달" in cleaned or "쿠폰" in cleaned:
                return "배달앱 쿠폰 조건"
            return "배달료 논란"

        cleaned = re.split(r"[“”\"'‘’]", cleaned)[0].strip()
        cleaned = re.sub(r"\.\.\..*$", "", cleaned).strip()
        cleaned = re.sub(r"\s*\d+[,\d]*원\s*(돼야|되야|이상|부터).*$", "", cleaned).strip()
        if "," in cleaned:
            head, tail = cleaned.split(",", 1)
            if any(kw in tail for kw in ("?", "!", "불만", "논란", "반응", "화제", "이슈")):
                cleaned = head.strip()
        cleaned = re.split(r"[!?]", cleaned)[0].strip()
        cleaned = cleaned.strip(" ,.-")
        return cleaned or "오늘 이슈"

    @staticmethod
    def _is_delivery_money_topic(text: str) -> bool:
        return is_delivery_money_text(text)

    @staticmethod
    def _is_policy_benefit_topic(text: str) -> bool:
        return is_policy_benefit_text(text)

    @staticmethod
    def _josa(word: str, pair: str) -> str:
        """한글 받침 유무에 따라 조사를 자동 선택한다.

        pair: '을/를' | '은/는' | '이/가' | '과/와'
        """
        josa_map = {
            "을/를": ("을", "를"),
            "은/는": ("은", "는"),
            "이/가": ("이", "가"),
            "과/와": ("과", "와"),
        }
        if pair not in josa_map:
            return pair.split("/")[-1]
        with_batchim, without_batchim = josa_map[pair]
        last_hangul = ""
        for ch in reversed(word):
            if "\uAC00" <= ch <= "\uD7A3":
                last_hangul = ch
                break
        if not last_hangul:
            return without_batchim
        batchim = (ord(last_hangul) - 0xAC00) % 28
        return with_batchim if batchim != 0 else without_batchim

    def _truncate_desc(self, text: str, max_len: int = 160) -> str:
        """문장 단위로 최대 160자 절단."""
        if len(text) <= max_len:
            return text
        window = text[:max_len]
        best = -1
        for punct in ("다.", "요.", "다!", "다?", "한다.", "된다.", "있다."):
            idx = window.rfind(punct)
            if idx > max_len // 2 and idx > best:
                best = idx + len(punct)
        if best > 0:
            return text[:best]
        idx = window.rfind(" ")
        if idx > max_len // 2:
            return text[:idx] + "..."
        return window[: max_len - 3] + "..."

    def _safe_html(self, value: str) -> str:
        """<br> 태그만 허용하고 나머지는 escape."""
        parts = (value or "").split("<br>")
        escaped_parts = [escape(p.strip()) for p in parts]
        return "<br>".join(escaped_parts)
