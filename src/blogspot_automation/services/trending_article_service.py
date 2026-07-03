"""TrendingArticleService — 트렌딩 후보 → LLM 직접 생성 article_html.

기존 GoldenPatternService + SlotFillerService + GoldenArticlePreviewService는
template-based로 정해진 슬롯을 채워 HTML을 만든다. 슬롯 내용이 generic해서
사용자 피드백("공부될 내용 없음, 결론·분량 별로")의 핵심 원인이 됨.

이 서비스는 trending 후보(네이버 인기 기사)를 LLM(LlmContentService 무료 우선
fallback chain)에 직접 위임해 fresh news pipeline

워크플로우:
  1. NewsPipeline이 trending 후보를 선택 (raw.trending_engine=True)
  2. 이 서비스가 candidate.topic + sample_titles + primary_tokens를 컨텍스트로
     LLM 호출 → JSON 응답 (title, meta_description, content HTML, labels, hashtags)
  3. NewsPipeline이 결과를 NewsPublishService.publish로 전달
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.llm_content_service import LlmContentService
from blogspot_automation.services.seo_policy import normalize_hashtags, normalize_labels

logger = logging.getLogger(__name__)


CLEAN_TRENDING_NEWS_SYSTEM_PROMPT = """당신은 "요미(Yomi)" 블로그의 날카로운 해설자입니다.
오늘 한국 뉴스 이슈를, 남들과 다르게 읽어내는 한 편의 해설 글로 만듭니다.

[정체성 — 날카로운 해설자]
당신은 통신사 기사를 받아 적는 사람이 아닙니다. 같은 사건을 다르게 보는 사람입니다.
- 단순 요약·재탕 절대 금지. 다른 매체 10곳이 똑같이 쓰는 문장을 반복하지 마세요.
- 글마다 "대부분의 보도가 놓치는 지점" 또는 "이 사건이 진짜 드러내는 것"을 최소 1개 분명히 제시하세요.
- 2차적 사고: 표면 사실 너머의 구조·맥락·파급을 짚으세요 — 누가 이득이고 손해인지, 비슷한 과거 사례,
  이다음에 벌어질 일. 단순 '무슨 일이 있었나'에서 멈추지 마세요.
- 다관점: 이해관계가 다른 2~3개 시선을 그냥 나열하지 마세요. 그 시선들이 '어디서 충돌하는지'를
  하나의 긴장으로 종합하세요. "한쪽은 X, 다른쪽은 Y" 식 나열 금지 → "X와 Y가 부딪치는 진짜 이유는
  Z"처럼 한 발 더 들어가 정리하세요. 통념과 다른 해석이 더 타당하면 과감히 내세요.
- 과한 헤지 금지: "아직 단정할 수 없다", "지켜봐야 한다" 류로 도망가지 마세요. 불확실한 건 한 번만
  명시하고, 그 안에서도 "가장 그럴듯한 시나리오"를 당신의 판단으로 제시하세요.
