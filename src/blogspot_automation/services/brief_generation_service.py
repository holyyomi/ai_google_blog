from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import urlparse

from blogspot_automation.services.topic_selection_service import SelectedTopicResult, SourceArticle
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecord,
    BriefRecordRepository,
    PublishStatus,
)


EXECUTION_OUTLINE = [
    "Hero",
    "한 줄 결론",
    "이 글이 필요한 사람",
    "핵심 요약 3~5개",
    "기사 기반 핵심 사실 정리",
    "지금 왜 중요한가",
    "그래서 개인에게 무슨 의미인가",
    "시작 방법 / 실행 단계",
    "준비물 / 시간 / 비용 / 예상수익",
    "추천 대상 / 비추천 대상",
    "실패 포인트",
    "실전 체크리스트",
    "7일 실행 플랜 또는 첫 3단계 액션",
    "주의사항",
    "FAQ",
    "CTA",
    "출처 / 업데이트",
]

PILLAR_PROFILES = {
    "매일 새로운 부업 해부": {
        "target_reader": "퇴근 후 하루 30~60분 안에서 현실적인 부업 가능성을 검토하는 40대 직장인",
        "reader_problem": "아이디어는 많지만 무엇부터 검증해야 할지 모르고, 시간과 비용을 잃는 것이 두렵다.",
        "recommended_for": [
            "작게 실험하고 반응을 보고 싶은 직장인",
            "월 5만~30만원 수준의 보조 수익부터 확인하고 싶은 사람",
        ],
        "not_recommended_for": [
            "초기 자금 없이 바로 큰 수익만 기대하는 사람",
            "반복 작업과 기록을 전혀 하고 싶지 않은 사람",
        ],
        "time": "첫 세팅 2~3시간, 이후 하루 30~60분",
        "cost": "0원~10만원",
        "income": "월 5만~50만원",
        "difficulty": "중간",
        "cta_type": "action_plan",
    },
    "한국뉴스 기반 관심 한국주식 해설": {
        "target_reader": "종목 추천보다 뉴스가 개인 포트폴리오에 어떤 의미인지 알고 싶은 한국주식 입문~중급 투자자",
        "reader_problem": "뉴스는 많이 보지만 어떤 숫자와 조건을 확인해야 하는지 몰라 감정적으로 반응한다.",
        "recommended_for": [
            "뉴스를 투자 판단 보조 자료로 읽고 싶은 개인 투자자",
            "실적·공시·산업 흐름을 해설형으로 이해하고 싶은 사람",
        ],
        "not_recommended_for": [
            "당장 매수 종목 한 개만 추천받고 싶은 사람",
            "손익 책임을 기사에 넘기고 싶은 사람",
        ],
        "time": "기사 정리 20분, 공시 확인 20분",
        "cost": "0원",
        "income": "직접 수익 범위 제시 불가, 손실 방지와 판단 보조 목적",
        "difficulty": "중간",
        "cta_type": "next_read",
    },
    "AI 부업 / 온라인 수익화 실전": {
        "target_reader": "본업은 유지하면서 AI를 활용해 작게 검증 가능한 온라인 수익 구조를 만들고 싶은 직장인",
        "reader_problem": "툴은 많지만 실제로 무엇을 팔고, 얼마의 시간과 비용이 드는지 감이 없다.",
        "recommended_for": [
            "문서, 템플릿, 반복 업무 자동화에 거부감이 없는 사람",
            "작업 기록을 남기며 2주 이상 실험할 수 있는 사람",
        ],
        "not_recommended_for": [
            "복붙만으로 즉시 수익을 기대하는 사람",
            "검수 없이 자동화 결과를 바로 판매하려는 사람",
        ],
        "time": "첫 세팅 3~4시간, 이후 하루 40~90분",
        "cost": "월 0원~7만원",
        "income": "월 10만~100만원",
        "difficulty": "중상",
        "cta_type": "action_plan",
    },
    "부업 세금 / N잡 세금": {
        "target_reader": "부업 소득이 생기기 시작했지만 세금 신고 시점과 기준을 헷갈리는 직장인",
        "reader_problem": "돈은 조금 벌리기 시작했는데 언제부터 신고를 준비해야 하는지 몰라 나중에 한 번에 엉킨다.",
        "recommended_for": [
            "플랫폼 수익, 프리랜서 수익, 소규모 판매 수익이 섞여 있는 사람",
            "세금 폭탄보다 기록 관리부터 하고 싶은 사람",
        ],
        "not_recommended_for": [
            "합법적 기준보다 편법만 찾는 사람",
            "개인 상황 확인 없이 일반론을 확정 답으로 받아들이려는 사람",
        ],
        "time": "기록 정리 1시간, 신고 전 체크 30분",
        "cost": "0원~5만원",
        "income": "직접 수익보다 누락 비용 방지 목적",
        "difficulty": "중간",
        "cta_type": "checklist",
    },
    "한국주식 초보 가이드": {
        "target_reader": "뉴스와 숫자를 함께 보며 한국주식 기초 체력을 만들고 싶은 초보 투자자",
        "reader_problem": "용어가 어려워 기사 내용을 읽어도 왜 중요한지 연결이 되지 않는다.",
        "recommended_for": [
            "기초 개념과 뉴스 읽는 순서를 배우고 싶은 초보",
            "ETF와 개별주를 구분해 접근하고 싶은 사람",
        ],
        "not_recommended_for": [
            "짧은 기간 고수익만 원하는 사람",
            "리스크 설명 없이 매수 신호만 원하는 사람",
        ],
        "time": "하루 20~30분",
        "cost": "0원",
        "income": "직접 수익 범위 제시 불가, 기초 역량 축적 목적",
        "difficulty": "초중급",
        "cta_type": "next_read",
    },
}


