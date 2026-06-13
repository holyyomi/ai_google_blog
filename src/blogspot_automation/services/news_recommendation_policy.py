from __future__ import annotations

from html import unescape
import re
from typing import Any


_GENERIC_TERMS: frozenset[str] = frozenset({
    "오늘",
    "이슈",
    "뉴스",
    "핵심",
    "정리",
    "확인",
    "방법",
    "신청",
    "신청방법",
    "대상",
    "조건",
    "대상조건",
    "먼저",
    "보기",
    "볼",
    "가지",
    "체크",
    "체크리스트",
    "지원금",
    "혜택",
    "공식",
    "기준",
})

_POLICY_SOURCE_MARKERS: tuple[str, ...] = (
    "정부24",
    "복지로",
    "지자체",
    "시·군·구청",
    "시군구청",
    "구청",
    "주민센터",
    "공식 공고",
    "공고문",
    "공식 신청",
    "신청 페이지",
    "담당 기관",
    "전담 콜센터",
    "누리집",
    "청년정책",
    "도로교통공단",
)

_POLICY_INFO_CATEGORIES: dict[str, tuple[str, ...]] = {
    "amount": ("지급 금액", "지원 금액", "금액", "지급액", "한도", "만원", "원", "차등 지급"),
    "eligibility": ("신청 대상", "대상 조건", "연령", "나이", "거주지", "거주 요건", "소득", "자격", "제외 조건"),
    "deadline": ("신청 기간", "마감", "접수 시간", "예산 소진", "조기 마감", "추가 접수"),
    "route": ("신청 방법", "신청 경로", "온라인", "방문", "정부24", "복지로", "누리집", "주민센터"),
    "documents": ("필요 서류", "신분증", "증빙", "통장 사본", "영수증", "면허증 사본", "서류"),
    "after_apply": ("접수 번호", "신청 완료", "처리 기한", "보완", "문자 안내", "결과 확인"),
}

_DRIVER_LICENSE_TERMS: tuple[str, ...] = (
    "운전면허",
    "면허 취득",
    "운전면허 취득비",
    "취득비",
    "면허학원",
    "자동차운전학원",
    "학원비",
    "수강료",
    "응시료",
    "면허증",
    "면허증 사본",
    "도로교통공단",
    "영수증",
    "사후 환급",
    "취득 후",
    "취득 전",
    "거주기간",
    "지자체별",
    "전국 공통",
)