- 본문에는 표·비교 블록·단계 리스트 같은 모듈을 최소 1개는 반드시 넣어 시각적으로 쪼개세요.
- 단, 사실과 의견은 칼같이 분리하세요. 확인된 사실은 단정하고, 당신의 해석임을 드러낼 때만
  표지를 붙이되 글 전체에서 1~2회로 아끼고 매번 다른 표현으로("제 해석으로는 / 굳이 따지자면 /
  여기서 한 발 더 들어가면 / 냉정히 보면" 등). 같은 표지를 반복하면 오히려 AI 티가 납니다.

[중복 금지 — 시스템이 보조 블록을 자동으로 붙입니다]
글 끝에 'Q&A, 확인된 것/아직인 것, 참고 출처' 보조 블록이 자동 추가됩니다. 그러니 본문에서는
이것들과 겹치는 섹션(확인된 사실 목록, 관련 검색어, 출처·근거 목록)을 따로 만들지 마세요.
본문 FAQ는 예외입니다 — 아래 [공통 모듈]의 yomi-faq로 정확히 2개만 넣으세요(그 이상 금지).
대신 본문은 당신이 가장 잘하는 것 — 맥락·분석·다관점·해석 — 에 집중하세요.
(배경·맥락 설명은 본문에서 풍부하게 다뤄도 좋습니다. 단 "왜 지금 주목받나" 같은 뻔한 제목은 피하고
당신만의 각도로.)

[사람처럼 쓰기 — AI 티 제거]
- "정리했습니다", "도움이 되셨길", "알아보겠습니다", "살펴보겠습니다", "~에 대해 자세히" 같은
  블로그·AI 상투어 전면 금지.
- "~으로 알려졌습니다", "~라고 전해집니다" 류 헤지 표현은 한 글에 2회까지만. 확인된 건 그냥 단정하세요.
- 기계적 섹션 제목("핵심 정리", "빠른 답변", "관련 검색어", "검색용 요약") 금지.
  헤딩은 사람이 말하듯 그 글에만 맞는 구체적 문장으로.
- 리듬을 주세요. 가끔 짧은 단언 한 줄. 모든 문단이 똑같이 밋밋한 길이면 AI 티가 납니다.

출력은 반드시 JSON 한 개만. 다른 텍스트 없이.
JSON 스키마:
{
  "title": "25~45자 한국어 제목 (아래 후보 중 당신이 가장 자신 있는 1개)",
  "title_candidates": ["서로 다른 각도의 제목 후보 3개 (각 25~45자)"],
  "slug": "영문 소문자 URL 슬러그 3~6단어 하이픈 연결 (예: jangma-definition-change-kma)",
  "image_concept": "커버 일러스트용 영어 장면 묘사 1문장 — 이 이슈를 상징하는 사물·풍경·은유. ⚠️간판/라벨/문서/글자가 등장할 소재 금지(missing·sign·document 같은 단어가 그림 속 글자로 깨져 그려짐), 인물 얼굴 금지. 예: rain clouds parting over a Korean weather observatory with dry cracked ground below",
  "meta_description": "80~155자 검색 의도 매칭 설명",
  "content": "HTML 본문 (<article class=\"yomi-clean-post\"> 포함, 텍스트 2200~3300자, 이미지 태그 금지)",
  "labels": ["주제 라벨 2~5개"],
  "hashtags": ["#해시태그 3~4개 (핵심 키워드·인물/기관·주제군·롱테일 1개)"],
  "faq_items": [{"question": "Q", "answer": "A"}, ...],
  "confirmed_facts": ["확인된 사실 3개"],
  "check_needed": ["아직 확인 안 된 것 2개"]
}

[faq_items — 검색엔진·AI 구조화 데이터 전용 (본문에 렌더되지 않음)]
- 정확히 5개. 이 이슈를 접한 사람이 실제로 검색창에 칠 법한 구체 질문으로.
- 답변은 2~3문장, 본문에서 확인된 사실 기반으로 자급자족하게(글을 안 읽어도 이해되게).
- 본문 yomi-faq 2개와 다른 질문으로 구성하세요. 일반론 질문("주의할 점은?") 금지 —
  반드시 이 이슈의 고유명사·조건·일정이 들어간 질문으로.

[confirmed_facts / check_needed — 글 끝 '확인된 것/아직인 것' 블록에 그대로 노출됨]
- confirmed_facts: 관련 기사 제목·키워드에서 직접 확인되는 사실만 3개, 각 1문장.
  고유명사·수치를 포함해 구체적으로. 당신의 해석·추측은 절대 넣지 마세요.
- check_needed: 아직 공식 확인이 안 된 쟁점 2개, 각 1문장. "~인지는 발표를 봐야 한다" 식.

[발행 표준 — 63-cj 글의 읽기 감각을 기준으로 삼되 복제하지 않기]
- 과한 랜딩페이지형 디자인, 그라데이션 박스, 이모지 남발, details 접힘 UI, 인라인 style을 쓰지 마세요.
- 본문은 반드시 <article class="yomi-clean-post"> 하나로 감싸세요.
- 첫 화면에서 답이 보여야 합니다. 첫 섹션은 <section class="yomi-lede">로 만들고 핵심 판단을 2문단 안에 넣으세요.
- 글은 "사건 설명"보다 독자가 오늘 확인할 기준, 단계, 손실 회피 포인트를 먼저 보여야 합니다.
- 한 단락은 2~3문장 이하. 긴 설명은 표, 단계 리스트, 2~3칸 비교 블록으로 쪼개세요.
- 단, 매번 같은 섹션명·같은 순서·같은 표 구성을 반복하지 마세요. 글마다 이슈 성격에 맞는 모듈을 5~7개만 골라 조합하세요.

[공통 모듈 — 필요한 것만 선택]
- <span class="yomi-kicker">YYYY.MM.DD 기준 오늘 이슈</span>
- <section class="yomi-lede">: 첫 화면 핵심 답변. 모든 글에 1회만 사용.
- <div class="yomi-thesis">: 두 가지 관점 비교. "배송 전/후", "확정/미확정", "독자/플랫폼"처럼 이슈별로 바꾸세요.
  ⚠️ 비교 카드(thesis/lens)는 각 칸 분량을 비슷하게(각 2문장 안팎). 한쪽만 길고 다른 쪽이
  한 줄이면 빈 칸처럼 보여 깨진 레이아웃이 됩니다. 채울 말이 없는 관점은 칸을 만들지 마세요.
- <table class="yomi-risk">: 상태·위험도·확인 항목 표. 일정, 신청, 환불, 배송, 요금 이슈에만 강하게 사용하세요.
- <ul class="yomi-list">: 단계형 확인 순서 또는 체크포인트. li에는 data-step="1"부터 넣으세요.
- <div class="yomi-lens">: 소비자·사업자·기관, 팬·플랫폼·제작사처럼 3개 관점이 필요할 때 사용하세요.
  각 관점 카드는 분량 균등(각 2문장 안팎) — 비어 보이는 카드 금지.
- <p class="yomi-note">: 독자가 자주 오해할 한 가지를 짧게 강조할 때 사용하세요.
- <section class="yomi-faq">: FAQ 2개. 각 항목은 <article><h3>질문</h3><p>답변</p></article>. (질문형 헤딩 과다 방지 — 최대 2개)
- <section class="yomi-source">: 출처명은 텍스트로만 정리. 외부 링크 href 금지.

[후킹 주제·제목 원칙]
- title_candidates에 서로 다른 각도 3개: ①정보 격차형(아는 사람만 아는 지점) ②긴장·대비형(통념 vs 실제) ③구체 기준형(숫자·일정·조건).
- 제목은 원문 기사 제목 요약이 아니라 독자의 손해, 일정, 조건, 확인 기준이 보여야 합니다.
- 좋은 제목 예 (이슈 성격별):
  · 일정·생활형: "6월3일 택배휴무, CJ 한진 롯데보다 집화 마감이 먼저입니다"
  · 반응해석형: "ㅇㅇ 논란, 팬들이 정말 화난 지점은 사과문이 아니다"
  · 타임라인형: "비 안 와도 장마철? 기상학계가 장마 정의를 다시 쓰는 이유"
  · 인물·스포츠형: "손흥민 이적설에 토트넘이 침묵하는 동안 움직인 세 가지"
- 진부한 제목 금지: 총정리, 완벽 가이드, 모든 것, 주목, 충격, 난리, 역대급.
- 검색자가 실제로 칠 단어(대상, 조건, 방법, 일정, 환불, 배송조회, 신청, 마감)를 자연스럽게 포함하세요.

[저장·공유 장치 — 매 글 필수]
- 북마크 가치 1개: 독자가 나중에 다시 찾아올 표·체크리스트·기준 목록을 본문 모듈로.
  "이건 저장해두자" 싶게 구체적으로 (일정표, 확인 기준, 단계별 판단 기준 등).
- 인용 한 줄 1개: 이 글의 관점을 압축한 짧고 단정적인 문장을 <p class="yomi-note">로.
  누군가 댓글이나 단톡방에 그대로 복사해 붙일 만한 문장 — 일반론 말고 이 이슈에만 맞는 말로.

[기승전결 — 글은 반드시 '결'로 닫혀야 합니다]
- 기(起): yomi-lede에서 사건 핵심과 당신의 판단을 먼저 제시.
- 승(承): 전개·맥락 — 무슨 일이 어떻게 흘러왔는지.
- 전(轉): 관점이 충돌하는 지점, 통념과 다른 당신의 해석 — 글의 하이라이트.
- 결(結): ⚠️ 마지막 h2 섹션은 반드시 마무리 섹션이어야 합니다 (FAQ로 글을 끝내지 마세요.
  FAQ는 결 앞에 배치). 결 섹션에는 ①당신의 최종 판단 한 단락 ②독자가 다음에 지켜볼
  관전 포인트 1~2개 ③여운이 남는 마지막 한 문장(짧은 단언)을 담으세요.
  헤딩은 "결론"·"마치며" 같은 기계적 제목 금지 — 그 글의 판단을 압축한 구체 문장으로.
  (예: "장마라는 단어가 바뀌면, 여름 준비 순서도 바뀝니다")

[이슈 프로필별 프레임]
- 문제해결형: lede + yomi-risk + yomi-list + FAQ 중심. "오늘 바로 확인할 순서"가 자연스럽습니다.
- 일정·배송형: lede + 단계 표 + 마감/재개 구간 + 반품/예외 + FAQ. 63-cj처럼 단계 판단을 강조하세요.
- 신청·청약·지원형: lede + 대상 조건 + 기간/금액 표 + 빠지는 혜택/주의점 + 신청 전 체크. 배송형 문구를 쓰지 마세요.
- 반응해석형: lede + 무슨 일이 있었나 + 반응이 갈린 이유 + 이해관계자 3관점 + 다음 관전 포인트 + FAQ. 억지 해결법 금지.
- 트렌드해석형: lede + 어디서 퍼졌나 + 사람들이 붙는 이유 + 확산 구조 + 식는 신호 + FAQ. 구매 유도 금지.
- 타임라인형: lede + 확인된 것/아직 모르는 것 + 왜 지금인가 + 시간 흐름 + 다음 쟁점 + FAQ. 단정과 추측을 분리하세요.
- 기업·플랫폼 변화형: lede + 적용 대상 + 계정/결제/서비스 영향 + 사용자가 먼저 볼 항목 + 공식 확인 기준 + FAQ.

[반복 방지]
- 같은 주제군 안에서도 h2 문구를 매번 바꾸세요. 예: "내 주문 위험도는 단계가 결정합니다"를 다른 글에 그대로 반복하지 마세요.
- 표 제목과 열 이름도 이슈에 맞게 바꾸세요. 예: 배송은 "현재 상태/위험도/지금 볼 것", 청약은 "확인 항목/의미/주의점".
- "오늘 바로 확인할 순서"는 문제해결형에만 쓰고, 반응해석형은 "다음 관전 포인트", 타임라인형은 "아직 확인할 부분"처럼 바꾸세요.

[팩트 가드레일]
- 구체 날짜·시각·금액·인원은 user_prompt의 관련 기사 제목이나 키워드에 명시된 것만 사용하세요.
- 명시되지 않은 사건 발생 시각은 "최근", "관련 보도에 따르면"으로 처리하세요.
- 외부 사이트로 나가는 링크는 본문에 넣지 마세요. 출처명만 텍스트로 적으세요.
- 마크다운 금지. HTML 태그만 사용하세요.
- HTML entity 코드(&#숫자;) 금지. 한국어 유니코드를 직접 쓰세요.
- "안녕하세요", "이번 포스팅에서는", "도움이 되셨길" 같은 블로그 상투어 금지.


[AI issue article mandatory rules]
- If the topic is an AI tool, AI model, automation, prompt, or productivity workflow, include all five: what changed, practical workflow, price/free-vs-paid limits, low-cost high-efficiency usage, and security/privacy/review risks.
- The tool/model/product named in the title or topic must appear with concrete explanation at least twice in the body. A specific title followed by generic ChatGPT advice is a failure.
- Include at most one copy-paste prompt, and only when it is genuinely useful. Prefer save-worthy checklists, cost decision tables, and workflow steps over generic prompt blocks.
- Structure the article as: problem -> why it matters now -> how to apply it -> cost/efficiency decision -> risks/limits -> what the reader should do today.
- Assume generated images contain no readable Korean text. Do not request, describe, or depend on text inside images.
- The final section must not be FAQ. End with a concrete judgment, one save-worthy rule, and one or two actions the reader can do today.
"""


@dataclass(slots=True)
class TrendingArticleResult:
    title: str
    meta_description: str
    article_html: str
    labels: list[str]
    hashtags: list[str]
    faq_items: list[dict[str, str]]
    provider_used: str = ""
    issue_content_profile: dict[str, Any] | None = None
    confirmed_facts: list[str] = field(default_factory=list)
    check_needed: list[str] = field(default_factory=list)
    slug: str = ""
    image_concept: str = ""


class TrendingArticleService:
    """Trending 후보 → LLM 무료 우선 fallback chain으로 article_html 직접 생성."""

    def __init__(self, llm: LlmContentService | None = None) -> None:
        self.llm = llm or LlmContentService()

    def generate_article(self, candidate: NewsCandidate) -> TrendingArticleResult:
        topic = candidate.topic
        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        sample_titles = raw.get("sample_titles", []) or []
        primary_tokens = raw.get("primary_tokens", []) or []
        sample_sources = raw.get("sample_sources", []) or []
        source_count = int(raw.get("source_count", 0) or 0)
        content_angle = raw.get("content_angle") if isinstance(raw.get("content_angle"), dict) else {}
        issue_profile = raw.get("issue_content_profile") if isinstance(raw.get("issue_content_profile"), dict) else {}
        if not issue_profile:
            issue_profile = IssueContentProfileService().build_profile(
                topic=topic,
                summary=candidate.summary or "",
                content_type=str(content_angle.get("content_type") or ""),
                topic_group=str(raw.get("topic_group") or content_angle.get("topic_group") or ""),
                raw=raw,
            )

        user_prompt = self._build_user_prompt(
            topic=topic,
            sample_titles=sample_titles,
            primary_tokens=primary_tokens,
            sample_sources=sample_sources,
            source_count=source_count,
            issue_profile=issue_profile,
        )

        logger.info(
            "TrendingArticleService: LLM fallback chain 호출 (trending=%s sources=%d)",
            topic[:50], source_count,
        )
        content_str = self.llm.call_with_fallback(
            user_prompt=user_prompt,
            system_prompt=CLEAN_TRENDING_NEWS_SYSTEM_PROMPT,
            min_chars=1500,
            validator=self._validate_json_response,
        )

        if not content_str:
            raise RuntimeError(
                "TrendingArticleService: LLM fallback chain 전체 실패 — "
                "모든 provider가 호출 실패 또는 invalid JSON. "
                "OPENROUTER_API_KEY 또는 OPENAI_API_KEY 중 1개 이상 유효해야 함."
            )

        parsed = self._normalize_and_parse(content_str)
        _title_pool = [str(parsed.get("title") or topic).strip("\"'")]
        _title_pool += [
            str(t).strip().strip("\"'")
            for t in (parsed.get("title_candidates") or [])
            if isinstance(t, str) and t.strip()
        ]
        title = self._select_best_title(_title_pool, primary_tokens=primary_tokens)
        meta_description = str(parsed.get("meta_description") or "").strip()
        article_html = str(parsed.get("content") or "").strip()
        if not article_html:
            raise RuntimeError("TrendingArticleService: LLM 응답에 content 필드 없음")
        # visible 질문형 헤딩 예산 방어: answer_engine이 intent Q&A 3개를 추가하므로
        # LLM yomi-faq는 2개로 제한해야 최종 질문 헤딩 ≤5 (감사 visible_question_headings_above_5).
        article_html = self._cap_yomi_faq_items(article_html, max_items=2)

        raw_labels = parsed.get("labels") or []
        labels = normalize_labels([t.strip() for t in raw_labels if isinstance(t, str) and t.strip()])
        raw_tags = parsed.get("hashtags") or []
        hashtags = normalize_hashtags([
            h for h in raw_tags
            if isinstance(h, str) and h.startswith("#") and len(h) > 1
            and "..." not in h and "~" not in h
        ])
        faq_items_raw = parsed.get("faq_items") or []
        faq_items = [
            {"question": str(i.get("question", "")).strip(), "answer": str(i.get("answer", "")).strip()}
            for i in faq_items_raw if isinstance(i, dict)
        ][:7]
        confirmed_facts = [
            str(x).strip() for x in (parsed.get("confirmed_facts") or [])
            if isinstance(x, str) and x.strip()
        ][:3]
        check_needed = [
            str(x).strip() for x in (parsed.get("check_needed") or [])
            if isinstance(x, str) and x.strip()
        ][:2]
        slug = re.sub(r"[^a-z0-9-]+", "-", str(parsed.get("slug") or "").lower()).strip("-")[:60]
        image_concept = " ".join(str(parsed.get("image_concept") or "").split())[:220]

        return TrendingArticleResult(
            title=title,
            meta_description=meta_description,
            article_html=article_html,
            labels=labels,
            hashtags=hashtags,
            faq_items=faq_items,
            issue_content_profile=issue_profile,
            confirmed_facts=confirmed_facts,
            check_needed=check_needed,
            slug=slug,
            image_concept=image_concept,
        )

    # ── 내부 ─────────────────────────────────────────────────────────────

    _TITLE_CLICHES = ("총정리", "완벽 가이드", "모든 것", "충격", "경악", "역대급", "난리", "소름")

    @classmethod
    def _select_best_title(cls, candidates: list[str], *, primary_tokens: list[str]) -> str:
        """제목 후보 중 후킹·무결성 점수가 가장 높은 1개 선택.

        integrity 차단 이슈가 있는 후보는 제외. 전부 차단이면 첫 후보 반환
        (이후 발행 계약 검증이 동일 기준으로 최종 차단하므로 안전).
        """
        from blogspot_automation.services.title_integrity_policy import audit_title_integrity

        best, best_score = "", -999
        seen: set[str] = set()
        for cand in candidates:
            text = " ".join((cand or "").split()).strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            audit = audit_title_integrity(
                text, content_type="today_issue_explainer", topic_group="today_issue",
            )
            if audit.get("blocking_issues"):
                continue
            score = 0
            n = len(text)
            if 25 <= n <= 45:
                score += 3
            elif 20 <= n <= 50:
                score += 1
            if re.search(r"\d", text):
                score += 2  # 숫자 = 구체성 신호
            if any(tok and str(tok) in text for tok in (primary_tokens or [])[:5]):
                score += 2  # 핵심 entity 포함 = 검색 매칭
            if "?" in text or "," in text:
                score += 1  # 호기심 갭 / 두 박자 구조
            if any(cliche in text for cliche in cls._TITLE_CLICHES):
                score -= 5
            if score > best_score:
                best, best_score = text, score
        if best:
            return best
        return " ".join((candidates[0] if candidates else "").split()).strip()

    @staticmethod
    def _cap_yomi_faq_items(html: str, *, max_items: int = 2) -> str:
        """yomi-faq 섹션의 <article> Q/A 항목을 max_items개로 제한한다.

        LLM이 FAQ를 4~5개 생성하면 answer_engine의 intent Q&A(3개)와 합쳐
        visible 질문형 헤딩이 5개를 초과해 발행이 차단된다. 초과 항목을 잘라
        최종 질문 헤딩 예산을 보장한다.
        """
        if not html:
            return html

        def _trim(match: "re.Match[str]") -> str:
            block = match.group(0)
            articles = list(re.finditer(r"<article\b.*?</article>", block, flags=re.IGNORECASE | re.DOTALL))
            if len(articles) <= max_items:
                return block
            trimmed = block
            for art in reversed(articles[max_items:]):
                trimmed = trimmed[: art.start()] + trimmed[art.end():]
            return trimmed

        return re.sub(
            r'<section\b[^>]*class=(["\'])[^"\']*\byomi-faq\b[^"\']*\1[^>]*>.*?</section>',
            _trim,
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

    @staticmethod
    def _build_user_prompt(
        *,
        topic: str,
        sample_titles: list[str],
        primary_tokens: list[str],
        sample_sources: list[str],
        source_count: int,
        issue_profile: dict[str, Any] | None = None,
    ) -> str:
        from datetime import datetime, timezone, timedelta
        _kst_now = datetime.now(timezone.utc) + timedelta(hours=9)
        _today_kr = _kst_now.strftime("%Y년 %m월 %d일")

        related_titles_block = "\n".join(f"  - {t}" for t in sample_titles[:5]) or "  (관련 기사 없음)"
        tokens_block = ", ".join(primary_tokens[:8]) or "(키워드 없음)"
        sources_block = ", ".join(sample_sources[:5]) or "(언론사 정보 없음)"

        issue_profile_prompt = IssueContentProfileService.prompt_block(issue_profile)

        return (
            f"[작성 기준일]\n"
            f"오늘 날짜: {_today_kr} (한국 시간)\n"
            f"이 이슈는 오늘 한국 네이버 뉴스에서 가장 많이 클릭된 트렌딩 이슈입니다.\n"
            f"⚠️ 사건 발생 시점·시각·구체 날짜는 아래 [관련 기사 제목]에 명시된 것만 사용하세요.\n"
            f"⚠️ 시점이 명시되지 않으면 '최근', '관련 보도에 따르면' 같은 상대 표현만 사용. "
            f"'YYYY년 MM월 DD일', 'OO시경' 같은 구체 시점 절대 창작 금지.\n"
            f"\n[오늘 한국 트렌딩 이슈]\n"
            f"주제: {topic}\n"
            f"네이버 인기 클러스터 크기: {source_count}개 매체 동시 보도\n"
            f"핵심 키워드: {tokens_block}\n"
            f"보도 언론사: {sources_block}\n"
            f"\n[관련 기사 제목 — 사실 근거의 유일한 source]\n{related_titles_block}\n"
            f"\n[작성 지시]\n"
            f"위 트렌딩 이슈를 한국 독자에게 정리한 블로그 글을 작성하세요.\n"
            f"- 시스템 프롬프트의 학습성·결론·제목·팩트 가드레일 규칙을 모두 준수\n"
            f"- 관련 기사 제목과 키워드만을 사실 근거로 사용 (학습 데이터의 다른 사건 혼동 절대 금지)\n"
            f"- 시점·인원수·금액 등 구체 수치는 위 제목에 없으면 언급하지 마세요\n"
            f"- 시점을 표현해야 할 때는 '최근', '오늘 보도된', '관련 보도에 따르면' 사용\n"
            f"- faq_items 5개(검색엔진 구조화 데이터용, 이슈 고유명사 포함 질문)를 JSON에 반드시 포함하고, hashtags는 3~4개 포함\n"
            f"{issue_profile_prompt}\n"
        )

    @staticmethod
    def _normalize_and_parse(text: str) -> dict[str, Any]:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        cleaned = re.sub(r"^json\s*\n", "", cleaned, flags=re.IGNORECASE)
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            cleaned = m.group(0)
        return json.loads(cleaned)

    # 본문에 등장하면 가짜 날짜 환각으로 간주하고 다음 provider로 fallback할 패턴.
    # 작성 기준일과 다른 연도가 본문에 박혀있다는 건 LLM이 학습 데이터 사건을 가져와 섞은 신호.
    _FAKE_DATE_PATTERNS = (
        r"20[0-2]\d\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일",  # "2024년 5월 27일"
        r"오[전후]\s*\d{1,2}\s*시\s*(?:\d{1,2}\s*분)?",       # "오후 1시경"
        r"\d{1,2}\s*시\s*\d{1,2}\s*분\s*경",                  # "13시 27분경"
        r"지난\s*20[0-2]\d\s*년",                              # "지난 2024년"
    )

    @classmethod
    def _validate_json_response(cls, text: str) -> None:
        parsed = cls._normalize_and_parse(text)
        if not isinstance(parsed, dict):
            raise ValueError("response not dict")
        content = str(parsed.get("content") or "").strip()
        if not content:
            raise ValueError("response missing 'content' field")
        if not str(parsed.get("title") or "").strip():
            raise ValueError("response missing 'title' field")
        if not re.search(r"<article\b[^>]*class=(['\"])[^'\"]*\byomi-clean-post\b", content, flags=re.IGNORECASE):
            raise ValueError("content must use the yomi-clean-post article layout")
        if not re.search(r'class=(["\'])[^"\']*\byomi-lede\b', content, flags=re.IGNORECASE):
            raise ValueError("content must start with a yomi-lede answer section")
        if not re.search(r'class=(["\'])[^"\']*\byomi-kicker\b', content, flags=re.IGNORECASE):
            raise ValueError("content must include a yomi-kicker 기준일 label")
        adaptive_modules = sum(
            1
            for marker in (
                "yomi-thesis",
                "yomi-risk",
                "yomi-list",
                "yomi-lens",
                "yomi-note",
            )
            if re.search(rf'class=(["\'])[^"\']*\b{re.escape(marker)}\b', content, flags=re.IGNORECASE)
        )
        if adaptive_modules < 2:
            raise ValueError("content must combine at least two clean-post modules for news-specific variation")
        if "style=" in content.lower():
            raise ValueError("inline styles are not allowed in clean Blogspot layout")
        if re.search(r"<details\b", content, flags=re.IGNORECASE):
            raise ValueError("details/collapsible UI is not allowed in clean Blogspot layout")
        for legacy_marker in ("hero-summary-box", "core-message-box", "ai-overview-box", "paa-block"):
            if legacy_marker in content:
                raise ValueError(f"legacy visual layout marker detected: {legacy_marker}")

        # 기승전결 '결' 강제 — 마지막 h2가 FAQ면 글이 '기승전'에서 끊긴다.
        # (프롬프트 지시만으론 LLM이 무시하는 사례 확인 → 검증으로 강제, 위반 시 재생성)
        h2_texts = re.findall(r"<h2[^>]*>(.*?)</h2>", content, flags=re.IGNORECASE | re.DOTALL)
        if h2_texts:
            last_h2 = re.sub(r"<[^>]+>", "", h2_texts[-1]).strip()
            if re.search(r"자주\s*묻는|FAQ", last_h2, flags=re.IGNORECASE):
                raise ValueError(
                    "article ends with FAQ — must close with a final (결) section: "
                    "최종 판단 + 관전 포인트 + 마지막 한 문장"
                )

        # 가짜 날짜 환각 검사 — 본문 + 구조화 필드(faq/confirmed/check) 전부.
        # faq_items는 FAQPage JSON-LD로, confirmed/check는 visible 블록으로 노출되므로
        # 본문과 동일한 가드레일을 적용해야 한다.
        aux_texts: list[str] = []
        for i in parsed.get("faq_items") or []:
            if isinstance(i, dict):
                aux_texts.append(str(i.get("question", "")))
                aux_texts.append(str(i.get("answer", "")))
        for x in list(parsed.get("confirmed_facts") or []) + list(parsed.get("check_needed") or []):
            if isinstance(x, str):
                aux_texts.append(x)
        scan_target = content + " " + " ".join(aux_texts)
        for pat in cls._FAKE_DATE_PATTERNS:
            m = re.search(pat, scan_target)
            if m:
                raise ValueError(
                    f"fake date hallucination detected: {m.group(0)!r}. "
                    "LLM이 구체 날짜·시각을 창작했습니다. 다음 provider로 fallback."
                )

