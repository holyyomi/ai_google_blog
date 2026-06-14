"""AI 슬롯 LLM 보강기 — 템플릿 구조는 유지하고 본문만 주제별 구체 내용으로 채운다.

설계 원칙(매일 발행 안전):
- LLM이 성공하면 주제 특화 내용으로 교체, 실패/형식 불량이면 템플릿 그대로 사용(폴백).
- 구조 슬롯(hook/yomi/real_criterion/misconceptions/use_cases/faq)만 텍스트 보강.
  표·체크리스트·프롬프트·가격표 등 형식 고정 슬롯은 건드리지 않는다.
- 사실 정확도를 위해 '확실하지 않으면 일반화하고 단정하지 말 것'을 시스템 프롬프트에 명시.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# content_type → 글 성격 힌트 (LLM 톤·초점 가이드)
_CT_FOCUS: dict[str, str] = {
    "ai_work_tip": "직장인이 이 주제로 실제 업무 시간을 줄이는 구체적 방법",
    "ai_prompt_recipe": "이 주제에 바로 쓰는 프롬프트 작성 원리와 실전 적용",
    "ai_tool_review": "이 도구/서비스의 실제 강점·약점·무료유료 경계·누구에게 맞는지",
    "ai_model_update": "이 업데이트로 새로 가능해진 것과 지금 바로 쓰는 활용법, 확인된 사실 위주",
    "ai_search_change": "이 검색/AEO/GEO 변화가 블로거·마케터에게 주는 실제 영향과 대응",
    "ai_blog_growth": "이 주제로 블로그 조회수·수익을 실제로 키우는 구체 전략",
    "ai_comparison": "비교 대상들의 실제 차이와 상황별 선택 기준",
    "ai_risk_security": "이 리스크의 실제 발생 양상과 구체적 예방·대응 방법",
    "ai_beginner_guide": "완전 초보가 이 주제를 처음 시작하는 쉬운 단계",
}

_SYSTEM_PROMPT = (
    "당신은 한국어 AI 전문 블로그의 시니어 에디터입니다. "
    "주제에 특정 도구·서비스 이름이 있으면 그 도구 하나에 집중해 깊이 있게 씁니다. "
    "초보용 일반론이 아니라, 잘 안 알려진 고급 활용법·실전 팁·숨은 기능 등 "
    "'유료 강의급'의 구체적 정보를 줍니다(구체적 메뉴·기능명·설정·예시 포함). "
    "단, 간결하게 씁니다. 군더더기·반복·당연한 말은 빼고 정보 밀도를 높입니다. "
    "광고·과장·자기소개·인사말 없이 핵심만 씁니다. "
    "확실하지 않은 수치·요금·날짜·기능은 단정하지 말고 '직접 확인 필요'로 표현합니다. "
    "특정 인물 비방, 허위 단정, 수익 보장 표현은 절대 쓰지 않습니다. "
    "반드시 유효한 JSON만 출력합니다(코드블록·설명 금지)."
)

# LLM이 채울 수 있는 텍스트형 슬롯과 출력 스펙 (간결·고밀도 지향)
_ENRICH_SPEC = {
    "title": (
        "이 글의 제목 1개. 32자 이내, 자연스럽고 구체적인 한국어. "
        "주제에 도구명이 있으면 제목에 그 도구명을 넣을 것. "
        "비문 금지(조사·어미 정확히), '먼저 볼 N가지'·'~할 N가지'·'무료 도구' 같은 정형구/막연한 표현 금지, "
        "낚시성·과장 금지. 구체적 이득이나 핵심 질문이 드러나게."
    ),
    "hook_opening": "독자 상황에 공감하며 글의 가치를 제시하는 3~4문장. 짧고 밀도 높게. 인사말 금지.",
    "yomi_judgment": "핵심 관점·결론을 단정적으로 2~3문장. 라벨 금지.",
    "real_criterion": "실전 단계 3개를 '1단계: ...\\n2단계: ...\\n3단계: ...' 형식 한 문자열로. 각 단계 1~2문장, 구체적 기능·메뉴·방법 포함(고급 팁 우선).",
    "misconceptions": "주제 특화 오해 3개를 [{\"착각\":\"...\",\"실제\":\"...\"}] 배열로. 각 1문장.",
    "use_cases": "고급 실전 활용 시나리오 3개를 [{\"상황\":\"...\",\"활용\":\"...\"}] 배열로. 잘 안 알려진 활용 위주, 각 1~2문장.",
    "faq": "주제 특화 실전 질문 3개를 [{\"Q\":\"...\",\"A\":\"...\"}] 배열로. 답변 1~2문장.",
    "prompt_block": (
        "이 주제/도구에 바로 복사해 쓰는 완성형 프롬프트 3개를 "
        "[{\"label\":\"용도(짧게)\",\"prompt\":\"실제 프롬프트 전문\"}] 배열로. "
        "그대로 붙여넣어도 결과가 나오도록 구체적 예시 값까지 채울 것. "
        "대괄호 빈칸은 꼭 필요한 1~2개로 최소화. 화살표는 ->로 표기."
    ),
}


def _strip_internal_labels(text: str) -> str:
    text = re.sub(r'^\s*요미\s*(?:의)?\s*판단\s*[:：]\s*', '', str(text or ''))
    return text.strip()


def enrich_slots_with_llm(
    *,
    slots: dict[str, Any],
    topic: str,
    content_type: str,
    selected_title: str = "",
    llm_service: Any = None,
) -> dict[str, Any]:
    """LLM으로 주제 특화 본문을 생성해 slots의 텍스트형 슬롯을 교체한다.

    실패/형식 불량/비활성 시 원본 slots를 그대로 반환(폴백) — 발행은 항상 진행 가능.
    """
    if os.getenv("ENABLE_AI_LLM_ENRICH", "true").strip().lower() in {"0", "false", "no", "off"}:
        return slots

    try:
        if llm_service is None:
            from blogspot_automation.services.llm_content_service import LlmContentService
            llm_service = LlmContentService()
    except Exception as exc:
        logger.warning("ai_slot_enricher: LLM 서비스 로드 실패(폴백): %s", exc)
        return slots

    focus = _CT_FOCUS.get(content_type, "이 AI 주제의 실용적 핵심")
    spec_lines = "\n".join(f'- "{k}": {v}' for k, v in _ENRICH_SPEC.items())
    title_part = f"제목: {selected_title}\n" if selected_title else ""
    user_prompt = (
        f"주제: {topic}\n{title_part}글 성격: {focus}\n\n"
        f"아래 키를 가진 JSON 하나만 출력하세요. 각 값은 한국어로, 주제에 특화된 구체적 내용으로 채웁니다.\n"
        f"{spec_lines}\n\n"
        "주의: 표·체크리스트·가격은 포함하지 마세요(다른 모듈이 처리). "
        "사실이 불확실하면 일반적 원리로 쓰되 '직접 확인 필요'를 덧붙이세요."
    )

    def _validator(text: str) -> None:
        data = _parse_json(text)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        # 최소한 hook/yomi/faq가 있어야 유효로 인정
        if not (data.get("hook_opening") and data.get("yomi_judgment") and data.get("faq")):
            raise ValueError("missing core keys")

    try:
        result = llm_service.call_with_fallback(
            user_prompt, system_prompt=_SYSTEM_PROMPT, min_chars=300, validator=_validator,
        )
    except Exception as exc:
        logger.warning("ai_slot_enricher: LLM 호출 예외(폴백): %s", exc)
        return slots

    if not result:
        logger.info("ai_slot_enricher: LLM 결과 없음 → 템플릿 폴백")
        return slots

    data = _parse_json(result)
    if not isinstance(data, dict):
        return slots

    enriched = dict(slots)
    _apply_text(enriched, data, "hook_opening")
    _apply_text(enriched, data, "yomi_judgment", clean=True)
    _apply_text(enriched, data, "real_criterion")
    _apply_pairs(enriched, data, "misconceptions", ("착각", "실제"))
    _apply_pairs(enriched, data, "use_cases", ("상황", "활용"))
    _apply_pairs(enriched, data, "faq", ("Q", "A"), min_items=3)

    # prompt_block: 템플릿에 원래 있던 패턴(프롬프트 레시피 등)에서만 주제 특화로 교체
    if "prompt_block" in slots:
        pb = data.get("prompt_block")
        if isinstance(pb, list):
            cards = []
            for item in pb:
                if isinstance(item, dict) and str(item.get("label", "")).strip() and str(item.get("prompt", "")).strip():
                    cards.append({
                        "label": str(item["label"]).strip(),
                        "prompt": str(item["prompt"]).strip().replace("→", "->"),
                    })
            if len(cards) >= 2:
                enriched["prompt_block"] = cards[:5]

    # 제목: LLM이 만든 자연스러운 제목을 특수 키에 담아 파이프라인이 채택하게 한다
    llm_title = data.get("title")
    if isinstance(llm_title, str):
        t = re.sub(r"\s+", " ", llm_title).strip().strip('"').strip()
        if 6 <= len(t) <= 60 and not re.search(r"먼저\s*(볼|확인할|정할|해야)\s*\d+\s*가지", t):
            enriched["_llm_title"] = t

    logger.info("ai_slot_enricher: 주제 특화 본문 적용 완료 (topic=%s)", topic[:40])
    return enriched


def _parse_json(text: str) -> Any:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _apply_text(slots: dict, data: dict, key: str, *, clean: bool = False) -> None:
    val = data.get(key)
    if isinstance(val, str) and len(val.strip()) >= 20:
        slots[key] = _strip_internal_labels(val) if clean else val.strip()


def _apply_pairs(slots: dict, data: dict, key: str, fields: tuple[str, str], *, min_items: int = 3) -> None:
    val = data.get(key)
    if not isinstance(val, list):
        return
    cleaned = []
    a, b = fields
    for item in val:
        if isinstance(item, dict) and str(item.get(a, "")).strip() and str(item.get(b, "")).strip():
            cleaned.append({a: str(item[a]).strip(), b: str(item[b]).strip()})
    if len(cleaned) >= min_items:
        # faq는 기존(공통 심화 FAQ)과 합치지 않고 LLM 주제특화로 교체하되 상한 6개
        slots[key] = cleaned[:6]