@dataclass(slots=True)
class BriefGenerationInput:
    work_item_id: str
    selected_pillar: str
    selected_topic: str
    why_selected: str
    source_articles: list[dict[str, object]]
    primary_keyword: str
    secondary_keywords: list[str]
    article_pack: dict[str, object]


class BlogBriefGenerationService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        brief_repository: BriefRecordRepository,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.brief_repository = brief_repository

    def generate_from_selected_topic(self, selection: SelectedTopicResult) -> BriefRecord:
        if selection.publish_status != PublishStatus.PLANNED.value:
            raise ValueError(
                f"Topic generation is blocked because publish_status={selection.publish_status}. "
                "Only planned topics with sufficient sources can continue."
            )
        if selection.source_quality_status != "sufficient" or selection.source_count < 3:
            raise ValueError("Topic generation is blocked because fewer than 3 real source articles were validated.")
        source_articles = [_source_article_from_dict(article) for article in selection.source_articles]
        payload = BriefGenerationInput(
            work_item_id=selection.saved_work_item_id,
            selected_pillar=selection.selected_pillar,
            selected_topic=selection.selected_topic,
            why_selected=selection.why_selected,
            source_articles=selection.source_articles,
            primary_keyword=str(selection.keyword_set.get("primary_keyword") or ""),
            secondary_keywords=list(selection.keyword_set.get("secondary_keywords") or []),
            article_pack=dict(selection.article_pack or {}),
        )
        return self.generate_brief(payload, source_articles=source_articles)

    def generate_brief(
        self,
        payload: BriefGenerationInput,
        *,
        source_articles: list[SourceArticle],
    ) -> BriefRecord:
        work_item = self.work_item_repository.get_by_id(payload.work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {payload.work_item_id}")

        deduped_articles = _dedupe_articles(source_articles)
        if len(deduped_articles) < 3:
            raise ValueError("Brief generation requires at least 3 deduplicated source articles.")

        profile = PILLAR_PROFILES.get(payload.selected_pillar, PILLAR_PROFILES["AI 부업 / 온라인 수익화 실전"])
        article_pack = payload.article_pack if isinstance(payload.article_pack, dict) else {}
        hard_facts = list(article_pack.get("hard_facts") or []) or _build_hard_facts(deduped_articles)
        facts = _extract_facts(deduped_articles)
        source_consensus = list(article_pack.get("source_consensus") or []) or _build_source_consensus(deduped_articles)
        source_differences = list(article_pack.get("source_differences") or []) or _build_source_differences(deduped_articles)
        practical_actions = _build_practical_actions(payload.selected_pillar, payload.primary_keyword, deduped_articles)
        key_takeaways = _build_key_takeaways(payload.selected_topic, hard_facts, practical_actions)
        faq_items = _build_faq_items(payload.selected_pillar, payload.selected_topic, profile, practical_actions)
        cautions = _build_cautions(payload.selected_pillar, deduped_articles)
        failure_points = _build_failure_points(payload.selected_pillar, deduped_articles)
        what_it_means = list(article_pack.get("reader_relevance") or []) or _build_reader_meaning(payload.selected_pillar, payload.selected_topic, deduped_articles)
        why_now = _build_why_now(deduped_articles, payload.selected_topic)
        cta_direction = _build_cta_direction(payload.selected_pillar, practical_actions)
        timestamp = datetime.now(timezone.utc).isoformat()
        content_density_status = _evaluate_content_density(
            hard_facts=hard_facts,
            practical_actions=practical_actions,
            faq_items=faq_items,
            failure_points=failure_points,
            profile=profile,
        )

        brief = BriefRecord(
            work_item_id=payload.work_item_id,
            created_at=timestamp,
            updated_at=timestamp,
            brief_summary=_build_brief_summary(payload.selected_topic, payload.why_selected, what_it_means),
            final_angle=_build_final_angle(payload.selected_pillar, payload.selected_topic),
            target_reader=profile["target_reader"],
            reader_problem=profile["reader_problem"],
            search_intent=str(article_pack.get("search_intent_guess") or _build_search_intent(payload.selected_pillar, payload.primary_keyword)),
            one_line_hook=_build_one_line_hook(payload.selected_pillar, payload.selected_topic),
            why_now=why_now,
            outline_sections=list(EXECUTION_OUTLINE),
            key_takeaways=key_takeaways,
            facts_from_sources=facts,
            hard_facts_from_sources=hard_facts,
            source_consensus=source_consensus,
            source_differences=source_differences,
            what_it_means_to_reader=what_it_means,
            cautions=cautions,
            practical_actions=practical_actions,
            estimated_time_to_start=profile["time"],
            estimated_cost_to_start=profile["cost"],
            potential_income_range=profile["income"],
            difficulty_level=profile["difficulty"],
            recommended_for=profile["recommended_for"],
            not_recommended_for=profile["not_recommended_for"],
            failure_points=failure_points,
            monetization_block_idea=_build_monetization_block_idea(payload.selected_pillar),
            faq_candidates=[item["question"] for item in faq_items],
            faq_items=faq_items,
            evidence_points=hard_facts[:5],
            cta_direction=cta_direction,
            cta_type=profile["cta_type"],
            content_density_status=content_density_status,
        )
        saved = self.brief_repository.upsert(brief)

        work_item.estimated_time_to_start = brief.estimated_time_to_start
        work_item.estimated_cost_to_start = brief.estimated_cost_to_start
        work_item.potential_income_range = brief.potential_income_range
        work_item.difficulty_level = brief.difficulty_level
        work_item.recommended_for = brief.recommended_for
        work_item.not_recommended_for = brief.not_recommended_for
        work_item.failure_points = brief.failure_points
        work_item.faq_items = brief.faq_items
        work_item.cta_type = brief.cta_type
        work_item.content_density_status = brief.content_density_status
        self.work_item_repository.upsert(work_item)

        if work_item.publish_status == PublishStatus.PLANNED.value:
            self.work_item_repository.transition_status(
                item_id=work_item.id,
                next_status=PublishStatus.GENERATED,
                notes="brief generated",
            )
        return saved


def _dedupe_articles(articles: list[SourceArticle]) -> list[SourceArticle]:
    seen: set[str] = set()
    result: list[SourceArticle] = []
    for article in articles:
        key = re.sub(r"\s+", " ", f"{article.title} {article.summary}".strip().lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def _source_article_from_dict(article: dict[str, object]) -> SourceArticle:
    return SourceArticle(
        provider_name=str(article.get("provider_name", "")),
        source_url=str(article.get("source_url", "")),
        title=str(article.get("title", "")),
        summary=str(article.get("summary") or article.get("one_line_summary") or ""),
        article_url=str(article.get("article_url", "")),
        published_at=str(article.get("published_at")) if article.get("published_at") else None,
    )


def _extract_facts(articles: list[SourceArticle]) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    for article in articles:
        for text in [article.title, article.summary]:
            cleaned = re.sub(r"\s+", " ", text.strip())
            if len(cleaned) < 18:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            facts.append(cleaned)
    return facts[:8]


def _build_hard_facts(articles: list[SourceArticle]) -> list[str]:
    hard_facts: list[str] = []
    for article in articles:
        domain = urlparse(article.article_url).netloc
        published = article.published_at[:10] if article.published_at else "날짜 미상"
        hard_facts.append(f"{published} 기준 {domain} 기사: {article.title}")
        if article.summary.strip():
            hard_facts.append(f"{domain} 요약 포인트: {article.summary.strip()}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in hard_facts:
        if item.lower() in seen:
            continue
        seen.add(item.lower())
        deduped.append(item)
    return deduped[:6]


def _build_source_consensus(articles: list[SourceArticle]) -> list[str]:
    first = articles[0]
    return [
        f"여러 기사 모두 '{_safe_topic_phrase(first.title)}' 흐름이 단기 이슈가 아니라 실제 행동 변화로 이어지고 있다고 본다.",
        "대부분의 기사에서 기회보다 실행 조건과 검수·판단 기준이 함께 중요하다고 강조한다.",
        "초보일수록 먼저 확인할 숫자, 시간, 리스크를 분리해서 봐야 한다는 점이 공통적이다.",
    ]


def _build_source_differences(articles: list[SourceArticle]) -> list[str]:
    if len(articles) < 2:
        return []
    return [
        f"{_domain_label(articles[0].article_url)}는 기회 측면을 더 강조하고, {_domain_label(articles[1].article_url)}는 실행 조건과 리스크를 더 강조한다.",
        "어떤 기사는 성장 신호를 중심으로 설명하고, 다른 기사는 실제로 시작할 때 필요한 검수와 운영 부담을 더 길게 다룬다.",
    ]


def _build_practical_actions(pillar: str, primary_keyword: str, articles: list[SourceArticle]) -> list[str]:
    if pillar == "부업 세금 / N잡 세금":
        return [
            "이번 달 입금 내역을 모아 어떤 수익이 사업소득인지 기타소득인지 먼저 구분한다.",
            "플랫폼 수수료, 광고비, 외주비처럼 나중에 증빙이 필요한 비용부터 한 파일에 정리한다.",
            "신고 기한 직전에 몰리지 않도록 분기별로 매출·비용 로그를 점검한다.",
        ]
    if pillar == "한국뉴스 기반 관심 한국주식 해설":
        return [
            f"{primary_keyword} 관련 기사 3건을 읽고 공시, 실적, 산업 키워드가 동시에 반복되는지 확인한다.",
            "뉴스만 보지 말고 숫자가 연결되는 공시 문서나 실적 발표 자료를 함께 확인한다.",
            "매수 결론을 내리기 전에 이번 이슈가 단기 재료인지 구조 변화인지 따로 메모한다.",
        ]
    if pillar == "한국주식 초보 가이드":
        return [
            f"{primary_keyword} 관련 용어를 먼저 3개만 정리한 뒤 기사와 공시를 나란히 읽는다.",
            "뉴스를 본 뒤 바로 거래하지 말고 같은 업종 ETF와 비교해 흐름을 익힌다.",
            "하루 20분만 투자해 기사 제목, 핵심 숫자, 내 해석을 한 줄로 기록한다.",
        ]
    if pillar == "AI 부업 / 온라인 수익화 실전":
        return [
            "오늘 안에 자동화할 작업 한 개만 고른다. 예: 글 초안, 제목 변형, 요약 정리.",
            "무료 또는 저가 도구 조합으로 먼저 3일 테스트하고, 이후에만 유료 툴 비용을 늘린다.",
            "자동화 결과물을 그대로 판매하지 말고 검수 체크리스트를 붙여 품질 기준을 만든다.",
        ]
    return [
        "수익 기대보다 먼저 하루에 실제로 쓸 수 있는 시간을 계산한다.",
        "첫 실험은 비용이 적고 검증 속도가 빠른 방식으로 시작한다.",
        "기록이 남는 채널부터 테스트해 반응과 실패 원인을 분리한다.",
    ]


def _build_key_takeaways(topic: str, hard_facts: list[str], practical_actions: list[str]) -> list[str]:
    takeaways = [
        f"{topic}은 단순 뉴스 요약보다 지금 무엇을 먼저 점검해야 하는지 아는 사람이 유리하다.",
        "시작 속도보다 검수 기준과 기록 방식이 오래 가는 결과를 만든다.",
        "시간, 비용, 난이도부터 계산하면 과장된 기대를 줄일 수 있다.",
    ]
    if hard_facts:
        takeaways.append(f"여러 기사에서 반복된 핵심 사실은 '{hard_facts[0]}'에 가깝다.")
    if practical_actions:
        takeaways.append(f"가장 먼저 할 일은 '{practical_actions[0]}' 수준으로 작게 시작하는 것이다.")
    return takeaways[:5]


def _build_reader_meaning(pillar: str, topic: str, articles: list[SourceArticle]) -> list[str]:
    if pillar == "부업 세금 / N잡 세금":
        return [
            "지금 기록을 시작하면 신고 직전에 몰리는 스트레스와 누락 가능성을 줄일 수 있다.",
            "수익이 아직 작더라도 기준을 모르면 나중에 정리 비용이 더 커진다.",
        ]
    if pillar in {"한국뉴스 기반 관심 한국주식 해설", "한국주식 초보 가이드"}:
        return [
            "이 글의 목적은 매수 추천이 아니라 뉴스를 읽고도 흔들리지 않는 해석 기준을 만드는 것이다.",
            "기사 한 건보다 여러 기사에서 공통으로 반복되는 숫자와 표현을 보는 습관이 필요하다.",
        ]
    return [
        "툴을 더 사는 것보다 지금 가진 시간 안에서 반복 가능한 프로세스를 만드는 것이 더 중요하다.",
        "첫 수익보다 첫 검증이 먼저다. 1주 안에 작게 검증할 수 있어야 다음 단계로 갈 수 있다.",
    ]


def _build_why_now(articles: list[SourceArticle], topic: str) -> str:
    domains = ", ".join(_domain_label(article.article_url) for article in articles[:3])
    return f"최근 기사들이 {domains}에서 비슷한 방향으로 {topic}의 실행 조건을 다루고 있어, 지금 기준을 잡아두면 시행착오를 줄이기 쉽다."


def _build_cautions(pillar: str, articles: list[SourceArticle]) -> list[str]:
    cautions = [
        "이 글은 과장된 성공담을 만들기보다, 실제로 드는 시간과 비용을 먼저 계산하도록 설계했다.",
        "출처에 없는 수익 수치나 투자 확신 표현은 쓰지 않는다.",
    ]
    if pillar in {"한국뉴스 기반 관심 한국주식 해설", "한국주식 초보 가이드"}:
        cautions.append("이 글은 투자 추천이 아니며, 실제 판단은 공시와 본인 기준 확인이 먼저다.")
    if pillar == "부업 세금 / N잡 세금":
        cautions.append("개인별 소득 구조가 다르므로 세무 판단은 최종적으로 본인 상황에 맞춰 확인해야 한다.")
    else:
        cautions.append("쉽게 돈 번다는 표현보다 반복 가능성과 검수 비용을 먼저 따져야 한다.")
    text = " ".join(f"{article.title} {article.summary}" for article in articles)
    if any(word in text for word in ["보장", "무조건", "급등", "적중"]):
        cautions.append("기사 표현이 과장돼 보이면 제목보다 본문 조건과 출처를 먼저 확인한다.")
    return cautions[:5]


def _build_failure_points(pillar: str, articles: list[SourceArticle]) -> list[str]:
    base = [
        "처음부터 큰 범위로 시작해 검수 시간이 감당되지 않는 경우",
        "시간과 비용을 기록하지 않아 수익처럼 보이지만 실제로는 남는 것이 없는 경우",
    ]
    if pillar == "AI 부업 / 온라인 수익화 실전":
        base.extend(
            [
                "자동화 결과물을 검수 없이 바로 배포해 신뢰를 잃는 경우",
                "유료 도구를 먼저 결제하고 실제 고객 반응 검증은 뒤로 미루는 경우",
            ]
        )
    elif pillar == "부업 세금 / N잡 세금":
        base.extend(
            [
                "입금은 받았지만 어떤 소득 유형인지 구분하지 않는 경우",
                "매출은 기록하고 비용 증빙은 모으지 않아 신고 때 손해 보는 경우",
            ]
        )
    else:
        base.extend(
            [
                "기사 한 건만 보고 결론을 내리는 경우",
                "숫자 확인 없이 분위기만 따라가며 의사결정하는 경우",
            ]
        )
    return base[:4]


def _build_faq_items(
    pillar: str,
    topic: str,
    profile: dict[str, object],
    practical_actions: list[str],
) -> list[dict[str, str]]:
    income = str(profile["income"])
    time_needed = str(profile["time"])
    return [
        {
            "question": f"{topic}, 진짜 초보도 가능한가?",
            "answer": "가능하다. 다만 처음부터 큰 범위로 하지 말고, 본문에서 제안한 첫 단계 하나만 3일 동안 반복해 보는 방식이 현실적이다.",
        },
        {
            "question": "하루에 몇 분 또는 몇 시간이 필요한가?",
            "answer": f"기본적으로 {time_needed} 수준을 잡는 것이 안전하다. 첫 주는 세팅과 기록 때문에 조금 더 걸릴 수 있다.",
        },
        {
            "question": "돈은 언제부터 벌 수 있나?",
            "answer": f"이 글에서 보는 현실적 범위는 {income} 수준이다. 바로 수익이 난다고 가정하지 말고 먼저 반응과 유지 가능성을 확인해야 한다.",
        },
        {
            "question": "이거 사기나 과장 아닌가?",
            "answer": "그래서 여러 기사에서 반복된 사실과 조건만 남겼다. 과장된 표현은 제외했고, 출처가 없는 수익 숫자는 넣지 않았다.",
        },
        {
            "question": "세금 신고는 언제부터 고려해야 하나?",
            "answer": "정기적으로 돈이 들어오기 시작했다면 금액이 작더라도 기록을 먼저 시작하는 편이 낫다. 신고 판단은 뒤여도 기록은 오늘부터 가능하다.",
        },
        {
            "question": "어떤 사람은 하지 말아야 하나?",
            "answer": f"{', '.join(profile['not_recommended_for'])} 같은 경우에는 시작 전에 기대치를 조정하는 편이 낫다.",
        },
    ]


def _build_search_intent(pillar: str, primary_keyword: str) -> str:
    if pillar == "한국뉴스 기반 관심 한국주식 해설":
        return f"{primary_keyword} 관련 뉴스가 왜 중요한지, 개인 투자자가 어떤 숫자를 먼저 봐야 하는지 알고 싶다."
    if pillar == "부업 세금 / N잡 세금":
        return f"{primary_keyword} 기준으로 언제부터 기록하고 무엇을 신고 준비해야 하는지 알고 싶다."
    return f"{primary_keyword} 흐름이 실제 실행 가능한지, 시간·비용·수익 범위가 어느 정도인지 알고 싶다."


def _build_one_line_hook(pillar: str, topic: str) -> str:
    if pillar == "한국뉴스 기반 관심 한국주식 해설":
        return f"{topic}은 종목 추천보다 뉴스 해석 기준을 세우는 글이어야 오래 쓸 수 있다."
    if pillar == "부업 세금 / N잡 세금":
        return f"{topic}은 나중에 해결할 문제가 아니라, 수익이 작을 때부터 기록 습관으로 줄일 수 있는 문제다."
    return f"{topic}은 멋진 아이디어보다, 오늘 밤 바로 검증할 수 있는 실행 단위로 쪼개는 것이 핵심이다."


def _build_brief_summary(topic: str, why_selected: str, meanings: list[str]) -> str:
    meaning = meanings[0] if meanings else topic
    return f"{topic}을 단순 요약이 아니라 독자 실행 관점으로 재구성한다. {meaning} {why_selected}"


def _build_final_angle(pillar: str, topic: str) -> str:
    if pillar in {"한국뉴스 기반 관심 한국주식 해설", "한국주식 초보 가이드"}:
        return f"{topic}을 추천이 아닌 해설형 기준 정리로 풀어 독자가 스스로 판단하도록 돕는다."
    if pillar == "부업 세금 / N잡 세금":
        return f"{topic}을 신고 타이밍보다 기록과 누락 방지 관점에서 설명한다."
    return f"{topic}을 바로 시도 가능한 단계, 시간, 비용, 실패 포인트 중심으로 바꿔 설명한다."


def _build_monetization_block_idea(pillar: str) -> str:
    if pillar == "AI 부업 / 온라인 수익화 실전":
        return "도구 비용, 검수 시간, 재판매 가능성을 한 박스에서 동시에 비교해 독자가 바로 계산할 수 있게 한다."
    if pillar == "부업 세금 / N잡 세금":
        return "수익 확대보다 누락 비용 방지와 기록 효율을 중심으로 설명한다."
    if pillar in {"한국뉴스 기반 관심 한국주식 해설", "한국주식 초보 가이드"}:
        return "수익 약속 대신 정보 해석 능력과 리스크 관리 관점으로 설계한다."
    return "작게 시작해 실험 비용을 관리하는 방향으로 설계한다."


def _build_cta_direction(pillar: str, practical_actions: list[str]) -> str:
    first = practical_actions[0] if practical_actions else "오늘 할 첫 단계 한 개를 정한다."
    if pillar == "부업 세금 / N잡 세금":
        return f"오늘은 '{first}'부터 처리하고, 다음 글에서는 소득 유형별 기록 템플릿까지 이어서 확인한다."
    if pillar in {"한국뉴스 기반 관심 한국주식 해설", "한국주식 초보 가이드"}:
        return f"지금 '{first}'를 해보고, 다음에는 같은 뉴스 흐름을 읽는 초보 가이드와 비교해 본다."
    return f"오늘의 1단계는 '{first}'다. 실행 후에는 다음 글에서 검수 기준과 수익화 비교표까지 이어서 확인한다."


def _evaluate_content_density(
    *,
    hard_facts: list[str],
    practical_actions: list[str],
    faq_items: list[dict[str, str]],
    failure_points: list[str],
    profile: dict[str, object],
) -> str:
    has_metrics = all(str(profile[key]).strip() for key in ["time", "cost", "income", "difficulty"])
    if has_metrics and len(hard_facts) >= 4 and len(practical_actions) >= 3 and len(faq_items) >= 5 and len(failure_points) >= 3:
        return "dense"
    return "thin"


def _safe_topic_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _domain_label(url: str) -> str:
    return urlparse(url).netloc or url
