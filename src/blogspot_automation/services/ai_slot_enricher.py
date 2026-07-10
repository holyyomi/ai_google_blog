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
    "주제가 '무료 AI 도구'처럼 포괄적이면 반드시 대표 도구 1~3개(예: ChatGPT, Claude, Gemini)를 "
    "직접 지정해 그 도구들 기준으로 구체적으로 씁니다 — 어떤 도구 이야기인지 모호한 익명 서술 금지. "
    "제목·첫 문단·표에 그 도구명이 실제로 등장해야 합니다. "
    "모든 슬롯의 모든 문장이 이 주제에 특정되어야 합니다 — 어느 글에나 들어갈 수 있는 "
    "범용 'AI 업무 활용' 일반론으로 슬롯을 채우면 실패입니다. "
    "설정·기능 안내는 실제 화면 경로(앱 → 설정 → 메뉴명)와 버튼·토글의 실제 이름으로 쓰고, "
    "가격·무료 한도처럼 바뀌는 수치는 'YYYY년 M월 기준' 형태로 기준일과 함께 씁니다. "
    "초보용 일반론이 아니라, 잘 안 알려진 고급 활용법·실전 팁·숨은 기능 등 "
    "'유료 강의급'의 구체적 정보를 줍니다(구체적 메뉴·기능명·설정·예시 포함). "
    "글 전체에 최소 3개, '아는 사람만 아는' 실전 팁(숨은 메뉴·단축 경로, 무료 한도를 아끼는 "
    "사용 순서, 자주 하는 실수와 복구 방법)을 반드시 포함합니다 — 독자가 저장할 이유를 만드세요. "
    "단, 간결하게 씁니다. 군더더기·반복·당연한 말은 빼고 정보 밀도를 높입니다. "
    "광고·과장·자기소개·인사말 없이 핵심만 씁니다. "
    "본문 어떤 슬롯에도 해시태그(#단어)를 쓰지 않습니다 — 해시태그는 시스템이 별도 영역에 자동 삽입합니다. "
    "'제가 직접 해봤다'류 개인 경험담과 구체 수익·매출 금액 주장(예: 월 N만원 수익)은 절대 쓰지 않습니다. "
    "[팩트 안전 — 자동 발행 최우선 규칙] 확인되지 않은 출시일·가격·요금제·무료범위·모델명·"
    "기능 제공 여부·세부 메뉴 경로·개인정보 활용 범위·데이터 보관 기간·'기본값이 켜져/꺼져 있다'·"
    "국가별 제공 여부는 절대 단정하지 않습니다. 불확실하면 '계정·지역·앱 버전에 따라 다를 수 있다', "
    "'공식 도움말에서 최신 설정 확인 권장'처럼 씁니다. "
    "'무조건', '완전 차단', '100% 안전', '누구나 가능', '삭제하면 즉시 사라진다', "
    "'모든 계정에 동일 적용', 'AI 학습에 모두 편입된다' 같은 단정 표현은 금지합니다. "
    "특정 인물 비방, 허위 단정, 수익 보장 표현은 절대 쓰지 않습니다. "
    "출력 전 스스로 검수합니다: 확인 안 된 수치·경로 단정이 있으면 완화하고, 반복 문장은 제거합니다. "
    "반드시 유효한 JSON만 출력합니다(코드블록·설명 금지)."
)

