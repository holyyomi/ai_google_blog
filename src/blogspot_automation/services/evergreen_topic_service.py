from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from blogspot_automation.models.news_models import NewsCandidate


@dataclass(frozen=True, slots=True)
class EvergreenTopic:
    topic: str
    category: str
    summary: str
    evergreen_axis: str
    evergreen_reason: str
    search_demand_topic: str
    reader_search_questions: tuple[str, str, str]
    click_reason: str
    reader_benefit: str
    urgency_reason: str
    content_promise: str
    angle_type: str
    topic_group: str
    content_type: str


class EvergreenTopicService:
    """Build publishable evergreen candidates for weak-news days."""

    WEEKDAY_AXIS = {
        0: "adsense_revenue",
        1: "ai_automation",
        2: "money_life",
        3: "digital_survival",
        4: "tax_refund_support",
        5: "blogspot_growth",
        6: "adsense_revenue",
    }

    def collect_candidates(self, *, limit: int = 30) -> list[NewsCandidate]:
        topics = self._topics()
        start = self._daily_offset(len(topics))
        ordered = topics[start:] + topics[:start]
        return [self._to_candidate(topic) for topic in ordered[:limit]]

    @classmethod
    def preferred_axis_by_weekday(cls, today: date | None = None) -> str:
        return cls.WEEKDAY_AXIS.get((today or date.today()).weekday(), "adsense_revenue")

    @staticmethod
    def _daily_offset(size: int) -> int:
        if size <= 0:
            return 0
        return date.today().toordinal() % size

    @staticmethod
    def _to_candidate(topic: EvergreenTopic) -> NewsCandidate:
        search_angle: dict[str, Any] = {
            "original_topic": topic.topic,
            "search_demand_topic": topic.search_demand_topic,
            "reader_search_questions": list(topic.reader_search_questions),
            "click_reason": topic.click_reason,
            "reader_benefit": topic.reader_benefit,
            "urgency_reason": topic.urgency_reason,
            "content_promise": topic.content_promise,
            "angle_type": topic.angle_type,
            "should_transform_title": True,
            "commercial_support_signal": False,
            "generic_support_keyword": "",
            "public_benefit_keyword": "",
            "public_benefit_confidence": "none",
            "public_benefit_promotion_blocked": False,
        }
        content_angle = {
            "content_type": topic.content_type,
            "reader_question": topic.reader_search_questions[0],
            "reader_loss": topic.click_reason,
            "practical_value": topic.reader_benefit,
            "example_needed": True,
        }
        return NewsCandidate(
            topic=topic.search_demand_topic,
            category=topic.category,
            summary=topic.summary,
            source_hint="evergreen_fallback",
            published_at=None,
            url=None,
            raw={
                "source": "evergreen_fallback",
                "source_type": "evergreen_fallback",
                "is_test_candidate": False,
                "publish_allowed": True,
                "evergreen_axis": topic.evergreen_axis,
                "evergreen_reason": topic.evergreen_reason,
                "target_reader": "30~50대 직장인",
                "query_group": topic.evergreen_axis,
                "topic_group": topic.topic_group,
                "content_angle": content_angle,
                "search_angle": search_angle,
                "search_demand_topic": topic.search_demand_topic,
                "reader_search_questions": list(topic.reader_search_questions),
                "click_reason": topic.click_reason,
                "reader_benefit": topic.reader_benefit,
                "urgency_reason": topic.urgency_reason,
                "content_promise": topic.content_promise,
                "angle_type": topic.angle_type,
                "evergreen_fallback": True,
                "is_stale": False,
            },
        )

    @classmethod
    def _topics(cls) -> list[EvergreenTopic]:
        return [
            *cls._adsense_revenue_topics(),
            *cls._blogspot_growth_topics(),
            *cls._ai_automation_topics(),
            *cls._money_life_topics(),
            *cls._tax_refund_support_topics(),
            *cls._digital_survival_topics(),
        ]

    @staticmethod
    def _topic(
        *,
        topic: str,
        axis: str,
        search_topic: str,
        questions: tuple[str, str, str],
        click_reason: str,
        reader_benefit: str,
        content_promise: str,
        angle_type: str,
        topic_group: str,
        content_type: str,
        category: str = "money",
        summary: str = "",
        urgency_reason: str = "",
    ) -> EvergreenTopic:
        axis_reasons = {
            "adsense_revenue": "애드센스 수익과 검색 의도는 뉴스가 약한 날에도 반복 검색되는 수익형 evergreen 축이다.",
            "blogspot_growth": "블로그스팟 운영과 글 구조는 장기 수익형 블로그를 만드는 실행형 evergreen 축이다.",
            "ai_automation": "AI 자동화는 30~50대 직장인의 시간, 생산성, 업무 선택 기준과 직접 연결된다.",
            "money_life": "생활비와 고정비 점검은 독자의 돈 손실을 줄이는 evergreen 검색 축이다.",
            "tax_refund_support": "세금 환급과 지원금 조회는 매년 반복되는 고의도 검색 주제다.",
            "digital_survival": "계정, 앱, 보안, 기기 변화는 직장인의 디지털 생활 리스크와 연결된다.",
        }
        return EvergreenTopic(
            topic=topic,
            category=category,
            summary=summary or f"{topic}을 30~50대 직장인의 돈, 시간, 선택 기준으로 점검한다.",
            evergreen_axis=axis,
            evergreen_reason=axis_reasons[axis],
            search_demand_topic=search_topic,
            reader_search_questions=questions,
            click_reason=click_reason,
            reader_benefit=reader_benefit,
            urgency_reason=urgency_reason or "지금 기준을 정해두면 반복 손실과 수정 비용을 줄일 수 있다.",
            content_promise=content_promise,
            angle_type=angle_type,
            topic_group=topic_group,
            content_type=content_type,
        )

    @classmethod
    def _adsense_revenue_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(
                topic="애드센스 수익이 안 오르는 블로그의 공통 실수 7가지",
                axis="adsense_revenue",
                search_topic="애드센스 수익이 안 오르는 블로그 점검법",
                questions=("애드센스 수익이 안 오르는 이유는 무엇인가요?", "블로그 글에서 광고 수익을 낮추는 실수는 무엇인가요?", "애드센스 수익을 올리려면 어떤 글 구조를 먼저 바꿔야 하나요?"),
                click_reason="검색 의도와 글 구조를 놓치면 방문자가 있어도 광고 수익이 잘 오르지 않을 수 있다.",
                reader_benefit="제목, 본문, 내부 링크, 광고 배치 실수를 점검하는 기준을 얻는다.",
                content_promise="수익이 안 오르는 블로그의 공통 실수를 체크리스트와 비교 기준으로 정리한다.",
                angle_type="money_compare",
                topic_group="general_life",
                content_type="general_life",
            ),
            cls._topic(
                topic="조회수는 있는데 애드센스 수익이 낮은 이유",
                axis="adsense_revenue",
                search_topic="조회수 대비 애드센스 수익이 낮을 때 볼 3가지",
                questions=("조회수는 있는데 애드센스 수익이 낮은 이유는 무엇인가요?", "광고 단가가 낮은 글감은 어떻게 구분하나요?", "방문자 체류 시간을 늘리려면 무엇을 바꿔야 하나요?"),
                click_reason="조회수만 보고 글감을 고르면 광고 단가와 체류 시간이 낮아 수익이 줄 수 있다.",
                reader_benefit="조회수, CPC, 체류 시간, 검색 의도를 함께 보는 기준을 얻는다.",
                content_promise="조회수와 수익이 어긋나는 원인을 표와 체크리스트로 정리한다.",
                angle_type="money_compare",
                topic_group="general_life",
                content_type="general_life",
            ),
            cls._topic(
                topic="Search Console 노출은 높은데 클릭이 안 나오는 이유",
                axis="adsense_revenue",
                search_topic="서치콘솔 노출은 높은데 클릭률이 낮을 때 확인할 것",
                questions=("서치콘솔 노출은 높은데 클릭이 낮은 이유는 무엇인가요?", "검색 결과 제목은 어떻게 고쳐야 하나요?", "CTR을 볼 때 어떤 페이지부터 고쳐야 하나요?"),
                click_reason="노출만 높고 클릭이 낮으면 글이 있어도 방문과 수익으로 이어지지 않는다.",
                reader_benefit="검색어, 제목, 메타 설명, 평균 순위를 함께 보는 순서를 얻는다.",
                content_promise="서치콘솔에서 먼저 볼 지표와 수정 우선순위를 정리한다.",
                angle_type="money_compare",
                topic_group="general_life",
                content_type="general_life",
            ),
            cls._topic(
                topic="애드센스 블로그에서 돈 안 되는 글감부터 버려야 하는 이유",
                axis="adsense_revenue",
                search_topic="애드센스 블로그 돈 안 되는 글감 구분법",
                questions=("애드센스 블로그에서 돈 안 되는 글감은 어떻게 구분하나요?", "조회수만 높은 글감은 왜 위험한가요?", "수익형 글감은 어떤 기준으로 골라야 하나요?"),
                click_reason="돈 안 되는 글감이 쌓이면 작성 시간은 늘고 수익 개선은 늦어진다.",
                reader_benefit="검색 의도, 광고 가치, 독자 행동 가능성으로 글감을 거르는 기준을 얻는다.",
                content_promise="버릴 글감과 남길 글감을 비교표로 정리한다.",
                angle_type="money_compare",
                topic_group="general_life",
                content_type="general_life",
            ),
            cls._topic(
                topic="블로그 광고 수익을 높이려면 먼저 봐야 할 3가지",
                axis="adsense_revenue",
                search_topic="블로그 광고 수익 높이기 전에 먼저 볼 3가지",
                questions=("블로그 광고 수익을 높이려면 무엇부터 봐야 하나요?", "광고 배치보다 먼저 고칠 것은 무엇인가요?", "수익형 블로그 점검 순서는 어떻게 잡나요?"),
                click_reason="광고 위치만 바꾸면 글감과 구조 문제를 놓쳐 수익 개선이 제한될 수 있다.",
                reader_benefit="글감, 제목, 체류 구조를 먼저 보는 점검 순서를 얻는다.",
                content_promise="광고 수익 개선 전 확인할 핵심 3가지를 정리한다.",
                angle_type="money_compare",
                topic_group="general_life",
                content_type="general_life",
            ),
        ]

    @classmethod
    def _blogspot_growth_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(topic="블로그스팟 글이 색인 안 될 때 먼저 볼 5가지", axis="blogspot_growth", search_topic="블로그스팟 색인 안 될 때 먼저 볼 5가지", questions=("블로그스팟 글이 색인 안 되는 이유는 무엇인가요?", "구글 색인 요청 전에 무엇을 확인해야 하나요?", "Search Console에서 어떤 항목을 먼저 봐야 하나요?"), click_reason="색인이 막히면 좋은 글도 검색 유입과 광고 수익으로 이어지지 않는다.", reader_benefit="색인 상태, 사이트맵, robots, 내부 링크를 확인하는 순서를 얻는다.", content_promise="블로그스팟 색인 문제를 체크리스트로 정리한다.", angle_type="platform_check", topic_group="platform_issue", content_type="platform_change", category="tech"),
            cls._topic(topic="블로그스팟 vs 네이버블로그, 수익화 목적이면 어디가 나을까", axis="blogspot_growth", search_topic="블로그스팟 네이버블로그 수익화 목적 비교", questions=("수익화 목적이면 블로그스팟과 네이버블로그 중 어디가 나은가요?", "애드센스 관점에서 어떤 플랫폼이 유리한가요?", "초보가 플랫폼을 고를 때 무엇을 비교해야 하나요?"), click_reason="플랫폼 선택을 잘못하면 글 이전과 수익화 경로 변경 비용이 생길 수 있다.", reader_benefit="검색 노출, 광고 수익, 운영 난이도, 장기 자산성을 비교할 수 있다.", content_promise="수익화 목적 플랫폼 선택 기준을 비교표로 정리한다.", angle_type="money_compare", topic_group="general_life", content_type="general_life"),
            cls._topic(topic="블로그스팟 글쓰기 템플릿: 제목, 소제목, 이미지, 내부링크까지", axis="blogspot_growth", search_topic="블로그스팟 글쓰기 템플릿 체크리스트", questions=("블로그스팟 글쓰기 템플릿은 어떻게 구성하나요?", "제목과 소제목은 어떤 순서로 잡아야 하나요?", "이미지와 내부 링크는 어디에 넣어야 하나요?"), click_reason="템플릿이 없으면 글마다 구조가 흔들려 검색 노출과 체류 시간이 약해질 수 있다.", reader_benefit="제목, 소제목, 이미지, 내부 링크를 한 번에 점검하는 작성 순서를 얻는다.", content_promise="블로그스팟 글쓰기 구조를 실행 가능한 체크리스트로 정리한다.", angle_type="benefit_howto", topic_group="general_life", content_type="general_life", category="tech"),
            cls._topic(topic="블로그스팟 초보가 애드센스 승인 전에 준비할 것", axis="blogspot_growth", search_topic="블로그스팟 애드센스 승인 전 준비 체크리스트", questions=("블로그스팟 애드센스 승인 전에 무엇을 준비해야 하나요?", "승인 거절을 줄이려면 어떤 페이지가 필요한가요?", "초보가 글 몇 개부터 점검해야 하나요?"), click_reason="승인 전에 기본 구조를 놓치면 콘텐츠보다 사이트 신뢰 요소에서 막힐 수 있다.", reader_benefit="필수 페이지, 글 구조, 정책 리스크를 확인하는 순서를 얻는다.", content_promise="애드센스 승인 전 준비 항목을 체크리스트로 정리한다.", angle_type="benefit_howto", topic_group="general_life", content_type="general_life"),
            cls._topic(topic="블로그스팟에서 내부링크가 중요한 이유", axis="blogspot_growth", search_topic="블로그스팟 내부링크 넣기 전에 볼 기준", questions=("블로그스팟에서 내부링크는 왜 중요한가요?", "내부링크는 어느 위치에 넣어야 하나요?", "관련 글이 없을 때는 어떻게 연결해야 하나요?"), click_reason="내부링크가 없으면 독자가 한 글만 보고 나가 체류와 수익 기회가 줄 수 있다.", reader_benefit="관련 글, 앵커 문구, 배치 위치를 고르는 기준을 얻는다.", content_promise="내부링크의 역할과 배치 체크리스트를 정리한다.", angle_type="benefit_howto", topic_group="general_life", content_type="general_life"),
        ]

    @classmethod
    def _ai_automation_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유", axis="ai_automation", search_topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법", questions=("ChatGPT를 써도 업무 시간이 안 줄어드는 이유는 무엇인가요?", "직장인이 AI를 쓸 때 먼저 정할 기준은 무엇인가요?", "반복 업무를 줄이려면 어떤 일부터 맡겨야 하나요?"), click_reason="검수 기준 없이 AI를 쓰면 생성 시간보다 수정 시간이 더 늘어날 수 있다.", reader_benefit="AI에 맡길 업무, 입력 방식, 검수 기준을 정하는 순서를 얻는다.", content_promise="직장인이 AI로 업무 시간을 줄이는 현실 기준을 정리한다.", angle_type="ai_setting", topic_group="ai_work", content_type="ai_work_tip", category="tech"),
            cls._topic(topic="AI 업무 자동화할 때 처음 버려야 할 반복 작업 5가지", axis="ai_automation", search_topic="AI 업무 자동화 처음 버릴 반복 작업 5가지", questions=("AI 업무 자동화는 어떤 작업부터 시작해야 하나요?", "자동화하면 안 되는 업무는 무엇인가요?", "반복 작업을 고를 때 기준은 무엇인가요?"), click_reason="처음부터 복잡한 업무를 자동화하면 실패 비용과 수정 시간이 커질 수 있다.", reader_benefit="반복 빈도, 오류 위험, 검수 난이도로 자동화 대상을 고르는 기준을 얻는다.", content_promise="처음 자동화할 반복 작업과 피할 작업을 비교표로 정리한다.", angle_type="ai_setting", topic_group="ai_work", content_type="ai_work_tip", category="tech"),
            cls._topic(topic="크롬 AI 기능 켜기 전에 확인할 설정", axis="ai_automation", search_topic="크롬 AI 기능 켜기 전에 확인할 설정", questions=("크롬 AI 기능을 켜기 전에 무엇을 확인해야 하나요?", "브라우저 AI 기능은 개인정보에 어떤 영향을 주나요?", "직장인이 크롬 AI를 쓸 때 주의할 설정은 무엇인가요?"), click_reason="업무 브라우저에서 AI 기능을 켜기 전 설정을 놓치면 개인정보와 업무 자료 노출 리스크가 생길 수 있다.", reader_benefit="계정, 동기화, 개인정보, 확장 프로그램 설정을 확인하는 순서를 얻는다.", content_promise="크롬 AI 기능 사용 전 설정 체크리스트를 정리한다.", angle_type="ai_setting", topic_group="ai_work", content_type="ai_work_tip", category="tech"),
            cls._topic(topic="구글 AI 검색 변화가 직장인에게 중요한 이유", axis="ai_automation", search_topic="구글 AI 검색 변화가 직장인 업무에 미치는 영향", questions=("구글 AI 검색 변화는 직장인에게 왜 중요한가요?", "AI 검색 시대에 자료 조사는 어떻게 바뀌나요?", "업무용 검색 결과를 볼 때 무엇을 확인해야 하나요?"), click_reason="AI 검색 결과만 믿으면 출처와 조건을 놓쳐 업무 판단이 흔들릴 수 있다.", reader_benefit="AI 답변, 공식 출처, 비교 자료를 함께 확인하는 기준을 얻는다.", content_promise="AI 검색 변화에 맞춘 직장인 검색 습관을 정리한다.", angle_type="ai_setting", topic_group="ai_work", content_type="ai_work_tip", category="tech"),
            cls._topic(topic="무료 AI 도구를 업무에 쓸 때 먼저 확인할 한계", axis="ai_automation", search_topic="무료 AI 도구 업무 활용 전 확인할 한계", questions=("무료 AI 도구를 업무에 써도 괜찮나요?", "무료 AI 도구의 한계는 무엇인가요?", "업무 자료를 넣기 전에 무엇을 확인해야 하나요?"), click_reason="무료 도구의 제한과 데이터 정책을 모르고 쓰면 업무 자료와 결과 품질에서 문제가 생길 수 있다.", reader_benefit="데이터 입력, 출력 검수, 사용량 제한, 유료 전환 조건을 확인하는 기준을 얻는다.", content_promise="무료 AI 도구를 업무에 쓰기 전 확인할 한계를 체크리스트로 정리한다.", angle_type="ai_setting", topic_group="ai_work", content_type="ai_work_tip", category="tech"),
        ]

    @classmethod
    def _money_life_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(topic="구독 서비스 자동결제 전에 확인할 것", axis="money_life", search_topic="구독 서비스 자동결제 전 확인할 체크리스트", questions=("구독 서비스 자동결제 전에 무엇을 확인해야 하나요?", "무료체험이 유료 결제로 바뀌기 전 어떻게 막나요?", "구독료를 줄이려면 어떤 기준으로 해지하나요?"), click_reason="자동결제일을 놓치면 쓰지 않는 서비스 비용이 매달 빠져나갈 수 있다.", reader_benefit="결제일, 해지 경로, 가족 공유, 대체 서비스를 점검하는 순서를 얻는다.", content_promise="구독 서비스 자동결제 전 확인할 항목을 체크리스트로 정리한다.", angle_type="money_compare", topic_group="delivery_money", content_type="money_checklist"),
            cls._topic(topic="통신비가 계속 새는 사람들의 공통 실수", axis="money_life", search_topic="통신비 줄이기 전에 먼저 볼 공통 실수", questions=("통신비가 계속 많이 나오는 이유는 무엇인가요?", "요금제 변경 전에 무엇을 확인해야 하나요?", "가족 결합과 선택약정은 어떻게 점검하나요?"), click_reason="요금제와 부가서비스를 방치하면 매달 고정비가 불필요하게 커질 수 있다.", reader_benefit="데이터 사용량, 약정, 결합, 부가서비스를 점검하는 기준을 얻는다.", content_promise="통신비가 새는 지점을 항목별로 정리한다.", angle_type="money_compare", topic_group="delivery_money", content_type="money_checklist"),
            cls._topic(topic="무료배송인데 결제금액이 커지는 이유", axis="money_life", search_topic="무료배송인데 결제금액이 커질 때 확인할 것", questions=("무료배송인데 왜 결제금액이 커지나요?", "최소주문금액은 어떻게 비교해야 하나요?", "쿠폰과 배송비를 같이 볼 때 기준은 무엇인가요?"), click_reason="무료배송 문구만 보면 최소주문금액과 쿠폰 조건 때문에 더 쓸 수 있다.", reader_benefit="최종 결제금액, 최소주문금액, 쿠폰 적용 전후를 비교하는 방법을 얻는다.", content_promise="무료배송의 실제 비용 구조를 계산 예시로 정리한다.", angle_type="money_compare", topic_group="delivery_money", content_type="money_checklist"),
            cls._topic(topic="카드 혜택이 줄어들 때 먼저 볼 조건", axis="money_life", search_topic="카드 혜택 축소 전 확인할 조건", questions=("카드 혜택이 줄면 무엇부터 확인해야 하나요?", "전월 실적 조건은 어떻게 봐야 하나요?", "카드를 바꾸기 전에 어떤 비용을 비교해야 하나요?"), click_reason="혜택 축소를 모르고 쓰면 실적은 채우고 할인은 못 받는 상황이 생길 수 있다.", reader_benefit="전월 실적, 제외 업종, 할인 한도, 대체 카드 비교 기준을 얻는다.", content_promise="카드 혜택 축소 전 볼 조건을 표로 정리한다.", angle_type="money_compare", topic_group="delivery_money", content_type="money_checklist"),
            cls._topic(topic="생활비 줄이려면 고정비부터 봐야 하는 이유", axis="money_life", search_topic="생활비 줄이기 고정비 점검 순서", questions=("생활비를 줄이려면 왜 고정비부터 봐야 하나요?", "고정비는 어떤 순서로 점검해야 하나요?", "변동비보다 먼저 볼 항목은 무엇인가요?"), click_reason="변동비만 줄이면 피로감은 커지고 실제 절감액은 작을 수 있다.", reader_benefit="통신비, 구독료, 보험료, 카드 연회비를 우선순위로 점검하는 기준을 얻는다.", content_promise="생활비 고정비 점검 순서를 체크리스트로 정리한다.", angle_type="money_compare", topic_group="delivery_money", content_type="money_checklist"),
        ]

    @classmethod
    def _tax_refund_support_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", axis="tax_refund_support", search_topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", questions=("세금 환급금 대상은 어떻게 확인하나요?", "세금 환급금은 홈택스 어디에서 조회하나요?", "세금 환급 신청 전에 어떤 정보를 준비해야 하나요?"), click_reason="환급 대상과 계좌 정보를 놓치면 돌려받을 수 있는 금액 확인이 늦어질 수 있다.", reader_benefit="홈택스 조회 경로, 환급 계좌, 필요 서류를 먼저 확인하는 순서를 얻는다.", content_promise="세금 환급금 조회 전에 볼 항목을 정보표와 체크리스트로 정리한다.", angle_type="tax_refund", topic_group="policy_benefit", content_type="tax_refund"),
            cls._topic(topic="국세환급금 조회 전 계좌 오류부터 확인하세요", axis="tax_refund_support", search_topic="국세환급금 조회 전 계좌 오류부터 확인하세요", questions=("국세환급금은 어디에서 조회하나요?", "환급 계좌 오류는 어떻게 확인하나요?", "국세환급금이 늦어지면 무엇을 봐야 하나요?"), click_reason="계좌 오류나 예금주 불일치를 놓치면 환급금 지급이 늦어질 수 있다.", reader_benefit="국세환급금 조회와 계좌 오류 확인 순서를 얻는다.", content_promise="국세환급금 조회 전 계좌와 보완 요청 확인법을 정리한다.", angle_type="tax_refund", topic_group="policy_benefit", content_type="tax_refund"),
            cls._topic(topic="종합소득세 환급금이 늦어질 때 먼저 확인할 것", axis="tax_refund_support", search_topic="종합소득세 환급금 지연 때 먼저 확인할 것", questions=("종합소득세 환급금이 늦어지는 이유는 무엇인가요?", "종합소득세 신고 내역은 어디에서 확인하나요?", "환급 지연 시 어떤 자료를 먼저 봐야 하나요?"), click_reason="신고 내역과 공제 자료 누락을 놓치면 환급 처리가 늦어질 수 있다.", reader_benefit="신고 내역, 공제 자료, 계좌, 보완 요청을 확인하는 순서를 얻는다.", content_promise="종합소득세 환급 지연 원인을 체크리스트로 정리한다.", angle_type="tax_refund", topic_group="policy_benefit", content_type="tax_refund"),
            cls._topic(topic="연말정산 환급금 확인 전 공제 자료부터 볼 것", axis="tax_refund_support", search_topic="연말정산 환급금 확인 전 공제 자료 체크", questions=("연말정산 환급금 확인 전 무엇을 봐야 하나요?", "공제 자료 누락은 어떻게 확인하나요?", "연말정산 환급금이 예상과 다르면 무엇을 봐야 하나요?"), click_reason="공제 자료가 빠지면 환급 예상액과 실제 금액이 달라질 수 있다.", reader_benefit="공제 자료, 회사 제출 내역, 환급 계좌를 확인하는 기준을 얻는다.", content_promise="연말정산 환급금 확인 전 볼 공제 자료를 정리한다.", angle_type="tax_refund", topic_group="policy_benefit", content_type="tax_refund"),
            cls._topic(topic="미수령 환급금 조회할 때 놓치기 쉬운 항목", axis="tax_refund_support", search_topic="미수령 환급금 조회할 때 놓치기 쉬운 항목", questions=("미수령 환급금은 어디에서 조회하나요?", "미수령 환급금이 생기는 이유는 무엇인가요?", "환급금을 받기 전 어떤 정보를 확인해야 하나요?"), click_reason="미수령 환급금을 조회해도 계좌와 본인 인증을 놓치면 수령까지 이어지지 않을 수 있다.", reader_benefit="미수령 환급금 조회, 계좌, 보완 안내 확인 순서를 얻는다.", content_promise="미수령 환급금 조회 시 놓치기 쉬운 항목을 정리한다.", angle_type="tax_refund", topic_group="policy_benefit", content_type="tax_refund"),
        ]

    @classmethod
    def _digital_survival_topics(cls) -> list[EvergreenTopic]:
        return [
            cls._topic(topic="카카오톡 지원 종료, 내 폰도 해당될까", axis="digital_survival", search_topic="카카오톡 지원 종료 내 폰 해당 여부 확인법", questions=("내 휴대폰도 카카오톡 지원 종료 대상인가요?", "구형폰 카카오톡은 언제부터 안 되나요?", "카카오톡 지원 종료 전에 백업해야 할 것은 무엇인가요?"), click_reason="내 기기가 지원 종료 대상인지 모르면 갑자기 앱 사용과 인증이 불편해질 수 있다.", reader_benefit="기기 버전, 앱 업데이트, 백업, 대체 기기 확인 순서를 얻는다.", content_promise="카카오톡 지원 종료 전 확인할 설정과 백업을 정리한다.", angle_type="platform_check", topic_group="platform_issue", content_type="platform_change", category="tech"),
            cls._topic(topic="구글 계정 보안 경고가 뜰 때 먼저 확인할 것", axis="digital_survival", search_topic="구글 계정 보안 경고가 뜰 때 먼저 확인할 것", questions=("구글 계정 보안 경고가 뜨면 무엇부터 확인해야 하나요?", "로그인 기록은 어디에서 보나요?", "비밀번호를 바꾸기 전에 어떤 설정을 봐야 하나요?"), click_reason="보안 경고를 무시하면 업무 메일, 결제, 저장 자료 접근 리스크가 커질 수 있다.", reader_benefit="로그인 기록, 2단계 인증, 복구 이메일, 연결 앱 확인 순서를 얻는다.", content_promise="구글 계정 보안 경고 대응 순서를 체크리스트로 정리한다.", angle_type="platform_check", topic_group="platform_issue", content_type="platform_change", category="tech"),
            cls._topic(topic="스마트폰 앱 업데이트 후 결제가 안 될 때 볼 것", axis="digital_survival", search_topic="앱 업데이트 후 결제가 안 될 때 확인할 것", questions=("앱 업데이트 후 결제가 안 되면 무엇을 확인해야 하나요?", "결제 수단 오류는 어디에서 확인하나요?", "앱 권한과 캐시는 어떻게 점검하나요?"), click_reason="결제 오류 원인을 잘못 잡으면 카드, 앱, 계정 문제를 돌아가며 확인하느라 시간이 낭비된다.", reader_benefit="앱 버전, 결제 수단, 권한, 캐시, 계정 상태 확인 순서를 얻는다.", content_promise="앱 업데이트 후 결제 오류 점검 순서를 정리한다.", angle_type="platform_check", topic_group="platform_issue", content_type="platform_change", category="tech"),
            cls._topic(topic="개인정보 털리기 전에 설정에서 볼 5가지", axis="digital_survival", search_topic="개인정보 유출 전 설정에서 먼저 볼 5가지", questions=("개인정보 유출을 막으려면 설정에서 무엇을 봐야 하나요?", "앱 권한은 어떤 기준으로 꺼야 하나요?", "계정 보안 설정은 어디부터 확인하나요?"), click_reason="권한과 로그인 설정을 방치하면 필요 없는 앱이 위치, 연락처, 계정 정보에 접근할 수 있다.", reader_benefit="앱 권한, 로그인 기기, 광고 ID, 위치 기록, 백업 설정을 확인하는 기준을 얻는다.", content_promise="개인정보 보호를 위해 설정에서 볼 5가지를 정리한다.", angle_type="consumer_warning", topic_group="platform_issue", content_type="platform_change", category="tech"),
            cls._topic(topic="오래된 스마트폰을 계속 쓸 때 먼저 확인할 보안 설정", axis="digital_survival", search_topic="오래된 스마트폰 계속 쓸 때 보안 설정 확인법", questions=("오래된 스마트폰을 계속 써도 괜찮나요?", "보안 업데이트가 끝난 폰은 무엇이 위험한가요?", "구형폰에서 먼저 꺼야 할 설정은 무엇인가요?"), click_reason="보안 업데이트가 끝난 기기를 그대로 쓰면 인증, 결제, 개인정보 리스크가 커질 수 있다.", reader_benefit="OS 버전, 보안 패치, 금융 앱, 백업, 교체 기준을 확인하는 순서를 얻는다.", content_promise="오래된 스마트폰을 계속 쓸 때 확인할 보안 설정을 정리한다.", angle_type="platform_check", topic_group="platform_issue", content_type="platform_change", category="tech"),
        ]
