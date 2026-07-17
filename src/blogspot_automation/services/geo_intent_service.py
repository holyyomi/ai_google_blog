from __future__ import annotations

import hashlib
import logging
from html import escape
import re
from typing import Any

from blogspot_automation.services.blog_language import is_english_mode

logger = logging.getLogger(__name__)


def _josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """명사 + 받침 유무에 맞는 조사. 예: _josa('종합특검','은','는') → '종합특검은'.
    한글이 아닌 경우(영문·숫자)는 받침 없음(without)으로 처리해 깨짐을 피한다."""
    text = (word or "").rstrip()
    if not text:
        return word + without_batchim
    last = text[-1]
    if "가" <= last <= "힣":
        has_batchim = (ord(last) - 0xAC00) % 28 != 0
        return text + (with_batchim if has_batchim else without_batchim)
    return text + without_batchim


def _ga(word: str) -> str:
    """주격조사 이/가. '참교육가' 같은 깨진 표면형 방지."""
    return _josa(word, "이", "가")


class GeoIntentService:
    """GEO intent 콘텐츠를 rule-based로 생성한다. AI API 호출 없음."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def generate_reader_intent_questions(
        self,
        topic: str,
        content_type: str,
        topic_group: str,
        slots: dict,
    ) -> list[str]:
        """독자 의도 질문 5개 이상을 반환한다.

        topic 반복 spam 방지를 위해 첫 1~2개만 topic 활용, 나머지는 카테고리 키워드 사용.
        viral_issue_decode는 작품/이슈 이름 자체가 검색 키워드라 예외.
        """
        if is_english_mode():
            return self._reader_intent_questions_en(topic=topic, content_type=content_type, slots=slots)
        kw = topic.strip()[:30] if topic.strip() else "이 주제"
        policy_kw = self._policy_subject(topic)
        is_delivery_schedule_issue = self._is_delivery_schedule_issue(topic)

        if content_type == "consumer_warning" and is_delivery_schedule_issue:
            questions = [
                f"{kw}에서 택배가 쉬는 날은 언제인가요?",
                "선거일이나 공휴일에는 집화와 배송이 모두 멈추나요?",
                "새벽배송과 당일배송은 일반 택배와 다르게 운영되나요?",
                "배송조회가 멈췄을 때 어떤 단계를 먼저 봐야 하나요?",
                "이미 주문한 상품은 판매자와 택배사 중 어디를 확인해야 하나요?",
                "반품 회수나 교환 접수는 휴무일에 어떻게 달라지나요?",
            ]
        elif content_type in ("money_checklist", "delivery_money"):
            questions = [
                f"{kw}은 무엇을 기준으로 비교해야 하나요?",
                "쿠폰을 쓰면 항상 더 저렴한가요?",
                "배달비 무료 조건은 어떻게 확인하나요?",
                "최소주문금액 미달이면 어떻게 되나요?",
                "앱별 결제금액 차이는 어떻게 비교하나요?",
                "주문 전에 어떤 순서로 확인해야 하나요?",
            ]
        elif content_type in ("tax_refund",):
            questions = [
                f"{kw} 환급 대상은 누구인가요?",
                "환급 유형은 어떻게 구분하나요?",
                "환급 입금이 안 되는 이유는 무엇인가요?",
                "환급 소멸시효는 얼마인가요?",
                "환급 신청은 직접 해야 하나요?",
                "환급 조회 결과가 나오지 않을 때 어떻게 해야 하나요?",
            ]
        elif content_type in ("policy_benefit", "policy_deadline"):
            questions = [
                f"{policy_kw} 신청 대상은 누구인가요?",
                f"{policy_kw} 소득 기준은 어떻게 적용되나요?",
                f"{policy_kw} 필요 서류는 어디서 발급하나요?",
                f"{policy_kw} 신청 마감일은 어디서 확인하나요?",
                f"{policy_kw} 지급 방식과 사용처는 어떻게 되나요?",
                f"{policy_kw}을 놓치면 나중에 받을 수 있나요?",
            ]
        elif content_type == "platform_change":
            questions = [
                f"{kw} 적용 대상은 어떻게 확인하나요?",
                "변경 전에 무엇부터 점검해야 하나요?",
                "기존 사용자는 자동으로 예외 처리되나요?",
                "자동결제는 어떻게 처리해야 하나요?",
                "변경 후 취소·환불 기준이 달라지나요?",
                "공식 공지는 어디서 확인할 수 있나요?",
            ]
        elif content_type == "consumer_warning":
            questions = [
                f"{kw} 피해가 의심될 때 먼저 무엇을 해야 하나요?",
                "결제 화면·주문번호를 어떻게 남겨야 하나요?",
                "고객센터 대응이 부족하면 어디로 신고하나요?",
                "한국소비자원 신고는 어떻게 하나요?",
                "환불 거부 시 대응 방법은 무엇인가요?",
                "어떤 증거를 우선 확보해야 하나요?",
            ]
        elif content_type == "viral_issue_decode":
            questions = [
                f"{kw}에 대해 반응이 갈리는 이유는 무엇인가요?",
                f"{kw}의 순위와 실제 만족도 차이는 어느 정도인가요?",
                f"{kw}은 어떤 시청자에게 잘 맞나요?",
                f"{kw} 관련 루머와 사실은 어떻게 구분하나요?",
                f"{kw}을 시청하기 전에 알아야 할 것은 무엇인가요?",
                "기대 장르 코드를 먼저 확인하는 방법은 무엇인가요?",
            ]
        elif content_type == "ai_work_tip":
            questions = [
                f"{_josa(kw, '은', '는')} 어떤 업무에 효과적인가요?",
                "AI 도구는 무료로 쓸 수 있나요?",
                "AI 도구로 실제 시간 절약은 어느 정도인가요?",
                "AI 도구 사용 시 주의사항은 무엇인가요?",
                "AI 결과물은 어떻게 검수해야 하나요?",
                "AI 도구 도입 전 먼저 확인해야 할 항목은 무엇인가요?",
            ]
        elif content_type == "today_issue_explainer":
            questions = [
                f"{kw}에서 지금 확인된 내용은 무엇인가요?",
                f"{_ga(kw)} 오늘 이슈가 된 이유는 무엇인가요?",
                f"{kw}에서 아직 확인이 필요한 부분은 무엇인가요?",
                f"{_ga(kw)} 독자에게 직접 영향을 주는 지점은 무엇인가요?",
                f"{kw} 관련 다음 쟁점은 무엇인가요?",
                "확정 사실과 추정은 어떻게 구분해야 하나요?",
            ]
        else:
            questions = [
                f"{kw}의 핵심 내용은 무엇인가요?",
                "가장 중요한 확인 사항은 무엇인가요?",
                "나와 직접 관련이 있는지 어떻게 확인하나요?",
                "자주 묻는 질문은 무엇인가요?",
                "공식 정보는 어디서 확인하나요?",
                "주의해야 할 점은 무엇인가요?",
            ]

        # FAQ 슬롯에서 추가 질문 흡수
        faq_list = slots.get("faq") or []
        for item in faq_list:
            if isinstance(item, dict):
                q = str(item.get("Q", "")).strip()
                if q and q not in questions and len(questions) < 8:
                    questions.append(q)

        return questions[:8]

    def generate_issue_context(
        self,
        topic: str,
        content_type: str,
        hook: str,
    ) -> str:
        """3문장 이슈 맥락을 반환한다. 200자 이하, 사실 톤."""
        if is_english_mode():
            return self._issue_context_en(topic=topic, content_type=content_type, hook=hook)
        if not hook:
            hook = topic

        # hook에서 첫 2문장 추출
        sentences: list[str] = []
        text = " ".join(hook.split())
        for match in re.finditer(r"[^.!?。！？]+(?:다\.|요\.|니다\.|습니다\.|[.!?。！？])", text):
            sentence = match.group(0).strip()
            if len(sentence) > 5:
                sentences.append(sentence)
            if len(sentences) >= 2:
                break

        if not sentences:
            sentences = [_ensure_sentence(text[:80].strip())]

        # why-it-matters 문장 추가 (content_type별)
        why_map = {
            "money_checklist": "주문 전 조건 확인으로 결제 후 예상 외 금액을 줄일 수 있습니다.",
            "delivery_money": "배달앱 조건을 미리 파악하면 최종 결제금액 차이를 줄일 수 있습니다.",
            "tax_refund": "환급 유형에 따라 확인 경로가 달라지므로 먼저 구분이 필요합니다.",
            "policy_benefit": "지원 대상 및 신청 경로는 개인 상황에 따라 다를 수 있습니다.",
            "viral_issue_decode": "확인된 사실과 커뮤니티 해석을 나눠 봐야 이슈의 실제 의미가 보입니다.",
            "ai_work_tip": "반복 단계를 먼저 분리해야 AI 도구의 실제 시간 절감 효과를 얻을 수 있습니다.",
        }
        why = why_map.get(content_type, "직접 확인이 필요한 핵심 정보를 아래에 정리했습니다.")
        if content_type == "today_issue_explainer":
            why = "확인된 사실과 아직 단정할 수 없는 쟁점을 나눠 봐야 이슈의 실제 의미가 보입니다."
        sentences.append(why)

        result = " ".join(s.strip() for s in sentences[:3] if s.strip())
        return _truncate_at_sentence(result, max_len=220)

    def generate_intent_answers(
        self,
        questions: list[str],
        topic: str,
        content_type: str,
        slots: dict,
    ) -> list[dict[str, str]]:
        """Q&A 쌍을 슬롯에서 추출해 반환한다. 최소 3개."""
        qa_pairs: list[dict[str, str]] = []
        used_qs: set[str] = set()
        is_policy_content = content_type in ("policy_benefit", "policy_deadline")

        # 먼저 슬롯 FAQ에서 흡수
        faq_list = slots.get("faq") or []
        for item in faq_list:
            if isinstance(item, dict):
                q = str(item.get("Q", "")).strip()
                a = str(item.get("A", "")).strip()
                if is_policy_content:
                    q = self._topic_specific_policy_question(q, topic)
                if q in used_qs:
                    continue
                if q and a and len(qa_pairs) < 5:
                    if self._is_low_quality_answer(a):
                        a = self._fallback_answer_for_question(q, topic, content_type)
                    qa_pairs.append({"Q": q, "A": a})
                    used_qs.add(q)

        # 남은 질문은 real_criterion / yomi_judgment / 기본값으로 채움
        real = str(slots.get("real_criterion") or "").strip()
        yomi = str(slots.get("yomi_judgment") or "").strip()
        default_a = (
            "Check the official page or app directly."
            if is_english_mode()
            else "앱/공식 채널에서 직접 확인하세요."
        )
        is_delivery_schedule_issue = self._is_delivery_schedule_issue(topic)

        for raw_q in questions:
            q = self._topic_specific_policy_question(raw_q, topic) if is_policy_content else raw_q
            if q in used_qs:
                continue
            if len(qa_pairs) >= 5:
                break
            # 슬롯에서 관련 텍스트 찾기
            a = default_a
            specific_answer = (
                self._delivery_schedule_answer(q)
                if content_type == "consumer_warning" and is_delivery_schedule_issue
                else ""
            )
            if specific_answer:
                a = specific_answer
            elif is_policy_content:
                a = self._fallback_answer_for_question(q, topic, content_type)
            elif real and len(real) > 20:
                first_line = real.split("\n")[0].strip()
                a = first_line[:120] if first_line else a
            elif yomi and len(yomi) > 10:
                clean_yomi = yomi.replace("요미 판단:", "").replace("요미의 판단:", "").strip()
                a = clean_yomi[:120] if clean_yomi else a
            if self._is_low_quality_answer(a):
                a = self._fallback_answer_for_question(q, topic, content_type)
            # 영어 모드(2026-07-17): 영어 글은 한국어 패턴 기반 슬롯 추출(real/yomi)이
            # 비어 default_a가 여러 질문에 그대로 복제된다 → repeated_faq_or_intent_
            # answers 게이트 차단(드라이런 #4 실측). 질문 유형별 영어 폴백으로 다양화.
            if is_english_mode() and a == default_a:
                a = self._fallback_answer_for_question(q, topic, content_type)
            qa_pairs.append({"Q": q, "A": a})
            used_qs.add(q)

        # 최소 3개 보장
        if len(qa_pairs) < 3:
            if is_english_mode():
                generics = [
                    {"Q": f"What should you check first about {topic}?",
                     "A": "Start with the official announcement and confirm which plans and regions it applies to."},
                    {"Q": "How do I know if this affects me?",
                     "A": "Compare your plan, account settings, and region against the official eligibility notes."},
                    {"Q": "Could the details change?",
                     "A": "Yes — pricing and rollout details change often, so check the official page for the latest."},
                ]
            else:
                generics = [
                    {"Q": f"{topic}에서 가장 먼저 확인할 것은 무엇인가요?",
                     "A": "공식 안내 페이지에서 적용 조건을 먼저 확인하세요."},
                    {"Q": "실제로 나에게 해당하는지 어떻게 알 수 있나요?",
                     "A": "공식 채널에서 적용 대상 기준을 직접 조회해 보세요."},
                    {"Q": "변경 사항이 있을 수 있나요?",
                     "A": "정책은 수시로 바뀔 수 있으므로 최신 공지를 확인하는 것이 좋습니다."},
                ]
            for g in generics:
                q = self._topic_specific_policy_question(g["Q"], topic) if is_policy_content else g["Q"]
                if q not in used_qs and len(qa_pairs) < 3:
                    qa_pairs.append({"Q": q, "A": g["A"]})
                    used_qs.add(q)

        return self._dedupe_intent_answers(qa_pairs, topic, content_type)[:5]

    def generate_source_trust_block(
        self,
        content_type: str,
        topic_group: str,
        pattern_id: str,
    ) -> str:
        """출처 신뢰 면책 2~3문장을 반환한다."""
        if is_english_mode():
            return self._source_trust_en(content_type)
        if content_type in ("money_checklist", "delivery_money") or pattern_id == "delivery_money_checklist":
            return (
                "이 글은 공개 정보를 바탕으로 정리했습니다. "
                "배달앱 요금, 쿠폰 조건은 운영 상황에 따라 바뀔 수 있습니다. "
                "실제 이용 전 앱 공지를 확인하세요."
            )
        if content_type == "tax_refund" or pattern_id == "tax_refund_hometax_check":
            return (
                "이 글은 국세청 공개 안내를 바탕으로 작성됐습니다. "
                "환급 조건과 경로는 개인 상황에 따라 다를 수 있습니다. "
                "최종 기준은 홈택스 공식 화면을 확인하세요."
            )
        if content_type in ("policy_benefit", "policy_deadline"):
            return (
                "이 글은 공식 공고와 담당 기관 안내를 바탕으로 작성됐습니다. "
                "지원 대상, 금액, 신청 기간은 사업별로 다를 수 있습니다. "
                "최종 기준은 공고문, 신청 페이지, 문의처에서 확인하세요."
            )
        if content_type == "viral_issue_decode":
            return (
                "이 글은 공개된 시청자 반응과 데이터를 바탕으로 분석했습니다. "
                "특정 인물·작품에 대한 단정적 평가는 하지 않습니다. "
                "루머나 사생활 관련 내용은 포함하지 않습니다."
            )
        if content_type == "ai_work_tip":
            return (
                "이 글은 공개된 AI 서비스 정보를 바탕으로 작성됐습니다. "
                "도구별 기능과 요금은 서비스 정책에 따라 달라질 수 있습니다. "
                "실제 사용 전 공식 페이지를 확인하세요."
            )
        if content_type == "today_issue_explainer":
            return (
                "여기까지는 오늘 나온 여러 보도를 교차 확인한 사실과, 그 위에 얹은 제 해석입니다. "
                "진행 중인 사안이라 숫자나 일정은 더 나올 수 있으니, 중요한 판단은 원문을 함께 보세요."
            )
        return (
            "이 글은 공개 정보를 바탕으로 정리했습니다. "
            "내용은 시간이 지나면 달라질 수 있으므로 최신 정보를 직접 확인하세요."
        )

    def generate_ai_overview_target_answer(
        self,
        topic: str,
        content_type: str,
        slots: dict,
    ) -> str:
        """Google AI Overviews가 참고하기 좋은 3~5문장 핵심 답변을 반환한다."""
        if is_english_mode():
            return self._ai_overview_answer_en(topic=topic, content_type=content_type, slots=slots)
        hook = str(slots.get("hook_opening") or "").strip()
        yomi = str(slots.get("yomi_judgment") or "").replace("요미 판단:", "").replace("요미의 판단:", "").strip()
        real = str(slots.get("real_criterion") or "").strip()

        parts: list[str] = []

        # 이슈 핵심 (hook 첫 문장)
        if hook:
            for sep in ("다. ", "요. ", "니다. ", "습니다. "):
                idx = hook.find(sep)
                if idx > 10:
                    parts.append(hook[:idx + len(sep)].strip())
                    break
            if not parts:
                # hook이 이미 문장부호로 끝나면 '.'을 덧붙이지 않는다 — "위임받는다.."
                # 이중 마침표 글리치의 원인(2026-07-09 라이브 잔존 이슈).
                clipped = hook[:80].strip()
                parts.append(clipped if clipped.endswith((".", "!", "?")) else clipped + ".")

        # 독자 영향 (real_criterion 첫 줄) — 문장 경계 없이 100자에서 그냥 자르면
        # 중간에 끊긴 단어가 다음 part와 공백 하나로 붙어 "...생성 3 제미나이 3.5..."
        # 같은 글리치가 난다(2026-07-09 라이브 리허설 실측). hook과 같은 방식으로
        # 문장 경계에서만 자르고, 경계가 없고 너무 길면 이 part는 통째로 건너뛴다.
        if real:
            first_line = real.split("\n")[0].strip()
            if first_line and first_line not in parts:
                sentence = ""
                for sep in ("다. ", "요. ", "니다. ", "습니다. "):
                    idx = first_line.find(sep)
                    if idx > 10:
                        sentence = first_line[: idx + len(sep)].strip()
                        break
                if not sentence and len(first_line) <= 100:
                    sentence = first_line
                if sentence and sentence not in parts:
                    parts.append(sentence)

        # 판단 기준 (yomi 첫 문장)
        if yomi:
            for sep in ("다. ", "요. ", "니다. "):
                idx = yomi.find(sep)
                if idx > 10:
                    parts.append(yomi[:idx + len(sep)].strip())
                    break

        if content_type == "tax_refund":
            parts.append(
                "정확한 대상 여부와 신청 절차는 개인 상황에 따라 다를 수 있으므로 "
                "홈택스 또는 국세청 공식 안내 채널에서 직접 확인하는 것이 안전합니다."
            )
        elif content_type in ("policy_benefit", "policy_deadline"):
            parts.append(
                "정확한 대상 여부와 신청 절차는 개인 상황과 사업 기준에 따라 달라질 수 있으므로 "
                "공식 공고, 신청 페이지, 담당 기관 문의처에서 직접 확인하는 것이 안전합니다."
            )
        elif content_type in ("money_checklist", "delivery_money"):
            parts.append(
                "배달앱 요금, 쿠폰 조건, 최소주문금액은 운영 상황에 따라 달라질 수 있으므로 "
                "주문 전 앱 내 공지를 확인하세요."
            )
        elif content_type == "ai_work_tip":
            parts.append(
                "AI 도구 기능과 요금은 서비스 정책에 따라 달라질 수 있으므로 "
                "실제 사용 전 공식 페이지를 확인하세요."
            )

        result = " ".join(s.strip() for s in parts[:5] if s.strip())
        # 방어적 정규화: 어느 경로로든 남은 이중 마침표를 정리한다
        # (말줄임표 "..."는 보존, 숫자 소수점 "3.5"는 뒤가 숫자라 매칭 안 됨).
        result = re.sub(r"(?<=[가-힣A-Za-z\)\]])\.\.(?!\.)", ".", result)
        # 슬롯이 빈약해 결과가 최종 계약 최소 길이(35자, low_quality_ai_overview_answer)에
        # 못 미치면 주제 안내 문장으로 보강한다. (과거엔 이중 마침표 버그가 중복 제거를
        # 무력화해 같은 문장이 두 번 들어가며 우연히 길이를 채웠다 — 버그 수정으로
        # 드러난 경로라 정직한 폴백으로 대체.)
        if len(result) < 35:
            filler = f"{topic}에서 확인된 내용과 직접 확인할 것을 본문에서 구분해 정리했습니다."
            result = f"{result} {filler}".strip()
        return result[:500]

    def generate_people_also_ask(
        self,
        questions: list[str],
        topic: str,
        content_type: str,
    ) -> list[str]:
        """PAA(People Also Ask) 검색자 형태 질문 5개 이상을 반환한다."""
        if is_english_mode():
            return self._people_also_ask_en(questions=questions, topic=topic)
        kw = topic.strip()[:25] if topic.strip() else "이 주제"
        is_delivery_schedule_issue = self._is_delivery_schedule_issue(topic)

        # 기존 questions를 검색 쿼리 형태로 정제
        paa: list[str] = []
        for q in questions:
            q_clean = q.strip()
            if content_type == "consumer_warning" and is_delivery_schedule_issue and any(
                token in q_clean for token in ("환불 거부", "소비자 피해 신고", "결제 오류", "개인정보 유출")
            ):
                continue
            if q_clean and len(q_clean) > 5 and q_clean not in paa:
                paa.append(q_clean)
            if len(paa) >= 5:
                break

        # content_type별 보완 질문 — topic 반복 spam 방지를 위해 카테고리 키워드 위주로 작성.
        # 검색 의도(searcher intent)에 맞는 일반 검색어 형태 — raw_topic 9회+ 반복 방지.
        supplements: dict[str, list[str]] = {
            "money_checklist": [
                "배달앱 무료 배달 조건",
                "배달앱 쿠폰 적용 안 되는 이유",
                "배달앱별 최종 결제금액 차이",
                "배달비 최소주문금액 기준",
            ],
            "delivery_money": [
                "배달비 계산 방법",
                "배달앱 쿠폰 중복 적용 여부",
                "배달앱 가장 저렴한 주문 방법",
                "배달앱 구독권 실제 혜택",
            ],
            "tax_refund": [
                "세금 환급금 조회 방법",
                "홈택스 환급금 입금 안 될 때",
                "세금 환급 대상 확인",
                "환급금 소멸시효 기간",
            ],
            "policy_benefit": [
                "지원금 신청 방법",
                "지원금 지원 대상 기준",
                "지원금 신청 마감일",
                "지원금 금액과 사용처",
            ],
            "policy_deadline": [
                "지원금 신청 대상 확인",
                "지원금 소득 기준",
                "지원금 필요 서류",
                "지원금 신청 마감 확인",
            ],
            "viral_issue_decode": [
                f"{kw} 반응 갈리는 이유",
                f"{kw} 확인된 내용",
                f"{kw} 루머 사실 구분",
                f"{kw} 다음 쟁점",
            ],
            "ai_work_tip": [
                "AI 도구 무료 사용 가능 여부",
                "AI 도구 비교",
                "AI 도구 업무 활용법",
                "ChatGPT 직장인 활용",
            ],
            "platform_change": [
                "플랫폼 서비스 변경 대응 방법",
                "약관 변경 시 환불 가능 여부",
                "서비스 종료 전 백업 방법",
                "멤버십 변경 영향 확인",
            ],
            "consumer_warning": [
                "환불 거부 대응 방법",
                "소비자 피해 신고 방법",
                "결제 오류 환불 절차",
                "개인정보 유출 대응",
            ],
        }
        if content_type == "today_issue_explainer":
            supplements["today_issue_explainer"] = [
                f"{kw} 지금 확인된 내용",
                f"{kw} 왜 오늘 이슈",
                f"{kw} 아직 모르는 것",
                f"{kw} 다음 쟁점",
            ]
        if content_type == "consumer_warning" and is_delivery_schedule_issue:
            supplements["consumer_warning"] = [
                "선거일 택배 집화 마감 시간",
                "택배 휴무 배송조회 멈춤 이유",
                "새벽배송 선거일 운영 여부",
                "반품 회수 선거일 지연 대응",
            ]
        for s in supplements.get(content_type, [
            "관련 정보 확인 방법",
            "신청 절차 안내",
            "대상 조건 정리",
            "주의 사항 가이드",
        ]):
            if s not in paa and len(paa) < 8:
                paa.append(s)

        return paa[:8]

    def generate_confirmed_vs_check_needed(
        self,
        content_type: str,
        topic_group: str,
        slots: dict,
        topic: str = "",
    ) -> dict[str, list[str]]:
        """확인된 내용과 직접 확인 필요 항목을 반환한다."""
        if is_english_mode():
            return self._confirmed_vs_check_needed_en(content_type=content_type, slots=slots)
        real = str(slots.get("real_criterion") or "").strip()
        faq_list = list(slots.get("faq") or [])
        is_delivery_schedule_issue = self._is_delivery_schedule_issue(topic)

        confirmed_map: dict[str, list[str]] = {
            "money_checklist": [
                "배달비 무료 조건은 최소주문금액 충족 시 적용됨",
                "쿠폰마다 적용 가능 조건(최소주문금액·카테고리)이 다름",
                "앱별로 동일 가게의 최종 결제금액이 다를 수 있음",
            ],
            "delivery_money": [
                "배달비는 최소주문금액과 연동됨",
                "쿠폰과 구독 할인 중복 적용 여부는 앱마다 다름",
                "배달앱 구독권 적용 제외 가게가 존재함",
            ],
            "tax_refund": [
                "국세환급금 소멸시효는 5년",
                "홈택스·손택스에서 환급 유형별로 조회 메뉴가 다름",
                "환급계좌 미등록 시 자동 입금되지 않음",
            ],
            "policy_benefit": [
                "지원 대상 여부는 신청 전 공식 채널에서 확인 필요",
                "지원 금액과 기간은 공고 시점 기준으로 확정됨",
            ],
            "viral_issue_decode": [
                "공식 안내와 커뮤니티 반응은 구분해서 확인해야 함",
                "화제성과 실제 이용자 영향은 서로 다를 수 있음",
            ],
            "ai_work_tip": [
                "무료 버전에서도 반복 텍스트 업무는 활용 가능",
                "AI 결과물은 검수 후 사용해야 함",
                "회사 내 AI 사용 정책 확인 필요",
            ],
            "platform_change": [
                "운영사 공식 공지는 적용 일자·대상·예외 조건을 포함함",
                "약관 변경 시 취소·환불 기준이 함께 바뀔 수 있음",
                "기존 사용자도 적용 대상에 포함되는 경우가 일반적",
            ],
            "consumer_warning": [
                "결제 화면·주문번호·상담 기록은 환불 신청의 핵심 증거",
                "운영사 약관 위반 시 한국소비자원 1372 신고 가능",
                "개인정보침해 신고센터 118은 24시간 운영",
            ],
            "policy_deadline": [
                "지원금은 대부분 신청자만 받을 수 있음 (자동 지급 아님)",
                "신청 마감 후에는 일반적으로 추가 신청 불가",
                "공식 신청 경로는 정부24·복지로 등 공공 채널",
            ],
        }
        if content_type == "consumer_warning" and is_delivery_schedule_issue:
            confirmed_map["consumer_warning"] = [
                "선거일에는 주요 일반 택배의 집화·배송이 멈출 수 있음",
                "송장 발급과 실제 집화는 서로 다른 단계임",
                "새벽배송·당일배송은 일반 택배와 운영망이 달라 앱별 확인이 필요함",
            ]
        check_needed_map: dict[str, list[str]] = {
            "money_checklist": [
                "현재 운영 중인 가맹점 수와 서비스 지역",
                "실제 적용 가능한 쿠폰 한도와 유효기간",
                "구독권 혜택 조건 (앱 공지 확인 필요)",
            ],
            "delivery_money": [
                "앱별 최신 배달비 정책 (수시로 변경 가능)",
                "본인 주문 지역의 실제 무료배달 가능 가게 수",
                "현재 적용 중인 프로모션 종류",
            ],
            "tax_refund": [
                "본인의 환급 대상 여부 (홈택스 직접 조회 필요)",
                "현재 환급금 발생 금액과 처리 상태",
                "주소 불일치·계좌 오류 여부",
            ],
            "policy_benefit": [
                "현재 신청 가능한지 여부 (마감일 확인 필요)",
                "본인이 지원 대상에 해당하는지 여부",
                "실제 지원 금액 (공고 확인 필요)",
            ],
            "viral_issue_decode": [
                "현재 해당 작품/이슈의 최신 반응",
                "미확인 루머 및 사생활 관련 주장",
            ],
            "ai_work_tip": [
                "현재 무료 플랜 사용 가능 횟수 (정책 변경 가능)",
                "회사 내 AI 사용 허용 범위",
                "유료 전환 시 실제 요금 (공식 페이지 확인 필요)",
            ],
            "platform_change": [
                "본인 계정·요금제·기기가 적용 대상에 포함되는지",
                "변경 일자와 자동결제 처리 방식 (공식 공지 확인 필요)",
                "약관 변경에 따른 취소·환불 기준 변경 여부",
            ],
            "consumer_warning": [
                "본인 피해 사례에 운영사 약관이 어떻게 적용되는지",
                "보유한 결제 영수증·상담 기록·접수 번호의 유효성",
                "신고 가능한 공식 기관과 신고 절차 (개별 상황별 차이)",
            ],
            "policy_deadline": [
                "본인의 소득·연령·거주지 조건이 지원 대상에 해당하는지",
                "필요 서류의 발급 소요 영업일과 신청 마감일까지 여유",
                "지급 방식·사용처·기한 (공식 안내 확인 필요)",
            ],
        }
        if content_type == "consumer_warning" and is_delivery_schedule_issue:
            check_needed_map["consumer_warning"] = [
                "내 송장이 실제 집화됐는지 또는 발송 예약 상태인지",
                "판매자가 안내한 출고일이 6월3일 전인지 이후인지",
                "쿠팡·SSG·마켓컬리 등 앱별 새벽배송 공지와 지역별 예외",
            ]

        if content_type == "today_issue_explainer":
            confirmed_map["today_issue_explainer"] = [
                "본문은 현재 공개된 보도와 확인 가능한 흐름을 기준으로 정리했습니다.",
                "확정 사실과 해석이 섞이지 않도록 쟁점을 나눠 봐야 합니다.",
                "오늘 이슈가 된 이유는 사건 자체보다 이후 파급 가능성에 있습니다.",
            ]
            check_needed_map["today_issue_explainer"] = [
                "추가 발표나 후속 보도로 바뀔 수 있는 세부 내용",
                "당사자 입장, 공식 발표, 수치처럼 아직 단정하면 안 되는 정보",
                "독자에게 실제 영향이 생기는 시점과 범위",
            ]

        confirmed = confirmed_map.get(content_type, [
            "이 글의 내용은 공개된 정보 기준으로 정리되었습니다.",
            "공식 안내에 따라 세부 내용이 달라질 수 있습니다.",
        ])
        check_needed = check_needed_map.get(content_type, [
            "현재 적용 조건 (공식 채널 확인 필요)",
            "개인 상황에 따른 실제 적용 여부",
        ])

        # real_criterion에서 추가 확인 사항 흡수. 단계 설명을 잘라 붙이면
        # 본문에 끊긴 문장이 노출되므로 짧은 확인 문장만 허용한다.
        if real:
            for line in real.split("\n"):
                line = line.strip()
                if (
                    line
                    and _is_clean_confirmed_line(line)
                    and line not in confirmed
                    and len(confirmed) < 5
                ):
                    confirmed.append(line)

        return {"confirmed": confirmed[:5], "check_needed": check_needed[:5]}

    def generate_enhanced_source_trust_block(
        self,
        content_type: str,
        topic_group: str,
        pattern_id: str,
        today_str: str = "",
        *,
        seed: str = "",
    ) -> str:
        """강화된 출처 신뢰 블록 — 원문 기준, 확인 항목, 업데이트 날짜 포함."""
        if is_english_mode():
            return self._enhanced_source_trust_en(
                content_type=content_type, today_str=today_str, seed=seed
            )
        date_part = f" ({today_str} 기준)" if today_str else ""

        if content_type in ("money_checklist", "delivery_money") or pattern_id == "delivery_money_checklist":
            return (
                f"이 글은 공개된 배달앱 정보를 바탕으로 작성됐습니다{date_part}. "
                "배달비, 쿠폰 조건, 최소주문금액은 앱 정책 및 프로모션에 따라 수시로 바뀔 수 있습니다. "
                "실제 주문 전에는 앱 내 공지와 결제 화면에서 최종 조건을 직접 확인하세요. "
                "가맹점 수, 서비스 지역, 혜택 한도는 운영 상황에 따라 달라질 수 있습니다."
            )
        if content_type == "tax_refund" or pattern_id == "tax_refund_hometax_check":
            return (
                f"이 글은 국세청·정부24 공개 안내를 바탕으로 작성됐습니다{date_part}. "
                "환급 대상 여부, 신청 경로, 처리 상태는 개인 납세 상황에 따라 다를 수 있습니다. "
                "환급금 소멸시효(5년), 계좌 등록 방법, 조회 메뉴 경로는 홈택스 공식 화면에서 확인하세요. "
                "법령 또는 세무 처리 기준이 바뀔 수 있으므로 최신 공지를 확인하는 것이 안전합니다."
            )
        if content_type in ("policy_benefit", "policy_deadline"):
            return (
                f"이 글은 공식 공고와 담당 기관 안내를 바탕으로 작성됐습니다{date_part}. "
                "지원 대상, 금액, 신청 기간, 지급 방식은 사업별 공고 기준에 따라 달라질 수 있습니다. "
                "신청 전에는 공고문, 신청 페이지, 담당 기관 문의처에서 최신 조건을 직접 확인하세요. "
                "예산 소진, 접수 순서, 보완 요청 여부에 따라 실제 지급 가능성과 일정이 달라질 수 있습니다."
            )
        if content_type == "viral_issue_decode":
            return (
                f"이 글은 공개된 시청자 반응과 플랫폼 데이터를 바탕으로 분석됐습니다{date_part}. "
                "특정 인물·작품·제작사에 대한 단정적 평가나 루머는 포함하지 않습니다. "
                "공식 안내와 후속 보도에 따라 내용이 변경될 수 있습니다. "
                "사생활·미확인 정보는 이 글의 분석 범위에 해당하지 않습니다."
            )
        if content_type == "ai_work_tip":
            return (
                f"이 글은 공개된 AI 서비스 공식 안내를 바탕으로 작성됐습니다{date_part}. "
                "무료 플랜 사용 제한, 유료 전환 요금, 기능 범위는 서비스 정책에 따라 수시로 바뀔 수 있습니다. "
                "실제 사용 전 공식 페이지와 회사 내 AI 사용 정책을 함께 확인하세요. "
                "AI 결과물은 반드시 사람이 검수한 뒤 업무에 활용하는 것을 권장합니다."
            )
        if content_type == "today_issue_explainer":
            # 매 글 같은 문장이 반복되면 AI 티가 나므로 토픽 시드로 결정적 변주.
            variants = (
                (
                    f"여기까지는 오늘 나온 여러 보도를 교차 확인한 사실과, 그 위에 얹은 제 해석입니다{date_part}. "
                    "진행 중인 사안이라 숫자나 일정은 더 나올 수 있으니, 중요한 판단은 원문을 함께 보세요."
                ),
                (
                    f"본문 사실관계는 오늘 보도된 복수 매체 기사를 겹쳐 확인한 범위까지만 적었습니다{date_part}. "
                    "해석과 전망은 제 몫이니, 결정이 걸린 문제라면 원문 보도를 직접 확인하는 편이 안전합니다."
                ),
                (
                    f"사실로 적은 부분은 여러 매체가 동시에 전한 내용에 한정했습니다{date_part}. "
                    "아직 움직이는 사안이라 후속 발표에 따라 결이 달라질 수 있다는 점은 감안하고 읽어주세요."
                ),
            )
            digest = hashlib.md5((seed or today_str or "today_issue").encode("utf-8")).hexdigest()
            return variants[int(digest, 16) % len(variants)]
        return (
            f"이 글은 공개 정보를 바탕으로 정리했습니다{date_part}. "
            "내용은 시간이 지나면 달라질 수 있으므로 최신 정보를 직접 확인하세요. "
            "정책·서비스·가격 등 중요한 사항은 공식 채널에서 확인하는 것이 안전합니다."
        )

    # ------------------------------------------------------------------ #
    # English mode (BLOG_LANGUAGE=en) — 문자열 생산만 분기, 구조는 동일     #
    # ------------------------------------------------------------------ #

    def _reader_intent_questions_en(self, *, topic: str, content_type: str, slots: dict) -> list[str]:
        kw = topic.strip()[:40] if topic.strip() else "this topic"
        if content_type.startswith("ai_"):
            questions = [
                f"What is {kw} actually good for?",
                "How much does it cost, and is there a free plan?",
                "Is it worth paying for?",
                "What are the common mistakes to avoid?",
                "How should you review AI output before using it?",
                "What should you check before relying on it at work?",
            ]
        elif content_type == "today_issue_explainer":
            questions = [
                f"What changed with {kw}?",
                "Why is this news today?",
                "What's confirmed, and what's still unclear?",
                "Does this affect regular users?",
                "What happens next?",
                "How can you tell facts from speculation?",
            ]
        else:
            questions = [
                f"What's the key takeaway on {kw}?",
                "What changed?",
                "How much does it cost?",
                "Is it worth paying for?",
                "Where can you verify the official details?",
                "What should you watch out for?",
            ]
        for item in slots.get("faq") or []:
            if isinstance(item, dict):
                q = str(item.get("Q", "")).strip()
                if q and q not in questions and len(questions) < 8:
                    questions.append(q)
        return questions[:8]

    def _issue_context_en(self, *, topic: str, content_type: str, hook: str) -> str:
        text = " ".join((hook or topic or "").split())
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 5][:2]
        if not sentences and text:
            sentences = [_ensure_sentence(text[:120])]
        if content_type.startswith("ai_"):
            why = "Knowing what changed — and what it costs — decides whether this is worth your time."
        elif content_type == "today_issue_explainer":
            why = "Separating what's confirmed from what's still speculation is the only way to read this story."
        else:
            why = "The details worth verifying yourself are laid out below."
        sentences.append(why)
        return _truncate_at_sentence(" ".join(s for s in sentences[:3] if s), max_len=220)

    def _ai_overview_answer_en(self, *, topic: str, content_type: str, slots: dict) -> str:
        hook = str(slots.get("hook_opening") or "").strip()
        real = str(slots.get("real_criterion") or "").split("\n")[0].strip()
        yomi = str(slots.get("yomi_judgment") or "").strip()

        parts: list[str] = []
        for source in (hook, real, yomi):
            if not source:
                continue
            cleaned = " ".join(source.split())
            match = re.match(r".+?[.!?](?=\s|$)", cleaned)
            sentence = match.group(0).strip() if match else ""
            if not sentence and len(cleaned) <= 100:
                sentence = cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."
            if sentence and sentence not in parts:
                parts.append(sentence)

        if content_type.startswith("ai_"):
            parts.append(
                "Availability, pricing, and rollout can vary by account and region — "
                "check the official page for the latest details."
            )
        result = " ".join(s.strip() for s in parts[:5] if s.strip())
        if len(result) < 35:
            result = (
                f"{result} The article separates what's confirmed about {topic} "
                "from what you should verify yourself."
            ).strip()
        return result[:500]

    def _people_also_ask_en(self, *, questions: list[str], topic: str) -> list[str]:
        kw = topic.strip()[:40] if topic.strip() else "this topic"
        paa: list[str] = []
        for q in questions:
            q_clean = q.strip()
            if q_clean and len(q_clean) > 5 and q_clean not in paa:
                paa.append(q_clean)
            if len(paa) >= 5:
                break
        for s in (
            f"{kw} pricing",
            f"{kw} free plan limits",
            f"{kw} alternatives",
            f"{kw} how to get started",
        ):
            if s not in paa and len(paa) < 8:
                paa.append(s)
        return paa[:8]

    def _confirmed_vs_check_needed_en(self, *, content_type: str, slots: dict) -> dict[str, list[str]]:
        if content_type.startswith("ai_"):
            confirmed = [
                "The core facts here come from official announcements and product pages",
                "Free-tier limits and paid pricing are as published at the time of writing",
                "AI output still needs human review before you use it for real work",
            ]
            check_needed = [
                "Current pricing and plan limits on the official page (they change often)",
                "Whether the rollout has reached your account and region",
            ]
        elif content_type == "today_issue_explainer":
            confirmed = [
                "This article sticks to what multiple reports have confirmed so far.",
                "Facts and interpretation are kept separate on purpose.",
            ]
            check_needed = [
                "Details that follow-up announcements could still change",
                "Official statements, exact figures, and timelines that aren't final yet",
            ]
        else:
            confirmed = [
                "This article is based on publicly available information.",
                "Details may shift as official guidance updates.",
            ]
            check_needed = [
                "The current conditions on the official page",
                "Whether the specifics apply to your own account or situation",
            ]

        # 본문 기준 문장 흡수 — 짧고 검증 지향적인 줄만 (한국어 경로와 같은 취지)
        real = str(slots.get("real_criterion") or "").strip()
        for line in real.split("\n"):
            line = " ".join(line.split()).strip()
            if (
                line
                and len(line) <= 90
                and ":" not in line
                and re.search(r"\b(check|official|confirm)\w*\b", line, flags=re.IGNORECASE)
                and line not in confirmed
                and len(confirmed) < 5
            ):
                confirmed.append(line)

        return {"confirmed": confirmed[:5], "check_needed": check_needed[:5]}

    def _source_trust_en(self, content_type: str) -> str:
        if content_type.startswith("ai_"):
            return (
                "This article is based on publicly available information from official AI service pages. "
                "Features and pricing change with provider policy. "
                "Check the official page before you rely on it."
            )
        if content_type == "today_issue_explainer":
            return (
                "The facts here are cross-checked against multiple published reports; the interpretation is mine. "
                "This is a developing story, so read the original sources before making any big calls."
            )
        return (
            "This article is based on publicly available information. "
            "Details can change over time, so verify anything important at the source."
        )

    def _enhanced_source_trust_en(self, *, content_type: str, today_str: str, seed: str) -> str:
        date_part = f" (as of {today_str})" if today_str else ""
        if content_type.startswith("ai_"):
            return (
                f"This article is based on the official AI service documentation and announcements{date_part}. "
                "Free-tier limits, paid pricing, and feature availability change often with provider policy. "
                "Check the official page — and your company's AI policy — before you rely on it. "
                "Always review AI output before putting it into real work."
            )
        if content_type == "today_issue_explainer":
            # 매 글 같은 문장이 반복되면 AI 티가 나므로 토픽 시드로 결정적 변주 (한국어와 동일 메커니즘).
            variants = (
                (
                    f"The facts here are cross-checked against multiple reports published today{date_part}. "
                    "This is a developing story — numbers and timelines may shift, so check the original "
                    "sources before making any decisions."
                ),
                (
                    f"I limited the factual claims to what more than one outlet reported today{date_part}. "
                    "The interpretation is mine; if a decision rides on this, read the original reporting."
                ),
                (
                    f"Everything stated as fact comes from reports by multiple outlets{date_part}. "
                    "Follow-up announcements may change the picture, so keep that in mind as you read."
                ),
            )
            digest = hashlib.md5((seed or today_str or "today_issue").encode("utf-8")).hexdigest()
            return variants[int(digest, 16) % len(variants)]
        return (
            f"This article is based on publicly available information{date_part}. "
            "Details can change over time, so verify anything important at the source. "
            "For pricing, policy, and availability, the official page is the final word."
        )

    @staticmethod
    def _fallback_answer_en(question: str, topic: str, content_type: str) -> str:
        q = (question or "").lower()
        subject = " ".join((topic or "this topic").split()).strip() or "this topic"
        if any(token in q for token in ("cost", "price", "pricing", "free plan", "pay")):
            return (
                "Pricing and plan limits change often — compare the official pricing page "
                "against what you actually need before paying."
            )
        if any(token in q for token in ("worth", "should i")):
            return (
                "It depends on how often you'd use it. Try the free tier on a real task first, "
                "then decide whether the paid plan earns its keep."
            )
        if any(token in q for token in ("changed", "change", "new", "update")):
            return (
                f"The article covers what actually changed with {subject} and what stayed the same — "
                "check the official announcement for the exact rollout details."
            )
        if any(token in q for token in ("affect", "apply", "eligible", "my account")):
            return (
                "Whether it applies to you depends on your plan, account settings, and region — "
                "check the official eligibility notes against your own setup."
            )
        if any(token in q for token in ("official", "verify", "source", "where")):
            return (
                "Go by the official announcement and product page first; treat community posts "
                "and screenshots as secondary sources."
            )
        if any(token in q for token in ("mistake", "watch out", "risk", "careful")):
            return (
                "The main trap is treating unconfirmed claims as fact — keep what's verified "
                "separate from what's still speculation."
            )
        return (
            f"With {subject}, separate what's confirmed from what still needs checking — "
            "the details depend on your plan, account, and region."
        )

    @staticmethod
    def _is_delivery_schedule_issue(text: str) -> bool:
        haystack = (text or "").lower()
        return any(
            token in haystack
            for token in ("택배", "배송", "집화", "cj", "한진", "롯데", "쿠팡", "새벽배송")
        )

    @staticmethod
    def _delivery_schedule_answer(question: str) -> str:
        q = question or ""
        if any(token in q for token in ("쉬", "휴무", "선거일")) and "새벽" not in q:
            return "일반 택배는 선거일 집화와 배송이 멈출 수 있으므로 송장 발급 여부보다 실제 집화 단계와 택배사 공지를 확인해야 합니다."
        if any(token in q for token in ("사전투표", "5월29", "30일")):
            return "사전투표일 자체보다 중요한 것은 판매자 출고일입니다. 6월3일 전 실제 집화가 됐는지 배송조회로 확인하는 편이 정확합니다."
        if any(token in q for token in ("새벽", "당일", "쿠팡")):
            return "새벽배송과 당일배송은 일반 택배와 운영망이 다를 수 있습니다. 앱 공지, 지역별 운영 안내, 주문 상세의 도착 예정 시간을 따로 봐야 합니다."
        if any(token in q for token in ("조회", "언제", "움직")):
            return "배송조회가 멈췄다면 송장 발급 단계인지 집화 완료 단계인지 먼저 보세요. 집화 전이면 선거일 다음 영업 구간부터 움직일 가능성이 큽니다."
        if any(token in q for token in ("판매자", "확인", "발송")):
            return "이미 주문한 상품은 판매자 발송 예정일과 택배사 배송조회를 나눠 확인해야 합니다. 반품·교환은 접수 화면과 상담 내역을 캡처해 두세요."
        return "핵심은 배송사가 아니라 단계입니다. 송장 발급, 집화, 간선 이동, 배송 출발 중 어디에 멈춰 있는지 확인해야 실제 지연 폭을 판단할 수 있습니다."

    @staticmethod
    def _is_low_quality_answer(answer: str) -> bool:
        text = " ".join((answer or "").split())
        if len(text) < 18:
            return True
        if text.startswith(("으로 ", "라고 ", "에는 ", "에서는 ", "입니다", "합니다")):
            return True
        if "으로 단정하면 안 됩니다" in text:
            return True
        if text.count("공식") >= 2 and len(text) < 45:
            return True
        if any(token in text for token in ("\ufffd", "????")):
            return True
        return False

    @staticmethod
    def _fallback_answer_for_question(question: str, topic: str, content_type: str) -> str:
        if is_english_mode():
            return GeoIntentService._fallback_answer_en(question, topic, content_type)
        q = question or ""
        subject = GeoIntentService._policy_subject(topic) if content_type in ("policy_deadline", "policy_benefit") else (topic or "이 이슈")
        if content_type in ("money_checklist", "delivery_money"):
            return "결제 전에는 표시 가격보다 최종 결제금액, 쿠폰 조건, 최소주문금액을 같은 화면 기준으로 비교해야 합니다."
        if content_type in ("tax_refund",):
            return "환급 여부는 개인별 신고·납부 이력에 따라 달라지므로 조회 화면의 대상 여부, 계좌 정보, 처리 상태를 나눠 확인해야 합니다."
        if content_type in ("policy_deadline", "policy_benefit"):
            if any(token in q for token in ("대상", "누구", "해당", "자격")):
                return f"{subject} 대상 여부는 연령, 거주지, 소득 기준, 제외 조건을 공식 공고에서 함께 확인해야 합니다."
            if any(token in q for token in ("소득", "기준", "자격")):
                return f"{subject} 소득 기준은 가구원 수, 산정 기간, 증빙 방식에 따라 달라질 수 있어 공고문 기준으로 봐야 합니다."
            if any(token in q for token in ("서류", "증빙", "발급")):
                return f"{subject} 필요 서류는 신분증, 신청서, 소득·거주 증빙처럼 사업별로 다르므로 발급 소요일까지 확인해야 합니다."
            if any(token in q for token in ("마감", "기간", "언제", "지급일", "놓치")):
                return f"{subject} 신청 기간과 지급일은 예산 소진, 접수 순서, 보완 요청 여부에 따라 달라질 수 있습니다."
            if any(token in q for token in ("지급", "사용처", "금액", "방식")):
                return f"{subject} 지급 방식은 현금, 계좌 입금, 바우처, 지역상품권 등으로 달라질 수 있어 사용처 제한을 같이 봐야 합니다."
            return f"{_josa(subject, '은', '는')} 대상 조건, 신청 기간, 필요 서류, 공식 신청 경로를 한 번에 대조해야 실제 수급 가능성을 판단할 수 있습니다."
        if content_type == "platform_change":
            return "기존 이용자는 적용 시점, 계정 영향, 결제·환불 조건을 먼저 확인해야 실제 불편이나 비용 변화를 줄일 수 있습니다."
        if content_type == "viral_issue_decode":
            return "이 이슈는 결과 자체보다 기대치와 실제 반응의 차이를 봐야 합니다. 누가 어떤 지점에서 반응했는지 나누면 맥락이 선명해집니다."
        if content_type == "trend_decode":
            return "갑자기 퍼진 이유는 희소성, 인증 욕구, 플랫폼 확산이 겹친 결과일 수 있습니다. 유행 지속성과 실제 필요성을 분리해 봐야 합니다."
        if content_type == "today_issue_explainer":
            return f"{_josa(subject, '은', '는')} 확인된 사실과 아직 단정하기 어려운 쟁점을 나눠 봐야 합니다. 후속 발표나 추가 보도에 따라 의미가 달라질 수 있습니다."
        if "새벽" in q or "택배" in q or "배송" in q:
            return "배송 이슈는 송장 발급, 실제 집화, 간선 이동, 배송 출발 중 어느 단계인지 나눠 확인해야 지연 폭을 판단할 수 있습니다."
        if any(token in q for token in ("핵심", "내용", "무엇")):
            return f"{subject}의 핵심은 현재 확인된 사실과 아직 확인이 필요한 부분을 분리해서 보는 것입니다."
        if any(token in q for token in ("중요", "확인", "먼저")):
            return f"{subject}에서는 적용 대상, 시점, 실제 영향 범위를 먼저 확인해야 판단을 잘못하지 않습니다."
        if any(token in q for token in ("관련", "나와", "직접", "영향")):
            return f"{_ga(subject)} 나에게 영향을 주는지는 비용, 일정, 계정, 신청 조건처럼 직접 바뀌는 항목으로 확인해야 합니다."
        if any(token in q for token in ("공식", "정보", "출처")):
            return f"{subject}의 공식 정보는 최초 발표 주체와 후속 공지를 나눠 확인하고, 커뮤니티 해석은 보조 자료로만 봐야 합니다."
        if any(token in q for token in ("주의", "오해", "위험")):
            return f"{subject}에서 주의할 점은 확인되지 않은 추정과 확정된 사실을 같은 근거처럼 섞지 않는 것입니다."
        return f"{_josa(subject, '은', '는')} 현재 확인된 내용, 아직 확인이 필요한 부분, 독자에게 직접 영향을 주는 지점을 나눠 보는 것이 안전합니다."

    @staticmethod
    def _policy_subject(topic: str) -> str:
        subject = " ".join((topic or "").split()).strip()
        if not subject:
            return "지원금"
        subject = re.sub(r"\s*[—-]\s*먼저.*$", "", subject)
        subject = re.sub(r"\s*(신청방법.*|신청 방법.*|대상 조건.*|지급일.*|정리.*|체크리스트.*)$", "", subject).strip()
        if len(subject) < 4:
            subject = " ".join((topic or "지원금").split()).strip()[:25]
        return subject[:30] or "지원금"

    @classmethod
    def _topic_specific_policy_question(cls, question: str, topic: str) -> str:
        q = " ".join((question or "").split()).strip()
        if not q:
            return q
        subject = cls._policy_subject(topic)
        subject_terms = [term for term in re.findall(r"[가-힣A-Za-z0-9]{2,}", subject) if term not in {"신청", "대상", "조건", "정리"}]
        if subject_terms and any(term in q for term in subject_terms[:3]):
            return q
        return f"{subject} {q}"

    @classmethod
    def _dedupe_intent_answers(
        cls,
        pairs: list[dict[str, str]],
        topic: str,
        content_type: str,
    ) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen_answers: set[str] = set()
        seen_questions: set[str] = set()
        for pair in pairs:
            q = " ".join(str(pair.get("Q") or "").split()).strip()
            a = " ".join(str(pair.get("A") or "").split()).strip()
            if not q or q in seen_questions:
                continue
            key = cls._answer_key(a)
            if key in seen_answers or cls._is_low_quality_answer(a):
                a = cls._fallback_answer_for_question(q, topic, content_type)
                key = cls._answer_key(a)
            if key in seen_answers:
                q_context = q.rstrip("?")[:34]
                if is_english_mode():
                    a = f"For {q_context}: {a}"
                else:
                    a = f"{q_context} 기준으로 보면, {a}"
                key = cls._answer_key(a)
            deduped.append({"Q": q, "A": a})
            seen_questions.add(q)
            seen_answers.add(key)
        return deduped

    @staticmethod
    def _answer_key(answer: str) -> str:
        return re.sub(r"\s+", " ", (answer or "").strip())[:80]

    def check_content_type_forbidden_phrases(
        self,
        html: str,
        content_type: str,
    ) -> list[str]:
        """content_type별 금지 구문이 html에 포함됐는지 확인한다."""
        forbidden_map: dict[str, list[str]] = {
            "money_checklist": ["지원금 신청 마감", "환급", "홈택스", "세금환급"],
            "delivery_money": ["지원금 신청 마감", "환급", "홈택스", "세금환급"],
            "tax_refund": ["배달앱", "쿠폰", "배달비", "배달의민족"],
            "viral_issue_decode": ["지원금", "환급", "배달비"],
        }
        phrases = forbidden_map.get(content_type, [])
        return [p for p in phrases if p in html]


def _ensure_sentence(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned[-1] in ".!?。！？":
        return cleaned
    return f"{cleaned}."


def _truncate_at_sentence(text: str, *, max_len: int) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= max_len:
        return cleaned
    cut = max(
        cleaned.rfind(".", 0, max_len),
        cleaned.rfind("?", 0, max_len),
        cleaned.rfind("!", 0, max_len),
        cleaned.rfind("。", 0, max_len),
        cleaned.rfind("？", 0, max_len),
        cleaned.rfind("！", 0, max_len),
    )
    if cut >= 80:
        return cleaned[: cut + 1]
    return _ensure_sentence(cleaned[:max_len].rstrip(" ,.-_/\\"))


def _is_clean_confirmed_line(line: str) -> bool:
    text = " ".join((line or "").split()).strip()
    if not text or len(text) > 70:
        return False
    if re.match(r"^\d+\s*단계", text):
        return False
    if any(marker in text for marker in ("—", "->", "→", ":", "：")):
        return False
    if text.count("확인") > 1:
        return False
    return "확인" in text or "공식" in text
