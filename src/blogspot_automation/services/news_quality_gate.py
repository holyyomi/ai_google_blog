from __future__ import annotations

from html import unescape
import logging
import os
import re

from blogspot_automation.models.news_models import ScoredNewsCandidate
from blogspot_automation.services.answer_engine_policy import answer_engine_coverage
from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.cover_image_policy import cover_image_coverage, cover_image_required_from_env
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.news_focus_policy import ai_blog_mode_from_env, evaluate_news_focus
from blogspot_automation.services.news_recommendation_policy import evaluate_news_recommendation_policy
from blogspot_automation.services.news_taxonomy import is_delivery_money_text, is_tax_refund_text
from blogspot_automation.services.publish_preview_scorecard import build_publish_preview_scorecard
from blogspot_automation.services.seo_policy import (
    MAX_BLOGSPOT_LABELS,
    MAX_CONTENT_HASHTAGS,
    count_external_anchor_links,
    has_unverified_experience_or_income_claim,
)
from blogspot_automation.services.title_integrity_policy import audit_title_integrity

logger = logging.getLogger(__name__)


def _content_rehash_block_ratio() -> float:
    """재탕 차단 임계값 (후보 본문 문장 중 과거 발행 글과 겹치는 비율)."""
    try:
        value = float(os.getenv("NEWS_CONTENT_REHASH_BLOCK_RATIO", "0.6"))
    except ValueError:
        return 0.6
    return min(1.0, max(0.1, value))


_BANNED_DEFAULT_PHRASES: tuple[str, ...] = (
    "이 이슈는 나와 직접 관련이 없다",
    "정보가 너무 많음",
    "오늘 내 선택 기준이 됩니다",
    "나와 관련 있는지",
    "공식 안내를 확인한다",
    "공식 확인처를 확인한다",
    "행동 필요한지 모름",
    "내 생활과 관련있는지 모름",
    "지금 행동이 필요한지 모름",
    "비용·시간·선택 조건 중 직접 바뀌는 항목을 먼저 봐야 합니다",
    # 영어 전환(2026-07-17) 추가 — 영어 AI-slop 상투어. 한국어 본문에는 사실상
    # 등장하지 않는 어구라 ko 모드에는 무해한 additive 차단이다.
    "in today's fast-paced world",
    "delve into",
    "unlock the power",
    "game-changer",
    "game changer",
    "revolutionize",
    "unleash",
)

_BANNED_TITLE_PHRASES = (
    "충격",
    "경악",
    "발칵",
    "소름",
    "역대급",
    "난리났다",
    "무조건",
    "절대",
    "사람들이 놓친",
    "진짜 변수",
    "유행 뒤에 숨은 돈의 흐름",
    "결국 누가 더 내나",
    "했습니다",
    "됩니다",
    "합니다",
    "입니다",
    "재계는 지금",
    "화제 된 이 반응",
    "사람들이 본 에",
    "사람들이 본 의",
    # 영어 전환(2026-07-17) 추가 — 영어 클릭베이트/AI-slop 제목 어구.
    # 제목 매칭은 소문자 비교(phrase.lower() in lowered_title)라 소문자로 등록.
    "you won't believe",
    "shocking",
    "insane",
    "game-changer",
    "game changer",
    "revolutionize",
    "unleash",
    "in today's fast-paced world",
    "delve into",
    "unlock the power",
)
_MALFORMED_SELECTED_TITLE_PATTERNS = (
    r"^[가-힣A-Za-z0-9·\s]{2,24\]\s+",
    r"화제\s*된\s*이\s*반응",
    r"사람들이\s*본\s*[의에](?:\s|$)",
)
_TELECOM_PLAN_TERMS = (
    "요금제",
    "통신비",
    "선택약정",
    "가족결합",
    "결합할인",
    "멤버십",
    "KT초이스",
    "SKT",
    "SK텔레콤",
    "LG유플러스",
    "LGU+",
)
_GOOD_TITLE_SIGNALS = (
    "확인하세요",
    "먼저 볼",
    "해당될까",
    "증거",
    "조건",
    "체크",
    "방법",
    "줄이는 법",
)
_BANNED_TITLE_SUFFIXES = (
    "KBS 뉴스",
    "조선일보",
    "중앙일보",
    "데일리안",
    "미디어펜",
    "더퍼블릭",
    "v.daum.net",
    "n.news.naver.com",
    ".com",
    ".co.kr",
    ".net",
)
_BANNED_LABEL_FRAGMENTS = _BANNED_TITLE_SUFFIXES
_DEBUG_HTML_MARKERS = (
    "fallback",
    "테스트 후보",
    "raw",
    "scoring",
    "click_potential_score",
    "raw_total_score",
    "is_test_candidate",
)
_DELIVERY_BODY_TERMS = (
    "배달료",
    "최종 결제금액",
    "쿠폰",
    "무료배달",
    "최소주문금액",
    "수수료",
    "라이더",
    "자영업자",
    "소비자",
)
_POLICY_BENEFIT_BODY_TERMS = (
    "지원금",
    "신청",
    "마감",
    "대상 조건",
    "소득 기준",
    "필요 서류",
    "중복 지원",
    "공식 신청 페이지",
    "환급",
    "청년",
)