# LLM이 채울 수 있는 텍스트형 슬롯과 출력 스펙 (간결·고밀도 지향)
_ENRICH_SPEC = {
    "title": (
        "이 글의 제목 1개. 32자 이내, 자연스럽고 구체적인 한국어. "
        "제목에 반드시 구체 도구/서비스명을 넣을 것 — 주제가 포괄적이면 본문에서 다루는 "
        "대표 도구명으로(예: 'ChatGPT 무료 플랜…', 'ChatGPT·Claude 무료 한계…'). "
        "'무료 AI 도구'처럼 어떤 도구인지 알 수 없는 익명 제목 금지. "
        "비문 금지(조사·어미 정확히), '먼저 볼 N가지'·'~할 N가지'·'무료 도구' 같은 정형구/막연한 표현 금지, "
        "낚시성·과장 금지. 구체적 이득이나 핵심 질문이 드러나게."
    ),
    "hook_opening": "독자 상황에 공감하며 글의 가치를 제시하는 3~4문장. 짧고 밀도 높게. 인사말 금지.",
    "yomi_judgment": "핵심 관점·결론을 단정적으로 2~3문장. 라벨 금지.",
    "real_criterion": (
        "실전 단계 3개를 '1단계: ...\\n2단계: ...\\n3단계: ...' 형식 한 문자열로. "
        "각 단계 1~2문장, 구체적 기능·메뉴·방법 포함(고급 팁 우선). "
        "가능하면 소요 시간 변화를 수치로 넣되, 반드시 이 도구/기능의 실제 특성에서 "
        "나온 값으로 매번 다르게 추정할 것 — '30분->10분'처럼 예시로 자주 쓰이는 "
        "숫자를 그대로 베끼지 말 것. 근거 없는 구체 수치보다는 '수작업 대비 체감 시간 단축' "
        "처럼 정성적으로 쓰는 편이 낫다."
    ),
    "misconceptions": "주제 특화 오해 3개를 [{\"착각\":\"...\",\"실제\":\"...\"}] 배열로. 각 1문장.",
    "use_cases": "고급 실전 활용 시나리오 3개를 [{\"상황\":\"...\",\"활용\":\"...\"}] 배열로. 잘 안 알려진 활용 위주, 각 1~2문장.",
    "faq": "주제 특화 실전 질문 3개를 [{\"Q\":\"...\",\"A\":\"...\"}] 배열로. 답변 1~2문장.",
    "prompt_block": (
        "이 주제/도구에 바로 복사해 쓰는 완성형 프롬프트 5개를 "
        "[{\"label\":\"용도(짧게)\",\"prompt\":\"실제 프롬프트 전문\"}] 배열로. "
        "서로 다른 업무(예: 이메일/보고서/회의록/데이터 정리/기획) 하나씩. "
        "그대로 붙여넣어도 결과가 나오도록 역할·조건·출력 형식·예시 값까지 채운 8줄 내외 프롬프트로. "
        "대괄호 빈칸은 꼭 필요한 1~2개로 최소화. 화살표는 ->로 표기."
    ),
    "quick_decision_table": (
        "주제 특화 상황별 판단표 4~5행을 [{\"내 상황\":\"...\",\"할 일\":\"...\"}] 배열로. "
        "'할 일'은 구체적 기능명·설정·프롬프트 방향까지 담을 것. 뻔한 일반론 금지."
    ),
    "actions": (
        "오늘 바로 실행할 행동 3개를 [{\"행동\":\"짧은 제목\",\"설명\":\"1~2문장 구체 방법\"}] 배열로. "
        "측정 가능한 행동(예: 반복 업무 3개 목록화)으로."
    ),
    "pricing_table": (
        "이 주제와 관련된 도구/모델의 무료·유료 경계 비교 2~4행을 "
        "[{\"플랜\":\"도구명 플랜명\",\"가격\":\"...\",\"핵심 기능\":\"...\",\"한계\":\"...\"}] 배열로. "
        "널리 알려진 공개 가격은 구체적으로 쓸 것(예: 'ChatGPT Plus 월 $20', '무료 0원') — "
        "글에 작성 기준일이 명시되므로 그 시점 기준 가격이면 된다. "
        "정말 확신이 없는 항목만 '공식 요금 페이지 확인'으로 쓸 것(전 행을 이 문구로 채우지 말 것). "
        "'한계' 칸에는 무료 한도·제한을 구체적으로."
    ),
    "paa": (
        "사람들이 실제 검색창에 입력할 법한 이 주제의 관련 검색어 5개를 문자열 배열로. "
        "각 8~22자, 명사구 형태(예: 'ChatGPT 회의록 요약 프롬프트'), "
        "질문형 어미(~인가요/~하나요) 금지, 조사 어색함 금지, 글 제목 그대로 반복 금지. "
        "실제 검색량이 있을 법한 구체 키워드 조합으로."
    ),
    "citation_summary": (
        "AI 검색엔진(구글 AI Overviews, Perplexity 등)이 그대로 발췌·인용하기 좋은 "
        "이 주제의 핵심 요약 3~4문장 한 문자열. 첫 문장은 주제의 핵심 답을 직접 진술, "
        "가능하면 구체적 수치·조건 포함, 광고 문구·독자 호명 금지, 완결된 평서문."
    ),
    "target_reader": (
        "이 글이 실제로 도움이 되는 사람을 2~3문장으로. 구체적 상황·직무로 특정할 것 "
        "(예: '주간 보고서를 매주 직접 쓰는 팀 실무자'). 막연한 '30~50대 직장인' 같은 "
        "표현 금지, 글 제목 반복 금지."
    ),
    "confirmed_facts": (
        "이 주제에서 확실하게 성립하는 사실 3개를 문자열 배열로. 각 한 문장, "
        "주제 특화 내용(범용 AI 주의사항 금지)."
    ),
    "check_needed": (
        "독자가 직접 확인해야 하는 가변 항목 3개를 문자열 배열로. 각 한 문장, "
        "이 주제에서 실제로 자주 바뀌는 것들(요금, 한도, 정책 등 구체적으로)."
    ),
    "checklist": (
        "이 주제를 회사 업무에 적용하기 전 확인할 체크리스트 5~6개를 문자열 배열로. "
        "회사 기밀·개인정보 입력 금지, 결과물 팩트 검증, 사내 AI 정책 확인 등 "
        "실무 보안·품질 항목 위주. 각 항목 한 문장."
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

    # 실시간 검색 팩트 주입 — 모델 지식만으로 쓰면 수치·요금이 환각된다.
    # Custom Search/Gemini 그라운딩 결과를 근거로 제공하고, 근거에 없는 수치는
    # 단정하지 않도록 지시한다. 수집 실패 시엔 기존 방식(보수적 서술)으로 폴백.
    facts_part = ""
    if os.getenv("ENABLE_AI_FACT_INJECTION", "true").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            facts = str(llm_service.gather_facts(topic) or "").strip()
            if facts:
                facts_part = (
                    "\n[웹 검색으로 수집한 최신 근거 — 오늘 날짜 기준]\n"
                    f"{facts[:2500]}\n"
                    "위 근거에 있는 수치·날짜·요금은 그대로 인용하고, "
                    "근거에 없는 수치는 단정하지 말 것.\n"
                )
                logger.info("ai_slot_enricher: 검색 팩트 주입 (%d자)", len(facts))
        except Exception as exc:  # noqa: BLE001 — 팩트 수집 실패는 비치명
            logger.warning("ai_slot_enricher: 팩트 수집 실패(근거 없이 진행): %s", exc)

    user_prompt = (
        f"주제: {topic}\n{title_part}글 성격: {focus}\n"
        f"{facts_part}\n"
        f"아래 키를 가진 JSON 하나만 출력하세요. 각 값은 한국어로, 주제에 특화된 구체적 내용으로 채웁니다.\n"
        f"{spec_lines}\n\n"
        "주의: 표·가격·체크리스트는 반드시 지정된 JSON 키(quick_decision_table/pricing_table/checklist)에만 담고, "
        "텍스트 슬롯 안에는 넣지 마세요. "
        "사실이 불확실하면 일반적 원리로 쓰되 '직접 확인 필요'를 덧붙이세요. "
        "독자가 이 글을 저장하고 다시 찾아올 이유(복사해 쓰는 자산, 비교 기준, 비용 전략)를 "
        "각 슬롯에 최소 하나씩 담으세요."
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
    # 저장 가치 자산 슬롯 — 렌더러(golden_article_preview_service)가 지원하는
    # 표/체크리스트 슬롯을 주제 특화 내용으로 채운다 (형식 불량 시 항목별 폴백).
    _apply_pairs(enriched, data, "quick_decision_table", ("내 상황", "할 일"))
    _apply_pairs(enriched, data, "actions", ("행동", "설명"))
    _apply_pricing_table(enriched, data)
    _apply_checklist(enriched, data)

    # prompt_block: 주제 특화 완성형 프롬프트로 교체 (업무별 최대 5개).
    # 템플릿에 슬롯이 없던 패턴에도 추가한다 — 복사해 쓰는 자산은 저장 가치의 핵심.
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

    # GEO 블록 3종 — 규칙 기반(geo_intent_service) 일반론 대신 주제 특화 생성을
    # 특수 키로 전달, 렌더러가 우선 사용한다.
    cit = data.get("citation_summary")
    if isinstance(cit, str) and len(cit.strip()) >= 60:
        enriched["_llm_citation_summary"] = re.sub(r"\s+", " ", cit).strip()
    tr = data.get("target_reader")
    if isinstance(tr, str) and len(tr.strip()) >= 30:
        enriched["_llm_target_reader"] = re.sub(r"\s+", " ", tr).strip()
    for src_key, dst_key in (("confirmed_facts", "_llm_confirmed"), ("check_needed", "_llm_check_needed")):
        val = data.get(src_key)
        if isinstance(val, list):
            items = [re.sub(r"\s+", " ", str(v)).strip() for v in val if str(v).strip() and len(str(v).strip()) >= 8]
            if len(items) >= 2:
                enriched[dst_key] = items[:4]

    # 관련 검색어: 규칙 기반 PAA(어색한 조합 잦음) 대신 LLM이 만든 실제
    # 검색어 스타일 키워드를 특수 키로 전달 — 렌더러가 우선 사용한다.
    paa = data.get("paa")
    if isinstance(paa, list):
        keywords = []
        for item in paa:
            text = re.sub(r"\s+", " ", str(item or "")).strip().strip('"')
            if 6 <= len(text) <= 30 and not re.search(r"(인가요|하나요|할까요|입니까)\s*\??$", text):
                keywords.append(text)
        if len(keywords) >= 3:
            enriched["_llm_paa"] = keywords[:5]

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


def _apply_pricing_table(slots: dict, data: dict) -> None:
    """무료/유료 경계 비교표 — {플랜, 가격, 핵심 기능, 한계} 4필드 행만 채택."""
    val = data.get("pricing_table")
    if not isinstance(val, list):
        return
    rows = []
    for item in val:
        if not isinstance(item, dict):
            continue
        plan = str(item.get("플랜", "")).strip()
        price = str(item.get("가격", "")).strip()
        feature = str(item.get("핵심 기능", item.get("핵심기능", ""))).strip()
        limit = str(item.get("한계", "")).strip()
        if plan and price and (feature or limit):
            rows.append({"플랜": plan, "가격": price, "핵심 기능": feature, "한계": limit})
    if len(rows) >= 2:
        slots["pricing_table"] = rows[:4]


def _apply_checklist(slots: dict, data: dict) -> None:
    """도입 전 보안·품질 체크리스트 — 문자열 배열 4개 이상일 때만 채택."""
    val = data.get("checklist")
    if not isinstance(val, list):
        return
    items = [str(c).strip() for c in val if str(c).strip() and len(str(c).strip()) >= 8]
    if len(items) >= 4:
        slots["checklist"] = items[:6]


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