def evaluate_news_recommendation_policy(
    *,
    title: str,
    topic: str,
    html: str,
    content_type: str = "",
    topic_group: str = "",
    raw: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Evaluate whether a post is search/recommendation/share ready.

    This is the reusable "editor skill" for every generated news post. It is
    intentionally deterministic so scheduled runs can block weak posts without
    another model call.
    """
    raw = raw if isinstance(raw, dict) else {}
    source_text = " ".join(
        str(part or "")
        for part in (
            title,
            topic,
            raw.get("search_demand_topic"),
            raw.get("original_topic"),
            raw.get("reader_benefit"),
            raw.get("content_promise"),
        )
    )
    visible_text = _visible_text(html)
    full_text = f"{source_text} {visible_text}"
    title_terms = _meaningful_terms(source_text)

    blocking_issues: list[str] = []
    warnings: list[str] = []

    matched_title_terms = [term for term in title_terms if term in visible_text]
    required_term_count = 2 if len(title_terms) >= 3 else min(1, len(title_terms))
    if required_term_count and len(matched_title_terms) < required_term_count:
        blocking_issues.append("recommendation_title_body_promise_mismatch")

    faq_questions = _faq_questions(html)
    topic_specific_faq_count = sum(
        1 for question in faq_questions
        if any(term in question for term in title_terms[:6])
    )

    shareability_signals = _shareability_signals(html, visible_text)
    shareability_score = min(100, len(shareability_signals) * 14)
    if shareability_score < 55:
        warnings.append("recommendation_shareability_score_below_55")

    policy_like = _is_policy_support_like(
        text=full_text,
        content_type=content_type,
        topic_group=topic_group,
    )
    official_source_markers = [marker for marker in _POLICY_SOURCE_MARKERS if marker in full_text]
    policy_categories = _matched_policy_categories(full_text)
    driver_terms = [term for term in _DRIVER_LICENSE_TERMS if term in full_text]
    concrete_value_signals = _concrete_value_signals(full_text)
    source_specificity = _policy_source_specificity(
        raw=raw,
        title=title,
        topic=topic,
        visible_text=visible_text,
    )

    policy_specificity_score = 0
    if policy_like:
        policy_specificity_score = min(
            100,
            len(policy_categories) * 12
            + min(len(official_source_markers), 4) * 8
            + min(len(concrete_value_signals), 4) * 6
            + min(topic_specific_faq_count, 3) * 6
        )
        if len(official_source_markers) < 2:
            blocking_issues.append("recommendation_official_source_markers_below_2")
        if len(policy_categories) < 5:
            blocking_issues.append("recommendation_policy_information_categories_below_5")
        if topic_specific_faq_count < 2:
            blocking_issues.append("recommendation_policy_faq_not_topic_specific")
        if not concrete_value_signals:
            warnings.append("recommendation_policy_lacks_concrete_value_signal")
        if source_specificity["source_fact_count"] >= 3:
            required_matches = min(3, int(source_specificity["source_fact_count"]))
            if int(source_specificity["matched_source_fact_count"]) < required_matches:
                blocking_issues.append("recommendation_policy_source_specific_facts_below_3")
            if source_specificity["amount_facts"] and not source_specificity["matched_amount_facts"]:
                blocking_issues.append("recommendation_policy_amount_missing_from_body")
            if source_specificity["policy_name_facts"] and not source_specificity["matched_policy_name_facts"]:
                blocking_issues.append("recommendation_policy_name_missing_from_body")
        elif content_type == "policy_deadline" and topic_group == "policy_benefit":
            warnings.append("recommendation_policy_source_specific_facts_unavailable")

    if "운전면허" in source_text:
        if len(driver_terms) < 5:
            blocking_issues.append("recommendation_driver_license_specifics_missing")
        if not any(term in full_text for term in ("전국 공통", "지자체별", "지역별", "거주지")):
            blocking_issues.append("recommendation_driver_license_local_variation_missing")
        if not any(term in full_text for term in ("학원비", "수강료", "응시료", "영수증", "면허증 사본")):
            blocking_issues.append("recommendation_driver_license_document_or_cost_missing")

    recommender_score = 100
    recommender_score -= len(blocking_issues) * 18
    recommender_score -= len(warnings) * 6
    if policy_like and policy_specificity_score < 70:
        blocking_issues.append("recommendation_policy_specificity_score_below_70")
        recommender_score -= 14
    recommender_score = max(0, min(100, recommender_score))

    if recommender_score < 70:
        warnings.append("recommendation_ai_recommender_score_below_70")

    return {
        "passed": not blocking_issues,
        "blocking_issues": list(dict.fromkeys(blocking_issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "ai_recommender_score": recommender_score,
        "shareability_score": shareability_score,
        "shareability_signals": shareability_signals,
        "title_terms": title_terms,
        "matched_title_terms": matched_title_terms,
        "topic_specific_faq_count": topic_specific_faq_count,
        "policy_like": policy_like,
        "policy_specificity_score": policy_specificity_score,
        "policy_information_categories": policy_categories,
        "official_source_markers": official_source_markers,
        "concrete_value_signals": concrete_value_signals,
        "driver_license_specific_terms": driver_terms,
        "policy_source_specificity": source_specificity,
    }


def _visible_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def _meaningful_terms(text: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text or "")
    terms: list[str] = []
    for token in tokens:
        cleaned = token.strip()
        if len(cleaned) < 2:
            continue
        if cleaned in _GENERIC_TERMS:
            continue
        if cleaned not in terms:
            terms.append(cleaned)
        if len(terms) >= 10:
            break
    return terms


def _faq_questions(html: str) -> list[str]:
    questions: list[str] = []
    for match in re.finditer(r"<h3\b[^>]*>(.*?)</h3>", html or "", flags=re.IGNORECASE | re.DOTALL):
        text = _visible_text(match.group(1))
        if text:
            questions.append(text)
    return questions


def _shareability_signals(html: str, visible_text: str) -> list[str]:
    checks: list[tuple[str, bool]] = [
        ("table", "<table" in (html or "").lower()),
        ("faq", len(_faq_questions(html)) >= 3),
        ("checklist", any(term in visible_text for term in ("체크리스트", "바로 할", "지금 바로", "오늘 바로"))),
        ("example", any(term in visible_text for term in ("예시", "상황", "사례"))),
        ("official_check", any(term in visible_text for term in ("공식", "공고", "신청 페이지", "정부24", "복지로"))),
        ("risk_or_mistake", any(term in visible_text for term in ("주의", "함정", "착각", "제외", "놓치기 쉬운"))),
        ("updated_date", bool(re.search(r"20\d{2}-\d{2}-\d{2}", visible_text))),
    ]
    return [name for name, present in checks if present]


def _is_policy_support_like(*, text: str, content_type: str, topic_group: str) -> bool:
    if content_type in {"policy_deadline", "policy_benefit"}:
        return True
    if topic_group == "policy_benefit":
        return True
    return any(term in text for term in ("지원금", "보조금", "장려금", "정부 지원", "지자체 지원"))


def _matched_policy_categories(text: str) -> list[str]:
    matched: list[str] = []
    for category, terms in _POLICY_INFO_CATEGORIES.items():
        if any(term in text for term in terms):
            matched.append(category)
    return matched


def _concrete_value_signals(text: str) -> list[str]:
    signals: list[str] = []
    if re.search(r"\d+\s*(?:만\s*)?원", text):
        signals.append("money_amount")
    if re.search(r"\d+\s*%", text):
        signals.append("percentage")
    for term in ("전국 공통", "지자체별", "지역별", "사후 환급", "취득 후", "취득 전", "예산 소진", "조기 마감"):
        if term in text:
            signals.append(term)
    return signals


def _policy_source_specificity(
    *,
    raw: dict[str, Any],
    title: str,
    topic: str,
    visible_text: str,
) -> dict[str, object]:
    source_text = _source_specific_text(raw=raw, title=title, topic=topic)
    facts = _extract_source_facts(source_text)
    visible_compact = re.sub(r"\s+", "", visible_text or "")

    def _matched(values: list[str]) -> list[str]:
        matched: list[str] = []
        for value in values:
            text = " ".join(str(value or "").split()).strip()
            if not text:
                continue
            compact = re.sub(r"\s+", "", text)
            if text in visible_text or compact in visible_compact:
                matched.append(text)
        return matched

    source_facts = list(dict.fromkeys(
        facts["policy_names"]
        + facts["regions"]
        + facts["amounts"]
        + facts["targets"]
        + facts["payments"]
        + facts["source_names"]
    ))
    matched_facts = _matched(source_facts)
    return {
        "source_fact_count": len(source_facts),
        "matched_source_fact_count": len(matched_facts),
        "source_facts": source_facts,
        "matched_source_facts": matched_facts,
        "amount_facts": facts["amounts"],
        "matched_amount_facts": _matched(facts["amounts"]),
        "policy_name_facts": facts["policy_names"],
        "matched_policy_name_facts": _matched(facts["policy_names"]),
    }


def _source_specific_text(*, raw: dict[str, Any], title: str, topic: str) -> str:
    values: list[str] = []
    for key in (
        "source_title", "original_topic", "cleaned_title", "original_title",
        "source_summary", "public_benefit_original_topic",
    ):
        value = raw.get(key)
        if value:
            values.append(str(value))
    for key in ("source_titles", "sample_titles", "source_excerpts"):
        items = raw.get(key)
        if isinstance(items, list):
            values.extend(str(item or "") for item in items[:5])
    verification = raw.get("web_verification")
    if isinstance(verification, dict):
        for docs in verification.values():
            if isinstance(docs, list):
                for item in docs[:3]:
                    if isinstance(item, dict):
                        values.extend([str(item.get("title") or ""), str(item.get("snippet") or "")])
    naver_item = raw.get("naver_item")
    if isinstance(naver_item, dict):
        values.extend([str(naver_item.get("title") or ""), str(naver_item.get("description") or "")])
    if not values:
        return ""
    return _clean_source_text(" ".join(values + [title, topic]))


def _clean_source_text(text: str) -> str:
    clean = unescape(str(text or ""))
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\[[^\]]{1,18}\]", " ", clean)
    return " ".join(clean.split())


def _extract_source_facts(text: str) -> dict[str, list[str]]:
    if not text:
        return {
            "policy_names": [],
            "regions": [],
            "amounts": [],
            "targets": [],
            "payments": [],
            "source_names": [],
        }
    regions = _unique_from_terms(text, (
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    ))
    payments = _unique_from_terms(text, (
        "울산페이", "지역화폐", "지역사랑상품권", "상품권", "바우처",
        "카드 포인트", "포인트", "현금", "계좌 입금",
    ))
    source_names = _unique_from_terms(text, (
        "고용노동부", "보건복지부", "국세청", "정부24", "복지로",
        "대한민국 정책브리핑", "울산시", "울산광역시", "서울시", "부산시",
    ))
    amounts = _unique_from_regex(
        r"(?:1인(?:당)?\s*)?(?:최대\s*)?\d+(?:,\d{3})*\s*(?:만\s*)?원",
        text,
    )
    targets = _extract_target_facts(text)
    policy_names = _extract_policy_name_facts(text)
    return {
        "policy_names": policy_names,
        "regions": regions,
        "amounts": amounts,
        "targets": targets,
        "payments": payments,
        "source_names": source_names,
    }


def _unique_from_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for term in terms:
        if term in text and term not in found:
            found.append(term)
    return found


def _unique_from_regex(pattern: str, text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(pattern, text or ""):
        value = " ".join(match.group(0).split()).strip()
        if value and value not in found:
            found.append(value)
    return found


def _extract_target_facts(text: str) -> list[str]:
    targets: list[str] = []
    for term in ("근로자", "재직자", "청년", "소상공인", "자영업자", "사업자", "구직자"):
        for match in re.finditer(rf"[가-힣A-Za-z0-9·\s]{{0,18}}{re.escape(term)}", text or ""):
            value = " ".join(match.group(0).split()).strip(" ,.-")
            if len(value) >= 2 and value not in targets:
                targets.append(value[:32])
    return targets[:4]


def _extract_policy_name_facts(text: str) -> list[str]:
    names: list[str] = []
    patterns = (
        r"[가-힣A-Za-z0-9·\s]{2,34}(?:지원사업|지원금|장려금|보조금|수당)",
        r"[가-힣A-Za-z0-9·\s]{2,20}(?:안심페이|울산페이)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            value = " ".join(match.group(0).split()).strip(" ,.-")
            value = re.split(r"\s*(?:신청방법|신청 방법|대상 조건|공고|참여자 모집|,|—)", value)[0].strip()
            if len(value) >= 3 and value not in names:
                names.append(value[:36])
    return names[:4]