def _evergreen_auto_publish_allowed() -> bool:
    """Evergreen fallback 자동발행 허용 여부 — 기본 False (news_pipeline과 동일 규칙)."""
    explicit_allow = os.getenv("ALLOW_EVERGREEN_AUTO_PUBLISH", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    forced = os.getenv("FORCE_EVERGREEN_FALLBACK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return explicit_allow or forced


def _visible_text_for_debug_marker_scan(html: str) -> str:
    content = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<[^>]+>", " ", content)
    return " ".join(unescape(content).split())


class NewsQualityGate:
    def evaluate(
        self,
        *,
        selected: ScoredNewsCandidate,
        selected_title: str,
        html: str,
        image_prompt: str = "",
        image_alt_text: str = "",
        labels: list[str] | None = None,
        hashtags: list[str] | None = None,
        dry_run: bool = True,
        news_publish_mode: str = "dry_run",
        extra_allowed_urls: frozenset[str] | tuple[str, ...] = (),
    ) -> dict[str, object]:
        blocking_issues: list[str] = []
        warnings: list[str] = []
        title = (selected_title or "").strip()
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        hook_angle = selected.candidate.raw.get("hook_angle")
        click_potential_score = self._click_potential_score(selected)
        topic_group = str(selected.candidate.raw.get("topic_group") or "general_life")
        content_angle = selected.candidate.raw.get("content_angle")
        content_type = ""
        if isinstance(content_angle, dict):
            content_type = str(content_angle.get("content_type") or "")
        source_type = str(raw.get("source_type") or raw.get("source") or "")
        is_test_candidate = bool(raw.get("is_test_candidate"))
        publish_allowed = raw.get("publish_allowed", True)
        fallback_candidate = (
            source_type.lower() == "fallback"
            or is_test_candidate
            or publish_allowed is False
        )
        evergreen_candidate = source_type.lower() == "evergreen_fallback"
        evergreen_axis = str(raw.get("evergreen_axis") or "")
        target_reader = str(raw.get("target_reader") or "")
        publish_mode_active = (not dry_run) or (news_publish_mode or "").strip().lower() == "publish"

        if fallback_candidate:
            if publish_mode_active:
                blocking_issues.append("fallback_candidate_not_allowed_in_publish_mode")
            else:
                warnings.append("fallback candidate used for dry-run only")
        focus_decision = evaluate_news_focus(
            topic=selected.candidate.topic or "",
            title=title,
            summary=selected.candidate.summary or "",
            raw=raw,
        )
        if not focus_decision.allowed:
            blocking_issues.append(focus_decision.reason)
        commercial_support_signal = bool(raw.get("commercial_support_signal"))
        public_benefit_keyword = str(raw.get("public_benefit_keyword") or "")
        generic_support_keyword = str(raw.get("generic_support_keyword") or "")
        public_benefit_confidence = str(raw.get("public_benefit_confidence") or "none")
        is_stale = bool(raw.get("is_stale"))
        if commercial_support_signal and topic_group == "policy_benefit":
            blocking_issues.append("commercial_support_misclassified_as_policy_benefit")
        if public_benefit_keyword == "지원금" and bool((raw.get("strategy_score_breakdown") or {}).get("official_source_check_needed")):
            blocking_issues.append("generic_support_keyword_requires_official_source")
        if is_stale and (topic_group == "policy_benefit" or public_benefit_keyword or generic_support_keyword):
            blocking_issues.append("stale_policy_or_support_candidate")
        if evergreen_candidate and not evergreen_axis:
            blocking_issues.append("evergreen_fallback_missing_axis")
        # Evergreen fallback 자동발행 기본 금지 (2026-07-02): 범용 evergreen 글이
        # 최신 AI 이슈 글을 대체하는 것을 발행 모드에서 차단한다.
        # ALLOW_EVERGREEN_AUTO_PUBLISH=true 또는 FORCE_EVERGREEN_FALLBACK=true로만 허용.
        if evergreen_candidate and publish_mode_active and not _evergreen_auto_publish_allowed():
            blocking_issues.append("evergreen_fallback_auto_publish_disabled")

        axis_consecutive_count = int(raw.get("axis_consecutive_count") or 0)
        tax_refund_consecutive_count = int(raw.get("tax_refund_consecutive_count") or 0)
        # ai_blog_mode restricts evergreen fallback to a single axis (ai_automation) by
        # design, so axis repetition is guaranteed and intentional, not a diversity risk —
        # this warning/block was written for the multi-axis hybrid blog and would otherwise
        # permanently block evergreen publishing after 2 consecutive uses of the one allowed axis.
        if evergreen_candidate and axis_consecutive_count >= 2 and not ai_blog_mode_from_env():
            if publish_mode_active:
                blocking_issues.append(f"evergreen_axis_repeated_3x:{evergreen_axis}")
            else:
                warnings.append(f"evergreen_axis_repeated_3x:{evergreen_axis}")
        elif evergreen_candidate and axis_consecutive_count == 1 and not ai_blog_mode_from_env():
            warnings.append(f"evergreen_axis_repeated_twice:{evergreen_axis}")
        if evergreen_candidate and evergreen_axis == "tax_refund_support" and tax_refund_consecutive_count >= 1:
            warnings.append("tax_refund_axis_repeated_in_recent_runs")

        # score 게이트: score_relaxed_for_candidate_generation=true 후보는
        # 후보 생성 단계의 의도된 완화이므로 quality_gate에서 중복 차단하지 않는다.
        # 단, 다른 모든 콘텐츠 품질 게이트(golden_pattern/slot_fill/geo/sge 등)는 strict 유지.
        _raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        _score_relaxed = bool(_raw.get("score_relaxed_for_candidate_generation"))
        if selected.total_score < 75:
            if _score_relaxed:
                warnings.append("score_relaxed_below_75_publishing_with_relaxation")
            else:
                blocking_issues.append("total_score_below_75")
        _is_trending_candidate = bool(_raw.get("trending_engine"))
        if click_potential_score < 8:
            if _score_relaxed:
                warnings.append("click_potential_below_8_with_score_relaxation")
            elif _is_trending_candidate and click_potential_score >= 7:
                # 사용자 승인(2026-06-09): 트렌딩 후보는 트렌드 검색량 자체가 실제 클릭
                # 신호 → click>=7 허용. 연예·스포츠·게임 트렌딩 발행 가능.
                warnings.append("click_potential_below_8_trending_signal")
            else:
                blocking_issues.append("click_potential_score_below_8")
        if not hook_angle:
            blocking_issues.append("missing_hook_angle")
        if not title:
            blocking_issues.append("missing_selected_title")
        if title in {"지원금 신청 전 이것부터 확인하세요", "세금 환급 신청 전 이것부터 확인하세요"}:
            warnings.append("selected_title_too_generic")
        # 제목 길이 soft warning: 한국어 45자 기준 유지, 영어 모드는 단어 길이가
        # 길어 70자까지 허용(경고일 뿐 차단 아님 — 2026-07-17 영어 전환).
        _title_length_warn_limit = 70 if is_english_mode() else 45
        if len(title) > _title_length_warn_limit:
            warnings.append("selected_title_longer_than_45_chars")
        if "사람들이 놓친" in title:
            blocking_issues.append("selected_title_uses_repeated_missed_people_pattern")
        if "진짜 변수" in title:
            blocking_issues.append("selected_title_uses_repeated_real_variable_pattern")
        if "유행 뒤에 숨은 돈의 흐름" in title:
            blocking_issues.append("selected_title_uses_repeated_hidden_money_flow_pattern")
        if "결국 누가 더 내나" in title:
            blocking_issues.append("selected_title_uses_repeated_who_pays_pattern")
        if self._has_bad_subject_particle(title):
            blocking_issues.append("selected_title_bad_subject_particle")
        if content_type == "viral_issue_decode" and "평점보다 먼저 볼 포인트" in title:
            blocking_issues.append("selected_title_low_value_viral_rating_formula")
        for pattern in _MALFORMED_SELECTED_TITLE_PATTERNS:
            if re.search(pattern, title):
                blocking_issues.append("selected_title_malformed_phrase")
                break
        if content_type == "viral_issue_decode" and self._is_telecom_plan_topic(selected, title=title):
            blocking_issues.append("telecom_plan_topic_using_viral_reaction_template")
        source_context = self._title_source_context(selected)
        integrity = audit_title_integrity(
            title,
            content_type=content_type,
            topic_group=topic_group,
            source_text=source_context,
        )
        for issue in integrity.get("blocking_issues", []):
            if issue == "missing_title":
                blocking_issues.append("missing_selected_title")
            elif issue == "bad_subject_particle":
                blocking_issues.append("selected_title_bad_subject_particle")
            elif issue == "low_value_viral_rating_title":
                blocking_issues.append("selected_title_low_value_viral_rating_formula")
            elif issue == "telecom_plan_topic_using_viral_reaction_template":
                blocking_issues.append("telecom_plan_topic_using_viral_reaction_template")
            elif str(issue).startswith("source_series_name_leaked:"):
                blocking_issues.append(f"title_integrity_{issue}")
            else:
                blocking_issues.append(f"title_integrity_{issue}")

        if topic_group == "policy_benefit" and "유행" in title:
            blocking_issues.append("policy_benefit_title_contains_trend_expression")
        if re.search(r"대상\s*조(?!건)", title):
            blocking_issues.append("selected_title_has_truncated_word")

        # content_type 문구 누수 차단: policy/tax 계열 문구가 다른 content_type에 섞이지 않게
        # "신청 전", "대상 조건", "환급", "지원금"은 policy_benefit/tax_refund/policy_deadline 계열에서만 허용
        _policy_phrase_in_title = any(
            phrase in title for phrase in ("신청 전", "대상 조건", "환급", "지원금")
        )
        _policy_eligible_ct = content_type in {"policy_deadline", "tax_refund", "policy_benefit"}
        _policy_eligible_tg = topic_group in {"policy_benefit"}
        if _policy_phrase_in_title and not (_policy_eligible_ct or _policy_eligible_tg):
            blocking_issues.append(
                f"policy_phrase_leak_in_non_policy_title:{content_type or 'missing'}"
            )

        # blogspot 운영팁 문구가 뉴스 제목에 누수되지 않도록 차단
        if any(phrase in title for phrase in ("블로그스팟 내부링크", "내부링크 넣기", "블로그 운영")):
            blocking_issues.append("blogspot_growth_phrase_in_news_title")

        # refund 제목 누수 차단: 원문/topic_group이 refund_consumer가 아니면 환불 제목 금지
        # 개인정보(privacy_security) 이슈에 "환불 기다리기" 같은 제목이 붙는 문제 방지
        _refund_phrase_in_title = any(
            phrase in title for phrase in ("환불 기다리", "환불 지연", "환불 거부", "환불 받기", "환불 신청")
        )
        if _refund_phrase_in_title:
            raw_topic_text = (selected.candidate.topic or "") + " " + (selected.candidate.summary or "")
            orig_topic = str((selected.candidate.raw or {}).get("original_topic") or "")
            raw_topic_text += " " + orig_topic
            if topic_group != "refund_consumer" or not any(
                kw in raw_topic_text for kw in ("환불", "결제 취소", "결제취소", "취소 분쟁", "보상")
            ):
                blocking_issues.append(
                    f"refund_phrase_leak_in_non_refund_title:{topic_group or 'missing'}"
                )

        # title-body topic match: title에 환불이 있는데 원문에는 환불 키워드 없으면 차단
        # 또는 title에 원문 핵심 키워드(개인정보/유출 등)가 누락된 채 일반 환불 제목이면 차단
        if topic_group == "privacy_security":
            if "환불" in title and "개인정보" not in title and "본인확인" not in title:
                blocking_issues.append("privacy_topic_with_refund_title_no_privacy_keyword")

        # today_relevance / issue_specificity 평가 (오늘의 이슈 자동발행 핵심 기준)
        today_relevance_score = self._compute_today_relevance(selected)
        issue_specificity_score = self._compute_issue_specificity(selected)
        original_issue_preservation_score = self._compute_original_issue_preservation(
            selected, title=title,
        )
        reader_question_potential_score = self._compute_reader_question_potential(selected)
        raw["today_relevance_score"] = today_relevance_score
        raw["issue_specificity_score"] = issue_specificity_score
        raw["original_issue_preservation_score"] = original_issue_preservation_score
        raw["reader_question_potential_score"] = reader_question_potential_score

        # 발행 HTML에 AI 내부 라벨이 사용자 노출 영역(h1/h2/h3/p)에 노출되면 차단
        # id 속성은 보이지 않으므로 허용. visible text만 검사.
        _ai_smell_visible = (
            "AI Overviews 핵심 답변",  # 옛 h2
            "AI가 인용하기 좋은",  # 옛 h2
            "AI 검색 대응",
            "AI가 요약",
            "생성형 AI용 답변",
            "구조화된 AI 답변",
            "SGE 답변",
            "GEO 블록",
            "LLM 응답",
        )
        if any(label in html for label in _ai_smell_visible):
            blocking_issues.append("ai_internal_label_visible_in_html")

        # 외부 네이버 CTA가 남아 있으면 새 AI Blogspot 운영에서는 경고한다.
        naver_cta_present = "blog.naver.com" in html or 'id="NAVER_BLOG_CTA"' in html
        if naver_cta_present:
            warnings.append("external_naver_cta_present")

        # title 구체명사 요구 — 모든 뉴스 자동발행 후보에 적용
        # discovery_engine 후보는 entity-verified이므로 면제
        _ENTITY_TITLE_SET = (
            "삼성", "쿠팡", "네이버", "카카오", "유튜브", "넷플릭스", "티빙",
            "쿠팡이츠", "배민", "토스", "당근", "애플", "구글", "메타",
            "KT", "SKT", "LGU", "LG유플", "SK텔레콤",
            "정부", "공정위", "금감원", "국세청", "복지부", "고용부", "교육부",
            "개인정보위", "소비자원", "방통위", "한국인터넷진흥원",
            "신한", "국민", "하나", "농협", "현대", "기아", "포스코",
            "디즈니", "왓챠", "웨이브", "넷마블", "엔씨소프트", "엔씨",
            "롯데", "신세계", "이마트", "GS", "CJ", "한화",
            "넷플릭스", "DART", "공시", "노조", "노동조합",
        )
        title_has_source_entity = self._title_has_source_entity(title, selected)
        title_has_entity = (
            any(ch in title for ch in _ENTITY_TITLE_SET)
            or title_has_source_entity
            or bool(raw.get("discovery_engine"))
        )
        raw["title_has_specific_entity"] = bool(title_has_entity)
        if not title_has_entity and not isinstance(raw.get("public_benefit_keyword"), str):
            blocking_issues.append("title_has_no_specific_entity")

        title_body_alignment = self._title_body_alignment(title=title, html=html)
        if title_body_alignment["required_terms"] and title_body_alignment["missing_terms"]:
            blocking_issues.append(
                "title_body_entity_mismatch:"
                + ",".join(title_body_alignment["missing_terms"][:3])
            )

        # 추가: 주어가 없는 "확인할 것"/"먼저 확인" 단독 제목 차단
        # discovery 후보는 면제 (entity 검증됨)
        if not bool(raw.get("discovery_engine")):
            generic_only_phrase = (
                title.startswith("확인 ") or title.endswith("확인할 것")
                or title.endswith("확인 전에 볼 것")
                or "신청 전 이것부터" in title
                # "비교 전에 확인할 조건" 같은 transformer 변질 제목 차단
                or "비교 전에 확인할 조건" in title
            )
            if generic_only_phrase:
                blocking_issues.append("generic_title_without_subject")

        # today_relevance는 실뉴스 strict 기준이다. Evergreen fallback은 오늘성 대신
        # 반복 검색 수요와 evergreen 전용 focus/reader-value 게이트로 평가한다.
        if today_relevance_score < 7:
            if evergreen_candidate:
                warnings.append(f"evergreen_today_relevance_below_7:{today_relevance_score}")
            else:
                blocking_issues.append(
                    f"today_relevance_below_7:{today_relevance_score}"
                )
        # issue_specificity / original_issue_preservation 임계값을 7 → 6으로 보수적 완화.
        # 사유: 5일 연속 자동 발행 0건 — 7 임계가 publishable 후보를 과도 차단.
        # 6 미만은 여전히 차단해 generic 변질은 방어한다.
        practical_money_reframe = content_type == "money_checklist" or topic_group == "delivery_money"
        ai_evergreen_reframe = evergreen_candidate and (
            content_type == "ai_work_tip"
            or topic_group == "ai_work"
            or evergreen_axis == "ai_automation"
        )
        if issue_specificity_score < 6:
            if ai_evergreen_reframe:
                warnings.append(
                    f"ai_evergreen_issue_specificity_below_6:{issue_specificity_score}"
                )
            else:
                blocking_issues.append(
                    f"issue_specificity_below_6:{issue_specificity_score}"
                )
        elif issue_specificity_score < 7:
            warnings.append(
                f"issue_specificity_below_7:{issue_specificity_score}"
            )
        if original_issue_preservation_score < 6:
            if ai_evergreen_reframe:
                warnings.append(
                    "ai_evergreen_original_issue_preservation_below_6:"
                    f"{original_issue_preservation_score}"
                )
            elif practical_money_reframe and issue_specificity_score >= 6:
                warnings.append(
                    "original_issue_preservation_below_6_practical_reframe:"
                    f"{original_issue_preservation_score}"
                )
            else:
                blocking_issues.append(
                    f"original_issue_preservation_below_6:{original_issue_preservation_score}"
                )
        elif original_issue_preservation_score < 7:
            warnings.append(
                f"original_issue_preservation_below_7:{original_issue_preservation_score}"
            )
        if reader_question_potential_score < 7:
            warnings.append(
                f"reader_question_potential_below_7:{reader_question_potential_score}"
            )

        lowered_title = title.lower()
        for phrase in _BANNED_TITLE_PHRASES:
            if phrase.lower() in lowered_title:
                blocking_issues.append(f"banned_title_phrase:{phrase}")
        for suffix in _BANNED_TITLE_SUFFIXES:
            if suffix.lower() in lowered_title:
                blocking_issues.append(f"title_contains_source_suffix:{suffix}")

        lowered_html = html.lower()
        visible_html_text = _visible_text_for_debug_marker_scan(html).lower()
        for marker in _DEBUG_HTML_MARKERS:
            if marker.lower() in visible_html_text:
                blocking_issues.append(f"html_contains_debug_marker:{marker}")

        if not re.search(r"<h1\b[^>]*>.*?</h1>", html, flags=re.IGNORECASE | re.DOTALL):
            blocking_issues.append("missing_h1")
        if re.search(r"<meta\b", html, flags=re.IGNORECASE):
            warnings.append("html_contains_body_meta_tag")
        if "application/ld+json" not in lowered_html:
            blocking_issues.append("missing_json_ld")
        faq_section_present = bool(re.search(r'<section\b[^>]*class=["\'][^"\']*faq[^"\']*["\']', html, flags=re.IGNORECASE))
        faq_h3_count = len(re.findall(r"<h3\b[^>]*>.*?</h3>", html, flags=re.IGNORECASE | re.DOTALL))
        faq_json_ld_present = '"@type": "FAQPage"' in html or '"@type":"FAQPage"' in html
        faq_answers = self._faq_answers(html)
        if not faq_section_present:
            blocking_issues.append("missing_faq_section")
        if faq_h3_count < 3:
            blocking_issues.append("faq_h3_count_below_3")
        if not faq_json_ld_present:
            blocking_issues.append("missing_faqpage_json_ld")
        if len(faq_answers) < 3 or any(len(answer) < 20 for answer in faq_answers[:3]):
            blocking_issues.append("faq_answer_too_short")
        answer_coverage = answer_engine_coverage(html)
        if not bool(answer_coverage.get("ai_overview_target_answer_present")):
            blocking_issues.append("missing_ai_overview_target_answer")
        if not bool(answer_coverage.get("issue_context_present")):
            blocking_issues.append("missing_issue_context_block")
        if not bool(answer_coverage.get("intent_answer_present")):
            blocking_issues.append("missing_intent_answer_block")
        if int(answer_coverage.get("intent_qa_count") or 0) < 3:
            blocking_issues.append("intent_qa_count_below_3")
        # PEOPLE_ALSO_ASK_BLOCK 요건 제거(2026-07-09) — 답 없는 검색어 나열이라 읽는
        # 값이 없는 순수 SEO 필러로 판단, 더 이상 생성/요구하지 않음(answer_engine_policy.py).
        if not bool(answer_coverage.get("confirmed_vs_check_needed_present")):
            blocking_issues.append("missing_confirmed_vs_check_needed_block")
        if not bool(answer_coverage.get("source_trust_block_present")):
            blocking_issues.append("missing_source_trust_block")
        if not bool(answer_coverage.get("blogposting_json_ld_present")):
            blocking_issues.append("missing_blogposting_json_ld")
        final_html_audit = audit_final_html_quality(
            html,
            topic=selected.candidate.topic or "",
            content_type=content_type,
            topic_group=topic_group,
        )
        blocking_issues.extend(str(issue) for issue in final_html_audit.get("issues", []))
        warnings.extend(str(warning) for warning in final_html_audit.get("warnings", []))
        issue_context_markers = ("확인된", "아직 확인", "관전 포인트", "반응이 갈린", "확산 이유")
        if not any(marker in html for marker in ("예시", "체크리스트", "오늘 바로 할 것")) and not (
            content_type in {"viral_issue_decode", "trend_decode", "today_issue_explainer"}
            and any(marker in html for marker in issue_context_markers)
        ):
            warnings.append("article_lacks_example_or_checklist")
        hero_summary_present = "hero-summary-box" in html or "yomi-lede" in html
        target_reader_box_present = "target-reader-box" in html
        core_message_box_present = "core-message-box" in html or "핵심 관점" in html or "yomi-thesis" in html
        key_fact_cards_present = "key-fact-cards" in html or "yomi-thesis" in html or "yomi-lens" in html
        checklist_box_present = ("checklist" in html and "체크리스트" in html) or "yomi-list" in html
        warning_box_present = 'class="warning' in html or "놓치기 쉬운" in html or "yomi-note" in html
        visual_faq_present = "faq-card" in html or "yomi-faq" in html
        yomi_judgment_present = "yomi-judgment-box" in html or "핵심 관점" in html or "yomi-thesis" in html
        misconception_box_present = "misconception-box" in html or "yomi-risk" in html
        quick_decision_table_present = "quick-decision-table" in html or "yomi-risk" in html
        if content_type and not hero_summary_present:
            warnings.append("visual_missing_hero_summary_box")
        if content_type and not target_reader_box_present:
            warnings.append("missing_target_reader_box")
        if content_type and not core_message_box_present:
            warnings.append("missing_core_message_box")
        if content_type and not key_fact_cards_present:
            warnings.append("visual_missing_key_fact_cards")
        if content_type and not checklist_box_present and content_type not in {"today_issue_explainer", "trend_decode"}:
            warnings.append("visual_missing_checklist_box")
        if content_type and not warning_box_present:
            warnings.append("visual_missing_warning_box")
        if content_type and not visual_faq_present:
            warnings.append("visual_faq_not_card_style")
        if content_type and not yomi_judgment_present:
            warnings.append("missing_yomi_judgment_box")
        if content_type and not misconception_box_present:
            warnings.append("missing_misconception_box")
        if content_type and not quick_decision_table_present:
            warnings.append("missing_quick_decision_table")
        reader_value = self._reader_value_score(
            title=title,
            html=html,
            content_type=content_type,
            topic_group=topic_group,
        )
        reader_value_score = int(reader_value.get("score", 0))
        if reader_value_score < 65:
            blocking_issues.append("reader_value_score_below_65")
        elif reader_value_score < 75:
            warnings.append("reader_value_score_below_75")
        image_prompt_present = bool((image_prompt or "").strip())
        image_alt_text_present = bool((image_alt_text or "").strip())
        if not image_prompt_present:
            blocking_issues.append("missing_image_prompt")
        if not image_alt_text_present:
            blocking_issues.append("missing_image_alt_text")
        if self._image_prompt_has_forbidden_terms(image_prompt):
            blocking_issues.append("image_prompt_contains_forbidden_visual_instruction")
        cover_coverage = cover_image_coverage(html)
        if not bool(cover_coverage.get("cover_image_present")):
            warnings.append("cover_image_missing")
            if cover_image_required_from_env():
                blocking_issues.append("missing_cover_image")
        elif not bool(cover_coverage.get("cover_image_public_url")):
            warnings.append("cover_image_not_public_url")
            if cover_image_required_from_env():
                blocking_issues.append("cover_image_not_public_url")
        cleaned_labels = self._clean_labels(labels or [])
        label_count = len(cleaned_labels)
        if label_count < 2:
            blocking_issues.append("labels_below_2")
        if label_count > MAX_BLOGSPOT_LABELS:
            blocking_issues.append(f"labels_above_{MAX_BLOGSPOT_LABELS}")
        if any(self._label_has_banned_fragment(label) for label in cleaned_labels):
            blocking_issues.append("labels_contain_banned_fragment")
        cleaned_hashtags = self._clean_hashtags(hashtags or [])
        hashtag_count = len(cleaned_hashtags)
        if hashtag_count < 1:
            blocking_issues.append("hashtags_below_1")
        if hashtag_count > MAX_CONTENT_HASHTAGS:
            blocking_issues.append(f"hashtags_above_{MAX_CONTENT_HASHTAGS}")
        if any(self._label_has_banned_fragment(tag) for tag in cleaned_hashtags):
            blocking_issues.append("hashtags_contain_banned_fragment")
        hashtag_mismatch_terms = self._hashtag_mismatch_terms(content_type, cleaned_hashtags)
        if hashtag_mismatch_terms:
            if content_type == "tax_refund":
                blocking_issues.append("hashtags_mixed_with_wrong_content_type")
            else:
                warnings.append("hashtags_mixed_with_wrong_content_type")
        if content_type == "money_checklist":
            if "가상의 계산 예시" not in html:
                blocking_issues.append("money_checklist_missing_example_box")
            if "최종 결제금액" not in html:
                blocking_issues.append("money_checklist_missing_final_payment_amount")
        if "논란" in title and "결국 누가 더 내나" in title:
            blocking_issues.append("selected_title_news_commentary_style")
        elif "논란" in title and not any(token in title for token in ("왜", "먼저", "확인", "아끼", "손해", "결제창", "이유", "법")):
            warnings.append("selected_title_news_like")

        plain_text = re.sub(r"<[^>]+>", " ", html)
        plain_text = " ".join(plain_text.split())
        recommendation_policy = evaluate_news_recommendation_policy(
            title=title,
            topic=selected.candidate.topic or "",
            html=html,
            content_type=content_type,
            topic_group=topic_group,
            raw=raw,
        )
        blocking_issues.extend(str(issue) for issue in recommendation_policy.get("blocking_issues", []))
        warnings.extend(str(warning) for warning in recommendation_policy.get("warnings", []))
        if has_unverified_experience_or_income_claim(html):
            blocking_issues.append("unverified_experience_or_income_claim")
        if topic_group == "ai_work" or content_type == "ai_work_tip":
            blocking_issues.extend(self._ai_blog_risk_issues(plain_text))
        # AI 글 저장 가치 게이트 (2026-07-02): 발행 모드에서 표/프롬프트/비용 전략 같은
        # "저장하고 다시 오는" 자산이 없는 AI 글의 발행을 차단한다.
        _is_ai_family = (
            topic_group == "ai_work"
            or topic_group.startswith("ai_")
            or content_type.startswith("ai_")
        )
        if _is_ai_family and publish_mode_active:
            _save_blocking, _save_warnings = self._ai_save_value_issues(
                html=html, content_type=content_type,
            )
            blocking_issues.extend(_save_blocking)
            warnings.extend(_save_warnings)
        blocking_issues.extend(
            self._ai_tool_topic_specificity_issues(
                title=title,
                topic=selected.candidate.topic or "",
                plain_text=plain_text,
                content_type=content_type,
                topic_group=topic_group,
            )
        )
        article_focus = self._article_focus_score(
            title=title,
            html=html,
            plain_text=plain_text,
            content_type=content_type,
            topic_group=topic_group,
            hashtags=cleaned_hashtags,
        )
        article_focus_score = int(article_focus.get("score", 0))
        if article_focus_score < 60:
            blocking_issues.append("article_focus_score_below_60")
        elif article_focus_score < 70:
            warnings.append("article_focus_score_below_70")
        if evergreen_candidate and article_focus_score < 70:
            blocking_issues.append("evergreen_article_focus_score_below_70")
        if evergreen_candidate and reader_value_score < 75:
            blocking_issues.append("evergreen_reader_value_score_below_75")
        if evergreen_candidate and not any(term in f"{target_reader} {plain_text[:800]}" for term in ("30~50", "30대", "40대", "50대", "직장인")):
            warnings.append("evergreen_target_reader_not_30_50_worker_focused")
        if len(plain_text) < 800:
            blocking_issues.append("article_body_too_short")

        related_ai_blog_box_present = "related-ai-blog-box" in html
        related_ai_blog_url_present = "holyyomiai.blogspot.com" in html
        related_ai_link_safe = 'target="_blank"' in html and 'rel="noopener noreferrer"' in html
        if related_ai_blog_box_present and not related_ai_blog_url_present:
            warnings.append("related_ai_blog_url_missing_in_box")
        if related_ai_blog_box_present and not related_ai_link_safe:
            warnings.append("related_ai_blog_link_missing_safe_attrs")
        if content_type == "tax_refund" and "구체 상황 예시" in html and "독자 상황 예시" in html:
            warnings.append("tax_refund_duplicate_example_sections")
        related_ai_box_match = re.search(r'<section class="related-ai-blog-box".*?</section>', html, re.DOTALL)
        if content_type == "tax_refund" and related_ai_box_match and "지원금" in related_ai_box_match.group():
            warnings.append("tax_refund_cta_contains_지원금")

        external_anchor_count = count_external_anchor_links(html, extra_allowed_urls=extra_allowed_urls)
        if external_anchor_count and publish_mode_active:
            blocking_issues.append("external_outbound_anchor_present")
        elif external_anchor_count:
            warnings.append("external_outbound_anchor_present")

        if not isinstance(hook_angle, dict) or not str(hook_angle.get("safe_title_keyword", "")).strip():
            blocking_issues.append("missing_safe_title_keyword")

        raw_topic_count = 0
        raw_topic = (selected.candidate.topic or "").strip()
        if len(raw_topic) >= 20 and not evergreen_candidate:
            escaped_topic = (
                raw_topic.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            # escaped와 raw가 동일하면 double-count 방지
            if escaped_topic == raw_topic:
                raw_topic_count = html.count(raw_topic)
            else:
                raw_topic_count = html.count(raw_topic) + html.count(escaped_topic)
            if content_type == "viral_issue_decode":
                if raw_topic_count >= 14:
                    warnings.append("viral_raw_topic_repeated_many_times")
            elif raw_topic_count >= 6:
                # title + JSON-LD headline + h1 = 3 (필수) + 자연스러운 본문 사용 1-2회 = 4-5 까지 허용
                # 6 이상은 spam 신호
                blocking_issues.append("raw_topic_repeated_in_html")

        if "유형: default" in html or "type: default" in lowered_html:
            blocking_issues.append("default_content_profile_used")

        default_phrase_hits: list[str] = [
            phrase for phrase in _BANNED_DEFAULT_PHRASES if phrase in html
        ]
        if default_phrase_hits:
            for hit in default_phrase_hits:
                blocking_issues.append(f"banned_default_phrase_detected:{hit[:40]}")

        # ── HTML entity artifact 체크 ────────────────────────────────────────
        # Blogger가 렌더링하지 못하는 entity fragment가 독자 화면에 그대로 노출되는 것을 차단.
        # 1) &amp;#숫자 — 이중 escape (독자에게 "&amp;#9989" 텍스트로 표시됨)
        # 2) &#숫자 (세미콜론 없음) — 불완전 entity (브라우저 처리 불일치, 텍스트 노출)
        # 10진(&#39)과 16진(&#x27) 표기 모두 잡는다 — hex는 2026-07-16 실측에서
        # LLM 출력에 등장 확인, 기존 10진 전용 정규식의 블라인드 스팟이었다.
        _dbl_escape_re = re.compile(r'&amp;#(?:[xX][0-9a-fA-F]+|\d+)')
        # (?!...|;): 자릿수 문자 또는 ; 가 이어지면 더 긴 entity의 중간이므로 제외
        # 예: &#9989; / &#x27; → 다음이 ; → 제외됨 (정상 entity)
        # 예: &#9989 공백 / &#x27 공백 → 차단 (세미콜론 없는 entity)
        _bare_entity_re = re.compile(r'&#(?:[xX][0-9a-fA-F]+(?![0-9a-fA-F]|;)|\d+(?!\d|;))')
        _html_entity_double_escaped = bool(_dbl_escape_re.search(html))
        _html_entity_bare = bool(_bare_entity_re.search(html))
        html_entity_artifact_detected = _html_entity_double_escaped or _html_entity_bare
        html_entity_artifact_absent = not html_entity_artifact_detected
        if _html_entity_double_escaped:
            blocking_issues.append("broken_html_entity_double_escape")
        if _html_entity_bare:
            blocking_issues.append("broken_html_entity_no_semicolon")

        if self.is_delivery_money_issue(selected):
            delivery_term_count = sum(1 for term in _DELIVERY_BODY_TERMS if term in html)
            if delivery_term_count < 3:
                blocking_issues.append("delivery_money_specific_terms_missing")

        if topic_group == "policy_benefit":
            if content_type == "tax_refund":
                policy_term_count = sum(1 for term in ("환급", "조회", "홈택스", "손택스", "필요 서류", "환급 계좌", "공식 확인처") if term in html)
            else:
                policy_term_count = sum(1 for term in _POLICY_BENEFIT_BODY_TERMS if term in html)
            if policy_term_count < 4:
                blocking_issues.append("policy_benefit_specific_terms_missing")

        if content_type == "policy_deadline":
            policy_topic = str(public_benefit_keyword or generic_support_keyword or selected.candidate.topic or "").strip()
            policy_checklist_count = self._policy_checklist_count(html)
            policy_density_terms = self._policy_information_density_terms(html)
            if policy_checklist_count < 5:
                blocking_issues.append("policy_deadline_checklist_below_5")
            if self._policy_required_term_count(html) < 3:
                blocking_issues.append("policy_deadline_required_info_missing")
            if len(policy_density_terms) < 5:
                blocking_issues.append("policy_deadline_information_density_below_5")
            if policy_topic and policy_topic not in " ".join(self._faq_questions(html)):
                blocking_issues.append("policy_deadline_faq_not_topic_specific")
            if "핵심 정보표" not in html and "<table" not in lowered_html:
                blocking_issues.append("policy_deadline_missing_info_table")
            if html.count("확인해야") >= 12 or html.count("확인한다") >= 18:
                warnings.append("policy_deadline_repeats_generic_confirmation_phrase")
            meta_description_text = self._meta_description(html)
            if policy_topic and policy_topic not in meta_description_text:
                warnings.append("policy_deadline_meta_description_too_generic")
        if content_type == "tax_refund" or is_tax_refund_text(f"{public_benefit_keyword} {selected.candidate.topic}"):
            tax_forbidden_count = sum(1 for term in ("사용처", "지역상품권", "바우처", "제외 업종", "가맹점", "카드 포인트") if term in html)
            if tax_forbidden_count >= 2:
                blocking_issues.append("tax_refund_contains_support_usage_terms")
            elif tax_forbidden_count == 1:
                warnings.append("tax_refund_contains_support_usage_term")
            tax_questions = " ".join(self._faq_questions(html))
            if tax_questions and not any(term in tax_questions for term in ("환급", "홈택스", "손택스", "조회")):
                warnings.append("tax_refund_faq_not_subtype_specific")
            tax_action_terms = self._tax_refund_action_terms(html)
            if len(tax_action_terms) < 5:
                blocking_issues.append("tax_refund_action_depth_missing")
            if "구체 상황 예시" not in html:
                warnings.append("tax_refund_missing_concrete_situation_example")
        else:
            tax_action_terms = []

        if content_type == "viral_issue_decode":
            viral_risk_flags = list(raw.get("viral_risk_flags") or [])
            viral_safety_sc = int(raw.get("viral_safety_score") or 0)
            if viral_risk_flags:
                blocking_issues.append(f"viral_risk_flags_detected:{','.join(viral_risk_flags[:3])}")
            if viral_safety_sc < 40:
                blocking_issues.append("viral_safety_score_too_low")
            viral_banned_patterns = ("충격 근황", "결국 터졌다", "소름 돋는 이유", "사생활 논란 총정리", "루머 진짜일까", "난리난")
            for pat in viral_banned_patterns:
                if pat in title:
                    blocking_issues.append(f"viral_banned_title_pattern:{pat}")
            if "반응" not in html and "이슈" not in html and "팬덤" not in html and "OTT" not in html:
                warnings.append("viral_issue_decode_missing_core_keywords_in_body")
            if not any(marker in html for marker in ("evergreen", "내부링크", "가이드", "관련")):
                warnings.append("viral_issue_decode_missing_evergreen_link_suggestion")

        cooldown = int(selected.candidate.raw.get("cooldown_penalty") or 0)
        if cooldown > 0:
            if evergreen_candidate:
                warnings.append(f"evergreen_rotation_penalty_applied:{evergreen_axis}(penalty={cooldown})")
            elif cooldown >= 20:
                warnings.append(f"topic_group_repeated_heavily:{topic_group}(penalty={cooldown})")
            else:
                warnings.append(f"topic_group_repeated:{topic_group}(penalty={cooldown})")

        relaxed_top_issue_blockers = self._relax_top_issue_publish_blockers(
            blocking_issues=blocking_issues,
            warnings=warnings,
            publish_mode_active=publish_mode_active,
            fallback_candidate=fallback_candidate,
            source_type=source_type,
            content_type=content_type,
            topic_group=topic_group,
            selected=selected,
            reader_value_score=reader_value_score,
            article_focus_score=article_focus_score,
            title_has_source_entity=title_has_source_entity,
            raw_topic_count=raw_topic_count,
        )

        # --- 재탕(near-duplicate) 감지 — 과거 발행 글과 본문 문장 겹침 비율 ---
        # LLM 보강 실패로 정적 템플릿 폴백된 글이 사실상 같은 본문으로 다시
        # 발행되는 것을 차단한다. 지문 없는 과거 레코드(기능 도입 전)는 비교에서
        # 제외되므로 기존 이력과의 오탐은 없다.
        content_fingerprint = self._sentence_fingerprints(html)
        content_rehash = {"ratio": 0.0, "matched_title": "", "compared_records": 0}
        try:
            content_rehash = self._max_history_overlap(content_fingerprint)
        except Exception as _sim_exc:  # noqa: BLE001 — 감지 실패는 비치명(게이트 완화 아님)
            logger.warning("content rehash check failed (skipped): %s", _sim_exc)
        _rehash_block_ratio = _content_rehash_block_ratio()
        if publish_mode_active and content_rehash["ratio"] >= _rehash_block_ratio:
            blocking_issues.append(
                f"content_near_duplicate_of_recent_post:{content_rehash['ratio']:.2f}"
            )

        practical_title_bonus = 8 if any(token in title for token in _GOOD_TITLE_SIGNALS) else 0
        score = max(0, min(100, 100 + practical_title_bonus - (len(set(blocking_issues)) * 12) - (len(warnings) * 5)))
        result = {
            "content_fingerprint": content_fingerprint,
            "content_rehash_ratio": content_rehash["ratio"],
            "content_rehash_matched_title": content_rehash["matched_title"],
            "content_rehash_compared_records": content_rehash["compared_records"],
            "passed": not blocking_issues,
            "score": score,
            "topic_group": topic_group,
            "content_type": content_type,
            "title_body_alignment": title_body_alignment,
            "faq_count": faq_h3_count,
            "faqpage_json_ld_present": faq_json_ld_present,
            "answer_engine_coverage": answer_coverage,
            "final_html_audit": final_html_audit,
            "ai_overview_target_answer_present": answer_coverage.get("ai_overview_target_answer_present"),
            "issue_context_present": answer_coverage.get("issue_context_present"),
            "intent_answer_present": answer_coverage.get("intent_answer_present"),
            "intent_qa_count": answer_coverage.get("intent_qa_count"),
            "people_also_ask_present": answer_coverage.get("people_also_ask_present"),
            "people_also_ask_count": answer_coverage.get("people_also_ask_count"),
            "confirmed_vs_check_needed_present": answer_coverage.get("confirmed_vs_check_needed_present"),
            "source_trust_block_present": answer_coverage.get("source_trust_block_present"),
            "blogposting_json_ld_present": answer_coverage.get("blogposting_json_ld_present"),
            "hero_summary_box_present": hero_summary_present,
            "target_reader_box_present": target_reader_box_present,
            "core_message_box_present": core_message_box_present,
            "key_fact_cards_present": key_fact_cards_present,
            "checklist_box_present": checklist_box_present,
            "warning_box_present": warning_box_present,
            "yomi_judgment_present": yomi_judgment_present,
            "misconception_box_present": misconception_box_present,
            "quick_decision_table_present": quick_decision_table_present,
            "reader_value_score": reader_value_score,
            "reader_value_breakdown": reader_value.get("breakdown", {}),
            "article_focus_score": article_focus_score,
            "article_focus_breakdown": article_focus.get("breakdown", {}),
            "recommendation_policy": recommendation_policy,
            "ai_recommender_score": recommendation_policy.get("ai_recommender_score"),
            "shareability_score": recommendation_policy.get("shareability_score"),
            "policy_specificity_score": recommendation_policy.get("policy_specificity_score"),
            "policy_information_density_terms": self._policy_information_density_terms(html) if content_type == "policy_deadline" else [],
            "policy_information_density_count": len(self._policy_information_density_terms(html)) if content_type == "policy_deadline" else 0,
            "tax_refund_action_terms": tax_action_terms if content_type == "tax_refund" else [],
            "tax_refund_action_term_count": len(tax_action_terms) if content_type == "tax_refund" else 0,
            "image_prompt_present": image_prompt_present,
            "image_alt_text_present": image_alt_text_present,
            "cover_image_present": cover_coverage.get("cover_image_present"),
            "cover_image_public_url": cover_coverage.get("cover_image_public_url"),
            "cover_image_block_present": cover_coverage.get("cover_image_block_present"),
            "label_count": label_count,
            "hashtags": cleaned_hashtags,
            "hashtag_count": hashtag_count,
            "hashtag_mismatch_terms": hashtag_mismatch_terms,
            "related_ai_blog_box_present": related_ai_blog_box_present,
            "related_ai_blog_url_present": related_ai_blog_url_present,
            "external_anchor_count": external_anchor_count,
            "external_anchor_absent": external_anchor_count == 0,
            "source_type": source_type,
            "news_focus_allowed": focus_decision.allowed,
            "news_focus_block_reason": focus_decision.reason,
            "news_focus_matched_terms": list(focus_decision.matched_terms),
            "is_test_candidate": is_test_candidate,
            "fallback_candidate": fallback_candidate,
            "evergreen_candidate": evergreen_candidate,
            "evergreen_axis": evergreen_axis,
            "target_reader": target_reader,
            "commercial_support_signal": commercial_support_signal,
            "generic_support_keyword": generic_support_keyword,
            "public_benefit_keyword": public_benefit_keyword,
            "public_benefit_confidence": public_benefit_confidence,
            "stale_penalty_applied": bool(raw.get("stale_penalty_applied")),
            "public_benefit_promotion_blocked": bool(raw.get("public_benefit_promotion_blocked")),
            "top_issue_relaxed_blocking_issues": relaxed_top_issue_blockers,
            "raw_topic_count": raw_topic_count,
            "blocking_issues": list(dict.fromkeys(blocking_issues)),
            "warnings": warnings,
            "default_phrase_detected": bool(default_phrase_hits),
            "default_phrase_hits": default_phrase_hits,
            "html_entity_artifact_absent": html_entity_artifact_absent,
            "broken_html_entity_detected": html_entity_artifact_detected,
        }
        result["publish_preview_scorecard"] = build_publish_preview_scorecard(result)
        return result

    @staticmethod
    def _sentence_fingerprints(html: str) -> list[str]:
        from blogspot_automation.services.content_similarity_service import sentence_fingerprints
        return sentence_fingerprints(html)

    @staticmethod
    def _max_history_overlap(candidate_fingerprints: list[str]) -> dict[str, object]:
        """최근 발행 이력(지문 보유 레코드)과의 최대 본문 겹침 비율."""
        from blogspot_automation.services.content_similarity_service import max_overlap_ratio
        from blogspot_automation.services.publish_history_service import PublishHistoryService
        records = PublishHistoryService().recent_records(limit=60, published_only=True)
        return max_overlap_ratio(candidate_fingerprints, records)

    @staticmethod
    def _ai_save_value_issues(*, html: str, content_type: str) -> tuple[list[str], list[str]]:
        """AI 글 저장 가치 검증 — (blocking, warnings).

        blocking: 표 0개, 복사형 프롬프트 자산 3개 미만(프롬프트 관련 타입), 비용 언급 전무.
        warnings: 체크리스트 부재, 프롬프트 자산 부족(비프롬프트 타입).
        """
        blocking: list[str] = []
        soft: list[str] = []
        lowered = (html or "").lower()

        table_count = lowered.count("<table")
        if table_count < 1:
            blocking.append("ai_save_value_no_table")

        # 복사형 프롬프트 자산: ai_prompt_recipe(패턴 자체가 프롬프트 템플릿 모음)만 강제.
        # ai_work_tip/ai_beginner_guide에 일괄 강제하면 주제와 무관한 범용 프롬프트 3개를
        # 억지로 끼워 넣게 되어 오히려 저장 가치를 해친다 — 표/체크리스트/비용 언급 등
        # 다른 저장 가치 신호로 충분히 커버된다.
        prompt_asset_count = max(lowered.count("prompt-code"), lowered.count("<pre"))
        prompt_relevant = content_type in {"ai_prompt_recipe"}
        if prompt_relevant and prompt_asset_count < 3:
            blocking.append(f"ai_save_value_prompt_blocks_below_3:{prompt_asset_count}")

        cost_terms = ("무료", "유료", "요금", "구독", "플랜", "비용", "가격")
        cost_hits = sum(1 for term in cost_terms if term in html)
        # 영어 전환(2026-07-17): 영어 모드에서는 영어 비용 어휘도 인정한다.
        # ko 모드 동작을 바꾸지 않도록 is_english_mode()로만 추가 카운트
        # ("plan"이 "explanation" 등에 substring 오탐되는 문제 차단).
        if is_english_mode():
            cost_terms_en = (
                "free", "paid", "pricing", "price", "plan", "per month",
                "/month", "$", "cost", "limit", "subscription",
            )
            cost_hits += sum(1 for term in cost_terms_en if term in lowered)
        if cost_hits == 0:
            blocking.append("ai_save_value_cost_strategy_missing")
        elif cost_hits < 2:
            soft.append("ai_save_value_cost_strategy_thin")

        checklist_present = (
            "체크리스트" in html
            or ("checklist" in lowered and "체크" in html)
            or "확인할 것" in html
            # 영어 전환(2026-07-17): 영어 모드에서는 checklist 단어/quality-checklist
            # 클래스만으로도 체크리스트 자산으로 인정 (ko 모드는 기존 조건 유지).
            or (is_english_mode() and ("checklist" in lowered or "quality-checklist" in lowered))
        )
        if not checklist_present:
            soft.append("ai_save_value_checklist_missing")

        return blocking, soft

    @staticmethod
    def is_delivery_money_issue(selected: ScoredNewsCandidate) -> bool:
        text = " ".join(
            str(part or "")
            for part in (
                selected.candidate.topic,
                selected.candidate.category,
                selected.candidate.summary,
                selected.reason,
                selected.candidate.raw.get("hook_angle"),
            )
        ).lower()
        return is_delivery_money_text(text)

    @staticmethod
    def _click_potential_score(selected: ScoredNewsCandidate) -> int:
        value = selected.candidate.raw.get("click_potential_score")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    _GENERIC_LATIN_ENTITY_TOKENS: frozenset[str] = frozenset({
        "AI",
        "API",
        "APP",
        "FAQ",
        "KST",
        "NEWS",
        "OTT",
        "PC",
        "SNS",
        "TV",
        "URL",
    })

    @classmethod
    def _latin_source_entity_tokens(cls, text: str) -> set[str]:
        tokens = {
            token.upper()
            for token in re.findall(r"\b[A-Z][A-Z0-9&.+-]{1,}\b", text or "")
        }
        return {token for token in tokens if token not in cls._GENERIC_LATIN_ENTITY_TOKENS}

    @classmethod
    def _title_has_latin_source_entity(cls, title: str, selected: ScoredNewsCandidate) -> bool:
        title_tokens = cls._latin_source_entity_tokens(title)
        if not title_tokens:
            return False
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_parts: list[str] = [
            selected.candidate.summary or "",
            str(raw.get("original_topic") or ""),
            str(raw.get("source_title") or ""),
            str(raw.get("cleaned_title") or ""),
            str(raw.get("original_title") or ""),
        ]
        for key in ("source_titles", "reader_search_questions"):
            values = raw.get(key)
            if isinstance(values, list):
                source_parts.extend(str(value or "") for value in values)
        source_tokens = cls._latin_source_entity_tokens(" ".join(source_parts))
        return bool(title_tokens & source_tokens)

    @classmethod
    def _title_has_source_entity(cls, title: str, selected: ScoredNewsCandidate) -> bool:
        return cls._title_has_latin_source_entity(title, selected) or cls._title_has_korean_source_entity(
            title,
            selected,
        )

    @classmethod
    def _title_has_korean_source_entity(cls, title: str, selected: ScoredNewsCandidate) -> bool:
        title_tokens = cls._korean_source_entity_tokens(title)
        if not title_tokens:
            return False
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_parts: list[str] = [
            selected.candidate.summary or "",
            str(raw.get("original_topic") or ""),
            str(raw.get("source_title") or ""),
            str(raw.get("cleaned_title") or ""),
            str(raw.get("original_title") or ""),
            str(raw.get("search_demand_topic") or ""),
        ]
        for key in ("source_titles", "reader_search_questions"):
            values = raw.get(key)
            if isinstance(values, list):
                source_parts.extend(str(value or "") for value in values)
        source_tokens = cls._korean_source_entity_tokens(" ".join(source_parts))
        return bool(title_tokens & source_tokens)

    _GENERIC_KOREAN_ENTITY_TOKENS: frozenset[str] = frozenset({
        "오늘",
        "이슈",
        "화제",
        "반응",
        "이유",
        "핵심",
        "포인트",
        "사람들",
        "먼저",
        "확인",
        "기준",
        "정리",
        "방법",
        "대상",
        "조건",
        "신청",
        "지급",
        "지급일",
        "지원금",
        "환불",
        "지연",
        "소비자",
        "증거",
        "피해",
        "발표",
        "공식",
        "뉴스",
        "속보",
        "시장",
        "출발",
        "상승",
        "갈린",
        "보기",
        "체크",
    })

    @classmethod
    def _korean_source_entity_tokens(cls, text: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[가-힣A-Za-z0-9]+", text or ""):
            normalized = token.strip(" ,.-:;!?\"'").lower()
            normalized = cls._strip_korean_particle(normalized)
            if len(normalized) < 2:
                continue
            if normalized in cls._GENERIC_KOREAN_ENTITY_TOKENS:
                continue
            if re.search(r"\d", normalized):
                continue
            if len(normalized) <= 2 and re.fullmatch(r"[가-힣]+", normalized):
                continue
            tokens.add(normalized)
        return tokens

    @staticmethod
    def _strip_korean_particle(token: str) -> str:
        for suffix in (
            "으로부터",
            "에서도",
            "에게",
            "에서",
            "부터",
            "까지",
            "으로",
            "로",
            "이",
            "가",
            "은",
            "는",
            "을",
            "를",
            "와",
            "과",
            "도",
            "만",
        ):
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                return token[: -len(suffix)]
        return token

    _TOP_ISSUE_RELAXABLE_CONTENT_TYPES: frozenset[str] = frozenset({
        "today_issue_explainer",
        "viral_issue_decode",
        "consumer_warning",
        "platform_change",
    })
    _TOP_ISSUE_RELAXABLE_SOURCES: frozenset[str] = frozenset({
        "google_news_rss",
        "naver_news_search",
        "naver_webkr_search",
        "google_custom_search",
        "daum_news_search",
    })

    @classmethod
    def _relax_top_issue_publish_blockers(
        cls,
        *,
        blocking_issues: list[str],
        warnings: list[str],
        publish_mode_active: bool,
        fallback_candidate: bool,
        source_type: str,
        content_type: str,
        topic_group: str,
        selected: ScoredNewsCandidate,
        reader_value_score: int,
        article_focus_score: int,
        title_has_source_entity: bool,
        raw_topic_count: int,
    ) -> list[str]:
        if not cls._top_issue_relaxation_allowed(
            publish_mode_active=publish_mode_active,
            fallback_candidate=fallback_candidate,
            source_type=source_type,
            content_type=content_type,
            topic_group=topic_group,
            selected=selected,
            reader_value_score=reader_value_score,
            article_focus_score=article_focus_score,
        ):
            return []

        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        click_score = cls._click_potential_score(selected)
        relaxed: list[str] = []
        kept: list[str] = []
        for issue in blocking_issues:
            if cls._is_relaxable_top_issue_blocker(
                issue,
                selected=selected,
                click_score=click_score,
                title_has_source_entity=title_has_source_entity,
                raw_topic_count=raw_topic_count,
            ):
                relaxed.append(issue)
                warnings.append(f"top_issue_publish_relaxed:{issue}")
            else:
                kept.append(issue)

        if relaxed:
            blocking_issues[:] = kept
            raw["top_issue_publish_relaxation"] = {
                "relaxed_blocking_issues": list(dict.fromkeys(relaxed)),
                "reader_value_score": reader_value_score,
                "article_focus_score": article_focus_score,
                "source_type": source_type,
                "content_type": content_type,
                "raw_topic_count": raw_topic_count,
            }
        return list(dict.fromkeys(relaxed))

    @classmethod
    def _top_issue_relaxation_allowed(
        cls,
        *,
        publish_mode_active: bool,
        fallback_candidate: bool,
        source_type: str,
        content_type: str,
        topic_group: str,
        selected: ScoredNewsCandidate,
        reader_value_score: int,
        article_focus_score: int,
    ) -> bool:
        if not publish_mode_active or fallback_candidate:
            return False
        normalized_source = (source_type or "").strip().lower()
        if normalized_source not in cls._TOP_ISSUE_RELAXABLE_SOURCES:
            return False
        if content_type not in cls._TOP_ISSUE_RELAXABLE_CONTENT_TYPES:
            return False
        if reader_value_score < 74 or article_focus_score < 70:
            return False
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        topic_engine_score = cls._safe_int(raw.get("topic_engine_score"))
        today_buzz_score = cls._safe_int(raw.get("today_buzz_score"))
        source_count = cls._safe_int(raw.get("source_count"))
        click_score = cls._click_potential_score(selected)
        real_time_signal = bool(raw.get("trending_engine")) or bool(raw.get("discovery_engine"))
        if topic_group in {"today_issue", "entertainment_sports", "ott_platform", "refund_consumer"}:
            real_time_signal = True
        return (
            selected.total_score >= 65
            or topic_engine_score >= 70
            or click_score >= 7
            or today_buzz_score >= 6
            or source_count >= 2
            or real_time_signal
        )

    @classmethod
    def _is_relaxable_top_issue_blocker(
        cls,
        issue: str,
        *,
        selected: ScoredNewsCandidate,
        click_score: int,
        title_has_source_entity: bool,
        raw_topic_count: int,
    ) -> bool:
        if issue == "total_score_below_75":
            return selected.total_score >= 65
        if issue == "click_potential_score_below_8":
            return click_score >= 6
        if issue == "title_has_no_specific_entity":
            return title_has_source_entity
        if issue.startswith("issue_specificity_below_6:"):
            return cls._issue_score(issue) >= 5 and title_has_source_entity
        if issue.startswith("original_issue_preservation_below_6:"):
            return cls._issue_score(issue) >= 2 and title_has_source_entity
        if issue.startswith("today_relevance_below_7:"):
            return cls._issue_score(issue) >= 6
        if issue == "raw_topic_repeated_in_html":
            return 0 < raw_topic_count < 12
        return False

    @staticmethod
    def _issue_score(issue: str) -> int:
        try:
            return int(str(issue).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # ── Today Issue Editorial Gates (오늘의 이슈 자동발행 품질 기준) ──

    _FUTURE_DATE_PATTERNS = (
        r"(\d+)월\s*부터",         # "9월부터" "10월부터"
        r"(\d+)월\s+(\d+)일\s*부터",  # "9월 1일부터"
        r"내년",
        r"다음\s*주",
        r"다음\s*달",
        r"내달",
        r"향후",
    )

    @classmethod
    def _compute_today_relevance(cls, selected: ScoredNewsCandidate) -> int:
        """0-10 점수: 오늘 클릭할 이유의 강도.

        - 미래 일정("9월부터")만 있고 오늘성 신호 없으면 0-3
        - published_at이 24h 내 + 오늘 신호 키워드 있으면 7-10
        - stale=True이면 0
        """
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        topic = selected.candidate.topic or ""
        original_topic = str(raw.get("original_topic") or "")
        all_text = topic + " " + original_topic + " " + (selected.candidate.summary or "")

        if raw.get("is_stale"):
            return 0

        # 미래 일정 신호 — 오늘 클릭 이유 약함
        future_signal_count = 0
        for pat in cls._FUTURE_DATE_PATTERNS:
            if re.search(pat, all_text):
                future_signal_count += 1

        # 오늘성 신호
        today_signal_count = 0
        for kw in ("오늘", "방금", "긴급", "속보", "현재", "지금", "막", "이번 주", "이슈"):
            if kw in all_text:
                today_signal_count += 1

        # published_at recency
        recent_publish = False
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        try:
            published_at = selected.candidate.published_at or ""
            if published_at:
                pub_dt = _dt.fromisoformat(published_at.replace("Z", "+00:00"))
                hours_ago = (_dt.now(_tz.utc) - pub_dt).total_seconds() / 3600
                if 0 <= hours_ago <= 48:
                    recent_publish = True
        except Exception:
            pass

        score = 5  # base
        if recent_publish:
            score += 2
        if raw.get("trending_engine"):
            score += 2
        # ai_issue_engine: AI_BLOG_MODE에서 신선한 실뉴스 + 구체 엔티티 검증을 통과한
        # AI 이슈 후보. AI 뉴스 헤드라인에는 "오늘" 류 키워드가 드물어 trending과
        # 동일한 오늘성 가산을 준다 (stale이면 이 플래그 자체가 부여되지 않음).
        if raw.get("ai_issue_engine"):
            score += 2
        if raw.get("discovery_engine"):
            try:
                buzz = int(raw.get("today_buzz_score") or 0)
            except (TypeError, ValueError):
                buzz = 0
            try:
                source_count = int(raw.get("source_count") or 0)
            except (TypeError, ValueError):
                source_count = 0
            if buzz >= 8 or source_count >= 3:
                score += 2
            elif buzz >= 6 or source_count >= 2:
                score += 1
        if today_signal_count >= 2:
            score += 2
        elif today_signal_count >= 1:
            score += 1
        if future_signal_count >= 2:
            score -= 4   # "9월부터" 같은 먼 미래 일정 강한 신호 → 점수 큰 감점
        elif future_signal_count == 1:
            score -= 2
        return max(0, min(10, score))

    @classmethod
    def _compute_issue_specificity(cls, selected: ScoredNewsCandidate) -> int:
        """0-10 점수: 특정 사건/서비스/인물/정책/플랫폼/가격/논란 등 고유 맥락이 있는가."""
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        topic = selected.candidate.topic or ""
        original_topic = str(raw.get("original_topic") or "")
        all_text = topic + " " + original_topic

        score = 5
        # 고유명사 / 브랜드 / 서비스명 등 specificity 신호
        specific_keywords = (
            "카드사", "은행", "보험", "통신사", "쿠팡", "네이버", "카카오", "유튜브", "넷플릭스",
            "삼성", "애플", "구글", "정부", "지자체", "경찰", "검찰", "공정위", "금감원",
            "개인정보위", "한국소비자원", "법원", "국세청", "보건복지부", "고용노동부",
            "과징금", "보상", "환불", "유출", "장애", "오류", "변경", "인상", "출시", "종료",
            "신청", "마감", "지급", "지원금", "환급",
            "배달앱", "배달비", "결제금액", "최종금액", "쿠폰", "수수료", "최소주문",
            # 영어 전환(2026-07-17) 추가 — 영어 기사에서의 가격/사건 특정성 신호.
            "pricing", "subscription", "refund", "lawsuit", "outage",
            "discount", "shutdown",
        )
        hits = sum(1 for kw in specific_keywords if kw in all_text)
        score += min(5, hits)
        # AI 뉴스 보정(2026-07-11): 기본 목록이 소비자·정책 위주라 "오픈AI
        # GPT-5.6 공개" 같은 고유명사 가득한 AI 뉴스가 무적중 5점 안팎에
        # 갇혔고(18건 중 16건 specificity 차단), 재탕 에버그린만 게이트를
        # 통과하는 역선택이 벌어졌다. 단, 브랜드명 하나만으로("직장인 ChatGPT
        # 활용법") 특정성을 인정하면 generic 에버그린까지 통과하므로,
        # AI 엔티티는 구체적 사건 신호와 동반될 때만 가점한다. 임계값 불변.
        ai_entity_keywords = (
            "오픈AI", "OpenAI", "챗GPT", "ChatGPT", "GPT", "제미나이", "Gemini",
            "클로드", "Claude", "앤트로픽", "Anthropic", "미토스", "코파일럿", "Copilot",
            "마이크로소프트", "퍼플렉시티", "미스트랄", "하이퍼클로바", "클로바",
            "카나나", "갤럭시", "그록", "Grok", "라마", "Llama", "소라", "Sora",
            # 플랫폼사도 사건 동반 시에만 가점(단독 언급은 기본 목록의 +1뿐)
            "네이버", "카카오", "구글", "삼성", "애플",
            # AI 반도체/로봇/제조 밸류체인 대기업(2026-07-16, GHA run
            # 29468907597 회귀 대응): "엔비디아·도요타·화낙 AI 동맹" 같은
            # 하드웨어/피지컬 AI 제휴 뉴스가 소비자용 AI 서비스명 목록에만
            # 없어 오차단됐다. 개별 회사 하나씩 반응형으로 늘리는 대신
            # AI 밸류체인에서 반복 등장하는 카테고리를 한 번에 채운다.
            "엔비디아", "NVIDIA", "인텔", "Intel", "퀄컴", "Qualcomm",
            "TSMC", "브로드컴", "Broadcom", "ARM", "도요타", "Toyota",
            "화낙", "Fanuc", "테슬라", "Tesla", "아마존", "Amazon",
            "메타", "Meta", "화웨이", "Huawei", "IBM", "소프트뱅크", "SoftBank",
            # 영어 전환(2026-07-17) 추가 — 영어 AI 뉴스에서 반복 등장하는
            # 제품/기업 엔티티(매칭은 이미 대소문자 무시).
            "Perplexity", "Midjourney", "Cursor", "Notion AI", "DeepSeek",
            "Mistral", "Runway", "ElevenLabs", "Hugging Face", "Stability AI",
            "xAI",
        )
        ai_event_keywords = (
            "공개", "발표", "업데이트", "도입", "돌파", "추월", "확대", "해제",
            "수출통제", "이용률", "가입자", "다운로드",
            # 가격/요금 변동 이벤트(2026-07-16, GHA run 29464514437 회귀 대응):
            # "요금 폭등", "무료 한도" 같은 정당하고 구체적인 AI 가격 뉴스에
            # 대응하는 이벤트 키워드가 없어 generic 취급되어 issue_specificity
            # 게이트에 오차단됐다.
            "요금", "가격", "인상", "폭등", "무료", "유료", "한도", "요금제",
            # 사고/보안/제휴 이벤트(2026-07-16, GHA run 29468907597 회귀
            # 대응): "그록 소스코드 무단수집 논란" 같은 사고성 뉴스와
            # "AI 협력 확대" 같은 제휴 뉴스가 이벤트 목록에 없어 오차단됐다.
            "논란", "유출", "해킹", "보안", "취약점", "소송", "제재",
            "협력", "동맹", "파트너십", "제휴",
        )
        # 영어 전환(2026-07-17): 영어 AI 뉴스의 사건/가격 이벤트 신호.
        # 기존 한국어 이벤트 매칭(대소문자 구분)은 그대로 두고, 영어 이벤트는
        # 소문자 텍스트에 추가로 매칭하는 additive 경로다. 짧은 토큰("api")이
        # 다른 단어 안에서 오탐되지 않도록 공백/슬래시 없는 토큰은 앞 경계를
        # 요구한다(뒤는 열어 둬 launch→launched, benchmark→benchmarks 커버).
        ai_event_keywords_en = (
            "pricing", "price increase", "price cut", "price hike", "launch",
            "release", "update", "subscription", "free tier", "rate limit",
            "api", "tokens", "context window", "discontinued", "rollout",
            "waitlist", "benchmark", "per month", "/month", "lawsuit",
            "acquisition", "partnership", "outage",
            # 2026-07-17 드라이런 #3 보강: 보안/오픈소스/기능 사건 신호 —
            # "open source 전환·저장소 유출"류 실뉴스가 5점(1점 부족)으로
            # 막히던 케이스. 전부 사건 특정 신호라 일반론 글에는 안 잡힌다.
            "open source", "open-source", "codebase", "repository", "repos",
            "data leak", "breach", "exfiltrat", "security incident",
            "jailbreak", "integration", "plugin", "extension", "dataset",
            "fine-tun", "on-device", "voice mode", "image generation",
        )
        # 실측 사건(2026-07-16): 스크랩된 토픽 문자열에 "gpt-image-1",
        # "claude-4"처럼 소문자/하이픈 표기가 섞여 대소문자 구분 매칭("GPT")이
        # 실제 AI 제품명을 놓쳤다. 엔티티 매칭만 대소문자 무시로 바꾼다
        # (이벤트 키워드 매칭은 기존 그대로 유지 — 스코프 최소화).
        all_text_lower = all_text.lower()
        ai_entity_matches = [kw for kw in ai_entity_keywords if kw.lower() in all_text_lower]
        # 부분 문자열 중복 제거: "GPT"는 "ChatGPT"/"챗GPT"의 부분 문자열이라 같은
        # 언급 하나가 엔티티 2개로 잡혔다 — 아래 entity_hits>=2(복수 개체 동시
        # 언급) 신호가 "ChatGPT" 단독 언급 하나에도 오발동하는 원인이었다.
        distinct_entity_matches = [
            kw for kw in ai_entity_matches
            if not any(kw != other and kw.lower() in other.lower() for other in ai_entity_matches)
        ]
        ai_entity_hits = len(distinct_entity_matches)
        ai_event_hits = sum(1 for kw in ai_event_keywords if kw in all_text)
        # 영어 이벤트 additive 매칭 (한국어 매칭 결과에 더하기만 한다).
        for kw in ai_event_keywords_en:
            if " " in kw or "/" in kw:
                if kw in all_text_lower:
                    ai_event_hits += 1
            elif re.search(rf"(?<![a-z0-9]){re.escape(kw)}", all_text_lower):
                ai_event_hits += 1
        # 영어 특정성 마커: "$30"/"$ 30" 금액, "4.5"/"v2.1" 버전 표기.
        if re.search(r"\$\s?\d", all_text):
            ai_event_hits += 1
        if re.search(r"(?<![\d.])v?\d+\.\d+(?![\d.])", all_text_lower):
            ai_event_hits += 1
        # 서로 다른 개체 2개 이상이 함께 언급되면(예: "엔비디아·도요타·화낙")
        # 그 자체로 구체적 사건/관계를 시사하므로, 고정 이벤트 단어가 없어도
        # 특정성으로 인정한다 — 매번 새 이벤트 단어를 추가하는 대신 "복수
        # 개체 동시 언급"이라는 더 일반적인 신호로 대응(2026-07-16 재검토).
        if ai_entity_hits and (ai_event_hits or ai_entity_hits >= 2):
            score += min(5, ai_entity_hits + ai_event_hits)
        # 사용자 승인(2026-06-09): 트렌딩/실검 후보는 트렌드 키워드 자체가 고유
        # 인물·사건·작품 엔티티 → specificity 신호로 인정. 소비자/정책 키워드 위주
        # 평가가 연예·스포츠·게임 트렌딩을 구조적으로 5점에 가두던 문제 보정.
        _is_trend = bool(raw.get("trending_engine") or raw.get("discovery_engine"))
        if _is_trend and len(all_text.strip()) >= 12:
            score += 3
        latin_entities = cls._latin_source_entity_tokens(topic) & cls._latin_source_entity_tokens(
            f"{original_topic} {selected.candidate.summary or ''}"
        )
        if latin_entities:
            score += min(5, len(latin_entities) + 3)
        # 너무 짧은 generic 제목 감점 (실제 헤드라인인 트렌딩 후보는 면제)
        if not _is_trend and len(topic.strip()) < 15:
            score -= 2
        # "확인할 조건" 만 있고 주어 없는 패턴
        if "확인할" in topic and not any(kw in topic for kw in specific_keywords):
            score -= 3
        return max(0, min(10, score))

    @classmethod
    def _compute_original_issue_preservation(
        cls, selected: ScoredNewsCandidate, title: str = ""
    ) -> int:
        """0-10 점수: 원문 이슈의 핵심 키워드가 제목/topic에 보존되어 있는가."""
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        original_topic = str(raw.get("original_topic") or "")
        if not original_topic:
            return 5  # 원문 없으면 중립
        topic = selected.candidate.topic or ""
        # 원문에서 의미 있는 키워드 추출. 금액/연도/출처/클릭 유도 표현은
        # 보존 대상에서 제외해 실제 정책명·서비스명 중심으로 평가한다.
        import re as _re_pres
        stopwords = {
            "최대", "최소", "얼마", "어떻게", "받나", "정리", "뉴스",
            "위키트리", "연합뉴스", "뉴시스", "뉴스1", "머니투데이",
            "줍니다", "준다", "신청하기",
        }
        original_tokens = [
            token
            for token in _re_pres.findall(r"[가-힣A-Za-z0-9]+", original_topic)
            if len(token) >= 2
            and token not in stopwords
            and not _re_pres.search(r"\d", token)
        ]
        if not original_tokens:
            return 5
        all_check = (topic + " " + title).lower()
        # 의미 있는 키워드 중 몇 개가 제목/topic에 살아있는가
        preserved = sum(1 for tok in original_tokens if tok.lower() in all_check)
        ratio = preserved / max(1, min(5, len(original_tokens)))  # 상위 5개 중 비율
        score = int(round(ratio * 10))
        return max(0, min(10, score))

    @classmethod
    def _compute_reader_question_potential(cls, selected: ScoredNewsCandidate) -> int:
        """0-10 점수: 독자가 궁금해할 질문이 5개 이상 도출 가능한가."""
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        questions = raw.get("reader_search_questions") or []
        if not isinstance(questions, list):
            return 5
        valid = [q for q in questions if isinstance(q, str) and len(q.strip()) >= 10]
        if len(valid) >= 5:
            return 9
        if len(valid) >= 3:
            return 7
        if len(valid) >= 2:
            return 5
        return 3

    _TITLE_BODY_STOP_TOKENS: frozenset[str] = frozenset({
        "이번엔",
        "오늘",
        "이슈",
        "화제",
        "반응",
        "갈린",
        "이유",
        "핵심",
        "포인트",
        "먼저",
        "보기",
        "가지",
        "3가지",
        "사람",
        "사람들",
        "본",
        "정리",
        "지금",
        "확인된",
        "아직",
        "모르는",
        "모르",
        "것",
        "것과",
        "확인",
        "해야",
        "무엇",
        "어떻게",
        "공식",
        "기준",
        "조건",
        "주의",
        "전",
        "후",
        "더",
        "왜",
        "놓치면",
        "내는",
    })

    # 영어 전환(2026-07-17): 영어 제목의 filler 단어가 본문 필수 등장 단어로
    # 강제되면 false title_body_entity_mismatch가 난다. ko 모드 동작을 바꾸지
    # 않도록 별도 세트로 두고 is_english_mode()에서만 적용한다.
    _TITLE_BODY_STOP_TOKENS_EN: frozenset[str] = frozenset({
        "the", "an", "and", "or", "for", "to", "of", "in", "on", "with",
        "your", "you", "how", "what", "why", "when", "which", "who",
        "is", "are", "was", "were", "it", "its", "this", "that", "these",
        "those", "vs", "versus", "best", "guide", "i", "we", "my", "our",
        "tested", "actually", "really", "gets", "get", "do", "does", "can",
        "will", "should", "not", "no", "be", "has", "have", "had", "at",
        "by", "as", "from", "into", "about", "after", "before", "still",
        "just", "now", "new", "more", "most",
    })

    @classmethod
    def _title_body_alignment(cls, *, title: str, html: str) -> dict[str, object]:
        required = cls._title_core_terms(title)
        substantive = cls._substantive_body_text(html)
        missing = [term for term in required if term not in substantive]
        return {
            "required_terms": required,
            "missing_terms": missing,
            "matched_terms": [term for term in required if term in substantive],
            "substantive_text_length": len(substantive),
        }

    @classmethod
    def _title_core_terms(cls, title: str) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[가-힣A-Za-z0-9+]+", title or ""):
            normalized = cls._strip_korean_particle(token.strip().lower())
            if len(normalized) < 2:
                continue
            if normalized in cls._TITLE_BODY_STOP_TOKENS:
                continue
            if is_english_mode() and normalized in cls._TITLE_BODY_STOP_TOKENS_EN:
                continue
            if re.fullmatch(r"\d+", normalized):
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= 5:
                break
        return terms

    @classmethod
    def _has_bad_subject_particle(cls, title: str) -> bool:
        for match in re.finditer(r"(?:^|\s)([가-힣A-Za-z0-9·]{2,})가(?=\s|,|$)", title or ""):
            stem = match.group(1)
            if cls._has_korean_final_consonant(stem[-1]):
                return True
        return False

    @staticmethod
    def _is_telecom_plan_topic(selected: ScoredNewsCandidate, *, title: str = "") -> bool:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        text_parts = [
            title,
            selected.candidate.topic or "",
            selected.candidate.summary or "",
            str(raw.get("original_topic") or ""),
            str(raw.get("source_title") or ""),
            str(raw.get("cleaned_title") or ""),
            str(raw.get("search_demand_topic") or ""),
        ]
        for key in ("source_titles", "reader_search_questions"):
            value = raw.get(key)
            if isinstance(value, list):
                text_parts.extend(str(item) for item in value)
        text = " ".join(text_parts)
        has_telecom_brand = any(brand in text for brand in ("KT", "SKT", "SK텔레콤", "LG유플러스", "LGU+"))
        has_plan_term = any(term in text for term in _TELECOM_PLAN_TERMS)
        return has_telecom_brand and has_plan_term

    @staticmethod
    def _title_source_context(selected: ScoredNewsCandidate) -> str:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        parts = [
            selected.candidate.topic or "",
            selected.candidate.summary or "",
            str(raw.get("original_topic") or ""),
            str(raw.get("source_title") or ""),
            str(raw.get("cleaned_title") or ""),
            str(raw.get("search_demand_topic") or ""),
        ]
        for key in ("source_titles", "reader_search_questions"):
            value = raw.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
        return " ".join(parts)

    @staticmethod
    def _has_korean_final_consonant(ch: str) -> bool:
        code = ord(ch)
        return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0

    @staticmethod
    def _substantive_body_text(html: str) -> str:
        content = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"<style\b.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
        parts: list[str] = []
        for tag in ("p", "td"):
            for match in re.findall(
                rf"<{tag}\b[^>]*>(.*?)</{tag}>",
                content,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                text = unescape(re.sub(r"<[^>]+>", " ", match))
                if text.strip():
                    parts.append(text)
        return re.sub(r"\s+", " ", " ".join(parts)).lower()

    @staticmethod
    def _faq_answers(html: str) -> list[str]:
        faq_match = re.search(
            r'<section\b[^>]*class=["\'][^"\']*faq[^"\']*["\'][^>]*>(.*?)</section>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not faq_match:
            return []
        section = faq_match.group(1)
        answers = re.findall(
            r"<h3\b[^>]*>.*?</h3>\s*<p\b[^>]*>(.*?)</p>",
            section,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return [" ".join(re.sub(r"<[^>]+>", " ", answer).split()) for answer in answers]

    @staticmethod
    def _faq_questions(html: str) -> list[str]:
        faq_match = re.search(
            r'<section\b[^>]*class=["\'][^"\']*faq[^"\']*["\'][^>]*>(.*?)</section>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not faq_match:
            return []
        return [
            " ".join(re.sub(r"<[^>]+>", " ", question).split())
            for question in re.findall(r"<h3\b[^>]*>(.*?)</h3>", faq_match.group(1), flags=re.IGNORECASE | re.DOTALL)
        ]

    @staticmethod
    def _policy_checklist_count(html: str) -> int:
        match = re.search(
            r"(오늘 바로 할 체크리스트.*?</section>)",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            count = len(re.findall(r"<p\b[^>]*>\s*\d+\)", match.group(1), flags=re.IGNORECASE))
            if count:
                return count

        counts: list[int] = []
        qdt = re.search(
            r'<section\b[^>]*class=["\'][^"\']*\bquick-decision-table\b[^"\']*["\'][^>]*>(.*?)</section>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if qdt:
            valid_rows = 0
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", qdt.group(1), flags=re.IGNORECASE | re.DOTALL):
                cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
                if len(cells) >= 2 and re.sub(r"<[^>]+>", " ", cells[1]).strip():
                    valid_rows += 1
            counts.append(valid_rows)

        actions = re.search(
            r'<section\b[^>]*class=["\'][^"\']*\bactions-box\b[^"\']*["\'][^>]*>(.*?)</section>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if actions:
            counts.append(len(re.findall(r"<li\b", actions.group(1), flags=re.IGNORECASE)))

        return max(counts or [0])

    @staticmethod
    def _policy_required_term_count(html: str) -> int:
        term_groups = (
            ("신청 대상", "대상 조건", "대상"),
            ("신청 기간", "마감일", "접수 시간"),
            ("지급 방식", "계좌 입금", "카드 포인트", "지역상품권"),
            ("사용처", "제외 업종", "가맹점"),
        )
        return sum(1 for terms in term_groups if any(term in html for term in terms))

    @staticmethod
    def _policy_information_density_terms(html: str) -> list[str]:
        required_terms = {
            "신청 대상": ("신청 대상", "대상 조건", "자격 조건"),
            "신청 기간": ("신청 기간", "마감일", "접수 시간"),
            "지급 금액": ("지급 금액", "1인당 금액", "가구별 한도"),
            "신청 방법": ("신청 방법", "온라인 신청", "방문 접수"),
            "지급 방식": ("지급 방식", "계좌 입금", "카드 포인트", "지역상품권", "바우처"),
            "사용처": ("사용처", "제외 업종", "가맹점"),
            "중복 지원": ("중복 지원", "중복 수급"),
            "필요 서류": ("필요 서류", "소득 증빙", "통장 사본"),
            "공식 확인처": ("공식 확인처", "정부24", "복지로", "지자체 공고", "공식 공고"),
            "마감": ("마감", "마감일"),
            "대상 조건": ("대상 조건", "자격 조건"),
        }
        return [label for label, terms in required_terms.items() if any(term in html for term in terms)]

    @classmethod
    def _reader_value_score(
        cls,
        *,
        title: str,
        html: str,
        content_type: str,
        topic_group: str,
    ) -> dict[str, object]:
        plain_text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
        search_terms = (
            "신청", "방법", "대상", "조건", "확인", "환불", "증거", "설정",
            "해지", "비교", "체크", "사용처", "지급", "마감",
            # 영어 전환(2026-07-17) 추가 — 영어 검색 의도 신호 (additive 가산용).
            "how to", "fix", "error", "not working", "pricing", "cost",
            "worth it", "alternative", "vs", "best", "limit", "free",
            "upgrade", "cancel", "compare",
        )
        pain_terms = (
            "손해", "마감", "놓치", "환불", "지원금", "지급", "사용처",
            "불편", "설정", "결제", "금액", "시간", "대상 조건",
            # 영어 전환(2026-07-17) 추가 — 영어 pain point 신호.
            "stuck", "fails", "blocked", "wasted", "overpaying",
            "hidden cost", "slow", "wrong answers",
        )
        checklist_terms = (
            "체크리스트", "예시", "정보표", "비교표", "오늘 바로 할 일",
            # 영어 전환(2026-07-17) 추가 — 영어 실용성/체크리스트 신호.
            "checklist", "step", "before you", "make sure", "check",
            "verify", "as of",
        )

        search_intent = 20 if any(term in title or term in plain_text[:500] for term in search_terms) else 10
        pain_solution = 20 if sum(1 for term in pain_terms if term in plain_text) >= 3 else 12
        if content_type == "policy_deadline" or topic_group == "policy_benefit":
            density_count = len(cls._policy_information_density_terms(html))
            info_density = 20 if density_count >= 7 else 15 if density_count >= 5 else 8
        else:
            info_density = 20 if len(plain_text) >= 1200 and "fact-card" in html else 14
        practical = 20 if sum(1 for term in checklist_terms if term in plain_text) >= 2 and "faq-card" in html else 12
        title_tokens = [token for token in re.split(r"\s+|,|·", title) if len(token) >= 3]
        matched_tokens = sum(1 for token in title_tokens[:5] if token in plain_text)
        promise_match = 20 if matched_tokens >= 2 else 14 if matched_tokens >= 1 else 8
        breakdown = {
            "search_intent": search_intent,
            "money_time_anxiety_solution": pain_solution,
            "information_density": info_density,
            "practical_checklist_example": practical,
            "title_body_promise_match": promise_match,
        }
        return {"score": sum(breakdown.values()), "breakdown": breakdown}

    @classmethod
    def _article_focus_score(
        cls,
        *,
        title: str,
        html: str,
        plain_text: str,
        content_type: str,
        topic_group: str,
        hashtags: list[str],
    ) -> dict[str, object]:
        target_terms = (
            "30~50", "30대", "40대", "50대", "직장인", "소비자", "이용자", "대상",
            # 영어 전환(2026-07-17) 추가 — 영어 타깃 독자 신호.
            "developers", "marketers", "students", "freelancers", "creators",
            "small business", "beginners", "professionals", "anyone who",
        )
        conclusion_terms = (
            "핵심", "먼저 알아야", "결론", "읽고 나서 바로 할 일",
            # 영어 전환(2026-07-17) 추가 — 영어 결론/요지 신호.
            "bottom line", "key takeaway", "in short", "the verdict",
            "what matters most",
        )
        search_terms = (
            "신청", "조회", "확인", "방법", "대상", "조건", "환불", "증거", "설정",
            "해지", "비교", "체크", "홈택스", "손택스", "지원 종료", "사용처",
            # 영어 전환(2026-07-17) 추가 — 영어 검색 의도 신호.
            "how to", "fix", "error", "not working", "pricing", "cost",
            "worth it", "alternative", "vs", "best", "limit", "free",
            "upgrade", "cancel", "compare", "setup",
        )
        action_terms = (
            "지금 바로 할 일", "체크리스트", "확인하세요", "보관하세요", "캡처", "준비", "비교",
            # 영어 전환(2026-07-17) 추가 — 영어 실행 지시 신호.
            "checklist", "step", "before you", "make sure", "check",
            "verify", "today", "right now",
        )
        target_clear = 20 if "target-reader-box" in html and any(term in plain_text for term in target_terms) else 10
        one_sentence_conclusion = 20 if "core-message-box" in html and any(term in plain_text for term in conclusion_terms) else 8
        search_intent_match = 20 if any(term in title or term in plain_text[:700] for term in search_terms) else 10
        actionable = 20 if "action-guide-box" in html and sum(1 for term in action_terms if term in plain_text) >= 2 else 10
        mixed_terms = cls._hashtag_mismatch_terms(content_type, hashtags)
        mixed_terms.extend(cls._body_mixing_terms(content_type, plain_text))
        no_topic_mixing = 20 if not mixed_terms else 0
        breakdown = {
            "target_clarity": target_clear,
            "one_sentence_conclusion": one_sentence_conclusion,
            "search_intent_match": search_intent_match,
            "actionability": actionable,
            "no_topic_mixing": no_topic_mixing,
        }
        return {"score": sum(breakdown.values()), "breakdown": breakdown}

    @staticmethod
    def _hashtag_mismatch_terms(content_type: str, hashtags: list[str]) -> list[str]:
        tags = " ".join(hashtags)
        forbidden_by_type = {
            "tax_refund": ("#지원금", "#신청마감", "#대상조건", "#사용처", "#정부지원"),
            "policy_deadline": ("#세금환급", "#환급금조회", "#홈택스", "#손택스", "#국세환급금", "#환급계좌"),
            "ai_work_tip": ("#지원금", "#세금환급", "#환급금조회", "#사용처", "#신청마감"),
            "platform_change": ("#지원금", "#세금환급", "#환급금조회"),
        }
        return [term for term in forbidden_by_type.get(content_type or "", ()) if term in tags]

    @staticmethod
    def _body_mixing_terms(content_type: str, plain_text: str) -> list[str]:
        forbidden_by_type = {
            "tax_refund": ("사용처", "지역상품권", "바우처", "가맹점", "카드 포인트"),
            "ai_work_tip": ("지원금 신청", "환급금 조회", "사용처"),
            "platform_change": ("지원금 신청", "세금 환급"),
        }
        return [term for term in forbidden_by_type.get(content_type or "", ()) if term in plain_text]

    @staticmethod
    def _ai_tool_topic_specificity_issues(
        *,
        title: str,
        topic: str,
        plain_text: str,
        content_type: str,
        topic_group: str,
    ) -> list[str]:
        issues: list[str] = []
        source_text = f"{title} {topic}"
        body = " ".join((plain_text or "").split())
        body_lower = body.lower()
        source_lower = source_text.lower()
        is_ai_article = (
            "ai" in source_lower
            or "gpt" in source_lower
            or "chatgpt" in source_lower
            or content_type.startswith("ai_")
            or topic_group.startswith("ai_")
        )
        if not is_ai_article or not body:
            return issues

        generic_template_markers = (
            "ChatGPT를 쓰기 시작했는데 오히려 시간이 더 걸리는 경험",
            "반복 텍스트 업무에 우선 적용",
            "이메일 초안·보고서 요약·반복 텍스트 생성",
            "좋은 프롬프트는 어떻게 짜나",
            "회의록 정리",
        )
        if "chatgpt" not in source_lower and any(marker in body for marker in generic_template_markers):
            issues.append("ai_generic_chatgpt_template_leaked")

        stop_terms = {
            "ai", "gpt", "chatgpt", "the", "and", "for", "with", "news", "update",
            "업무", "자동화", "활용", "기준", "이유", "방법", "정리", "사람", "먼저",
        }
        candidate_terms: list[str] = []
        for term in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}|[가-힣]{2,}", source_text):
            normalized = term.strip().lower()
            if normalized in stop_terms:
                continue
            if normalized not in candidate_terms:
                candidate_terms.append(normalized)
        important_terms = candidate_terms[:5]
        missing_terms = [term for term in important_terms if body_lower.count(term) < 2]
        if important_terms and len(missing_terms) >= max(1, len(important_terms) // 2):
            issues.append("ai_title_tool_terms_missing_in_body:" + ",".join(missing_terms[:3]))

        value_groups = {
            "pricing": ("요금", "가격", "비용", "무료", "유료", "플랜", "한도", "$", "달러"),
            "workflow": ("활용", "워크플로우", "자동화", "설정", "단계", "적용", "사용법"),
            "risk": ("보안", "개인정보", "권한", "데이터", "주의", "검수", "정책"),
        }
        missing_value_groups = [
            name for name, terms in value_groups.items()
            if not any(term in body for term in terms)
        ]
        if len(missing_value_groups) >= 2:
            issues.append("ai_paid_value_information_missing:" + ",".join(missing_value_groups))

        return issues

    @staticmethod
    def _ai_blog_risk_issues(plain_text: str) -> list[str]:
        issues: list[str] = []
        text = " ".join((plain_text or "").split())
        if not text:
            return issues

        overclaim_patterns = (
            r"무조건\s*(?:써야|사용해야|추천)",
            r"모든\s*업무를\s*(?:대신|자동)",
            r"완벽하게\s*(?:대체|해결|처리)",
            r"검수\s*(?:없이|불필요)",
            r"수익\s*보장",
        )
        # 영어 전환(2026-07-17) 추가 — 영어 과장/보장 표현도 동일 이슈로 차단
        # (additive 강화: 기존 한국어 패턴은 그대로 유지).
        overclaim_patterns_en = (
            r"guaranteed\s+(?:income|profit|profits|returns?)",
            r"100%\s*safe",
            r"no\s+review\s+needed",
            r"replaces?\s+(?:all|every)\s+(?:work|jobs?)",
            r"works\s+for\s+everyone",
            r"get\s+rich",
        )
        if any(re.search(pattern, text) for pattern in overclaim_patterns) or any(
            re.search(pattern, text, flags=re.IGNORECASE) for pattern in overclaim_patterns_en
        ):
            issues.append("ai_overclaim_or_guarantee_phrase")

        sensitive_terms = ("회사 기밀", "개인정보", "민감정보", "고객정보", "사내자료", "계약서 원문")
        safety_terms = ("입력하지", "넣지", "삭제", "마스킹", "익명", "주의", "금지", "제외", "확인")
        if any(term in text for term in sensitive_terms) and not any(term in text for term in safety_terms):
            issues.append("ai_sensitive_data_warning_missing")
        # 영어 전환(2026-07-17) 추가 — 영어 민감정보 언급 시에도 안전 문구를
        # 요구한다 (additive 강화: 기존 한국어 검사와 독립적으로 동작).
        text_lower = text.lower()
        sensitive_terms_en = (
            "company confidential", "confidential document", "personal data",
            "customer data", "trade secret",
        )
        safety_terms_en = (
            "do not enter", "don't enter", "do not paste", "never paste",
            "mask", "redact", "anonymize", "remove", "caution", "warning",
            "never share", "avoid", "exclude",
        )
        if (
            "ai_sensitive_data_warning_missing" not in issues
            and any(term in text_lower for term in sensitive_terms_en)
            and not any(term in text for term in safety_terms)
            and not any(term in text_lower for term in safety_terms_en)
        ):
            issues.append("ai_sensitive_data_warning_missing")

        price_or_limit_claim = re.search(
            r"(?:월|연|하루)?\s*(?:\d[\d,]*\s*(?:원|달러)|\$\s*\d[\d,.]*)|(?:무료|유료)\s*(?:제한|플랜|요금)",
            text,
        )
        _price_verify_context = any(
            term in text for term in ("공식", "기준", "확인", "변경", "다를 수", "제공된")
        )
        # 영어 전환(2026-07-17): 영어 모드에서는 영어 검증 문맥("official",
        # "as of", "may change" 등)도 인정 — 없으면 "$20/month" 언급만으로
        # 영어 가격 글이 전부 차단된다. ko 모드는 기존 조건 그대로.
        if not _price_verify_context and is_english_mode():
            _price_verify_context = any(
                term in text_lower
                for term in (
                    "official", "as of", "verify", "check", "may change",
                    "subject to change", "according to", "at the time of writing",
                )
            )
        if price_or_limit_claim and not _price_verify_context:
            issues.append("ai_price_or_plan_claim_without_verification_context")

        return issues

    @staticmethod
    def _tax_refund_action_terms(html: str) -> list[str]:
        checks: list[tuple[str, tuple[str, ...]]] = [
            ("환급 유형 구분", ("환급 유형 구분", "국세환급금", "미수령 환급금", "종합소득세", "연말정산", "지방세")),
            ("홈택스/손택스 조회 경로", ("홈택스", "손택스", "환급금 조회", "조회 메뉴")),
            ("환급 계좌 확인", ("환급 계좌", "예금주", "계좌번호")),
            ("지연 원인", ("지연 원인", "계좌번호 오류", "예금주 불일치", "공제 자료 누락", "중복 신고", "연락처 오류")),
            ("보완 요청", ("보완 요청", "전자고지", "안내 문자")),
            ("구체 상황 예시", ("구체 상황 예시", "환급금은 보이는데", "신고 내역이 누락", "정정 신고")),
        ]
        found: list[str] = []
        for label, terms in checks:
            matched = sum(1 for term in terms if term in html)
            if label == "환급 유형 구분":
                if matched >= 3:
                    found.append(label)
            elif label == "홈택스/손택스 조회 경로":
                if "홈택스" in html and "손택스" in html and ("환급금 조회" in html or "조회 메뉴" in html):
                    found.append(label)
            elif matched >= 1:
                found.append(label)
        return found

    @staticmethod
    def _meta_description(html: str) -> str:
        match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _image_prompt_has_forbidden_terms(image_prompt: str) -> bool:
        prompt = " ".join((image_prompt or "").lower().split())
        if not prompt:
            return False
        hard_forbidden = (
            "clickbait",
            "shocking",
            "sensational",
            "horror",
            "fear",
            "sexy",
            "violent",
            "gore",
        )
        for term in hard_forbidden:
            if term in prompt and f"no {term}" not in prompt and f"without {term}" not in prompt:
                return True
        guarded_terms = ("text", "logo", "watermark")
        for term in guarded_terms:
            if term not in prompt:
                continue
            allowed = (
                f"no {term}" in prompt
                or f"without {term}" in prompt
                or f"no readable {term}" in prompt
                or f"without readable {term}" in prompt
            )
            if not allowed:
                return True
        return False

    @staticmethod
    def _clean_labels(labels: list[str]) -> list[str]:
        cleaned: list[str] = []
        for label in labels:
            text = "".join(str(label or "").split()).strip(" ,.-_/\\")
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _clean_hashtags(hashtags: list[str]) -> list[str]:
        cleaned: list[str] = []
        for hashtag in hashtags:
            text = "".join(str(hashtag or "").split()).strip(" ,.-_/\\")
            if not text:
                continue
            if not text.startswith("#"):
                text = f"#{text.lstrip('#')}"
            if text not in cleaned:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _label_has_banned_fragment(label: str) -> bool:
        lowered = label.lower()
        return any(fragment.lower() in lowered for fragment in _BANNED_LABEL_FRAGMENTS)
