from __future__ import annotations

from typing import Any

from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.seo_policy import normalize_hashtags, normalize_labels


COMMON_LABELS = ("AI활용", "업무자동화", "AI도구", "프롬프트")

# ─── 영어 전환(2026-07-17): 6개 고정 라벨 체계 ────────────────────────────────
# Comparisons / Pricing / How-To / Fixes / Data & Stats / News 로 통일해
# 라벨 페이지 = 토픽 클러스터 허브로 쓴다 (내부링크가 라벨 검색 URL로 걸린다).
EN_LABEL_FAMILIES = ("Comparisons", "Pricing", "How-To", "Fixes", "Data & Stats", "News")

_EN_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Comparisons", (" vs ", "vs.", "versus", "alternative", "best ai", "best free", "worth it", "compare", "comparison", "which ")),
    ("Pricing", ("pricing", "price", "cost", "fee", "subscription", "per month", "/month", "free tier", "paid plan", "hidden cost", "free vs")),
    ("Fixes", ("not working", "fix", "error", "limit", "blocked", "bypass", "troubleshoot", "wrong answers", "workaround", "outage")),
    ("Data & Stats", ("statistics", "stats", "benchmark", "adoption", "context window", "the numbers")),
    ("How-To", ("how to", "guide", "tutorial", "setup", "automate", "use chatgpt", "use claude", "use ai", "workflow")),
)

# 영어 해시태그용 엔티티 표기 (탐지 토큰 → 태그 표기)
_EN_ENTITY_TAGS: tuple[tuple[str, str], ...] = (
    ("chatgpt", "ChatGPT"),
    ("openai", "OpenAI"),
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("copilot", "Copilot"),
    ("perplexity", "Perplexity"),
    ("midjourney", "Midjourney"),
    ("notion", "NotionAI"),
    ("grok", "Grok"),
    ("deepseek", "DeepSeek"),
    ("llama", "Llama"),
    ("cursor", "CursorAI"),
)


def en_content_family(*parts: str) -> str:
    """제목·주제 텍스트에서 6개 라벨 중 하나를 고른다 (기본 News)."""
    blob = " ".join(str(p or "") for p in parts).lower()
    for family, tokens in _EN_FAMILY_RULES:
        if any(tok in blob for tok in tokens):
            return family
    return "News"

# Blogspot 발행용 라벨 2~3개 — pattern_id 기준 우선
BLOGSPOT_LABELS_BY_PATTERN_ID: dict[str, tuple[str, ...]] = {
    "viral_ott_reaction_decode": ("AI뉴스해석", "콘텐츠AI", "AI트렌드"),
    "ai_work_time_savings": ("AI활용", "업무자동화", "생산성"),
    "ai_tool_comparison": ("AI도구비교", "AI활용", "생산성"),
    "ai_automation_workflow": ("AI자동화", "워크플로", "생산성"),
    "tax_refund_hometax_check": ("AI활용", "체크리스트", "생산성"),
}

BLOGSPOT_LABELS_BY_CONTENT_TYPE: dict[str, tuple[str, ...]] = {
    "viral_issue_decode": ("AI뉴스해석", "AI트렌드", "이슈해석"),
    "ai_work_tip": ("AI활용", "업무자동화", "생산성"),
    "tax_refund": ("AI활용", "체크리스트", "생산성"),
    "money_checklist": ("AI활용", "비용절감", "생산성"),
    "policy_deadline": ("AI활용", "체크리스트", "업무자동화"),
    "platform_change": ("AI서비스", "설정체크", "AI활용"),
    "general_life": ("AI활용", "체크리스트", "프롬프트"),
}

BLOGSPOT_LABELS_BY_TOPIC_GROUP: dict[str, tuple[str, ...]] = {
    "policy_benefit": ("AI활용", "체크리스트", "생산성"),
    "ai_work": ("AI활용", "업무자동화", "생산성"),
    "delivery_money": ("AI활용", "비용절감", "생산성"),
    "refund_consumer": ("AI보안", "리스크체크", "체크리스트"),
    "privacy_security": ("AI보안", "개인정보보호", "계정보안"),
    "platform_issue": ("AI서비스", "설정체크", "AI활용"),
    "ott_platform": ("콘텐츠AI", "AI트렌드", "이슈해석"),
    "entertainment_sports": ("콘텐츠AI", "AI트렌드", "이슈해석"),
    "fandom_consumer": ("콘텐츠AI", "AI트렌드", "이슈해석"),
    "general_life": ("AI활용", "체크리스트", "프롬프트"),
}

TOPIC_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    "policy_benefit": ("AI활용", "업무자동화", "생산성", "체크리스트", "AI도구"),
    "delivery_money": ("배달료", "배달앱", "생활비", "소비자", "자영업자", "수수료"),
    "refund_consumer": ("AI보안", "리스크체크", "개인정보보호", "체크리스트", "검수"),
    "privacy_security": ("AI보안", "개인정보보호", "계정보안", "검수", "체크리스트"),
    "platform_issue": ("AI서비스", "기능변경", "설정체크", "계정관리", "AI활용"),
    "ai_work": ("AI활용", "업무자동화", "생산성", "AI도구", "프롬프트", "AI보안"),
    "trend_meme": ("AI트렌드", "콘텐츠AI", "SNS자동화", "AI활용"),
    "entertainment_sports": ("콘텐츠AI", "AI트렌드", "이슈분석", "AI활용"),
    "ott_platform": ("OTT", "드라마반응", "넷플릭스", "시청자반응", "콘텐츠소비", "이슈해석"),
    "fandom_consumer": ("팬덤소비", "굿즈", "티켓팅", "콘서트", "아이돌", "이슈해석"),
    "general_life": ("AI활용", "선택기준", "체크리스트", "프롬프트"),
}

CONTENT_TYPE_LABELS: dict[str, tuple[str, ...]] = {
    "policy_deadline": ("신청조건", "마감체크", "지원정보"),
    "tax_refund": ("환급신청", "환급금조회", "홈택스"),
    "money_checklist": ("비용비교", "체크리스트", "절약정보"),
    "consumer_warning": ("피해예방", "소비자대응", "증거확인"),
    "platform_change": ("변경확인", "서비스공지", "디지털생활"),
    "ai_work_tip": ("업무팁", "AI활용", "생산성"),
    "trend_decode": ("소비판단", "트렌드분석", "선택기준"),
    "viral_issue_decode": ("AI뉴스해석", "반응분석", "AI트렌드"),
    "general_life": ("AI활용", "선택기준", "체크리스트"),
}

BANNED_LABEL_FRAGMENTS = (
    "v.daum.net",
    "n.news.naver.com",
    ".com",
    ".co.kr",
    "KBS 뉴스",
    "조선일보",
    "중앙일보",
    "데일리안",
    "미디어펜",
    "더퍼블릭",
)


HASHTAG_BASE_BY_CONTENT_TYPE: dict[str, tuple[str, ...]] = {
    "tax_refund": ("AI활용", "체크리스트", "생산성", "AI도구"),
    "policy_deadline": ("AI활용", "업무자동화", "체크리스트", "생산성"),
    "consumer_warning": ("AI보안", "리스크체크", "검수", "체크리스트"),
    "money_checklist": ("AI활용", "비용절감", "생산성", "체크리스트"),
    "platform_change": ("AI서비스", "기능변경", "설정체크", "AI활용"),
    "ai_work_tip": ("AI활용", "업무자동화", "생산성", "AI도구", "프롬프트", "AI보안"),
    "trend_decode": ("AI트렌드", "콘텐츠AI", "SNS자동화", "선택기준", "AI활용"),
    "viral_issue_decode": ("AI뉴스해석", "이슈해석", "반응분석", "콘텐츠AI"),
}

HASHTAG_BASE_BY_TOPIC_GROUP: dict[str, tuple[str, ...]] = {
    "ai_work": ("AI활용", "업무자동화", "생산성", "AI도구", "프롬프트", "AI보안"),
    "refund_consumer": ("AI보안", "리스크체크", "피해예방", "검수", "체크리스트"),
    "privacy_security": ("개인정보보호", "계정보안", "AI보안", "검수", "체크리스트"),
}

HASHTAG_BANNED_BY_CONTENT_TYPE: dict[str, tuple[str, ...]] = {
    "tax_refund": ("지원금", "신청마감", "대상조건", "사용처", "정부지원", "지역상품권", "바우처", "가맹점"),
    "policy_deadline": ("세금환급", "환급금조회", "홈택스", "손택스", "국세환급금", "환급계좌"),
    "ai_work_tip": ("지원금", "세금환급", "환급금조회", "사용처", "신청마감"),
    "platform_change": ("지원금", "세금환급", "환급금조회"),
}


class NewsLabelService:
    def build_blogspot_labels(
        self,
        *,
        pattern_id: str = "",
        content_type: str = "",
        topic_group: str = "",
    ) -> list[str]:
        """Blogspot 발행용 라벨을 2~3개로 제한해 반환한다."""
        if is_english_mode():
            # 주제 텍스트가 없는 경로라 family는 build()/해시태그 쪽에서 정교화되고,
            # 여기서는 클러스터 기본 라벨만 준다.
            return normalize_labels(["News", "AI Tools"])
        if pattern_id and pattern_id in BLOGSPOT_LABELS_BY_PATTERN_ID:
            return normalize_labels(list(BLOGSPOT_LABELS_BY_PATTERN_ID[pattern_id]))
        if content_type and content_type in BLOGSPOT_LABELS_BY_CONTENT_TYPE:
            return normalize_labels(list(BLOGSPOT_LABELS_BY_CONTENT_TYPE[content_type]))
        return normalize_labels(list(BLOGSPOT_LABELS_BY_TOPIC_GROUP.get(
            topic_group, ("AI활용", "업무자동화", "AI도구")
        )))

    def build(
        self,
        *,
        selected_topic: str,
        selected_title: str,
        topic_group: str,
        content_type: str,
        content_angle: dict[str, Any] | None = None,
        existing_labels: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        if is_english_mode():
            family = en_content_family(selected_topic, selected_title)
            labels_en = [family, "AI Tools"]
            blob = f"{selected_topic} {selected_title}".lower()
            for token, tag in _EN_ENTITY_TAGS:
                if token in blob:
                    labels_en.append(tag)
                    break
            return normalize_labels(labels_en[:4])
        labels: list[str] = []
        if content_type == "tax_refund":
            labels.extend(CONTENT_TYPE_LABELS["tax_refund"])
            labels.extend(("세금환급", "국세환급금", "환급계좌"))
        else:
            labels.extend(TOPIC_GROUP_LABELS.get(topic_group, TOPIC_GROUP_LABELS["general_life"])[:4])
            labels.extend(CONTENT_TYPE_LABELS.get(content_type, CONTENT_TYPE_LABELS["general_life"])[:2])
        labels.extend(COMMON_LABELS)
        labels.extend(self._keyword_labels(f"{selected_topic} {selected_title}")[:2])
        labels.extend(existing_labels or [])
        return self._finalize(labels)

    def build_hashtags(
        self,
        *,
        selected_topic: str,
        selected_title: str,
        topic_group: str,
        content_type: str,
        labels: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        if is_english_mode():
            blob = f"{selected_topic} {selected_title}".lower()
            family = en_content_family(selected_topic, selected_title)
            tags_en = ["#AI", f"#{family.replace(' & ', '').replace(' ', '').replace('-', '')}", "#AITools"]
            for token, tag in _EN_ENTITY_TAGS:
                if token in blob and f"#{tag}" not in tags_en:
                    tags_en.append(f"#{tag}")
                if len(tags_en) >= 6:
                    break
            return normalize_hashtags(tags_en)
        candidates: list[str] = list(
            HASHTAG_BASE_BY_TOPIC_GROUP.get(topic_group, HASHTAG_BASE_BY_CONTENT_TYPE.get(content_type, ()))
        )
        if content_type != "tax_refund":
            candidates.extend(TOPIC_GROUP_LABELS.get(topic_group, ())[:3])
            candidates.extend(labels or [])
        else:
            candidates.extend(CONTENT_TYPE_LABELS.get(content_type, ()))
        candidates.extend(self._keyword_labels(f"{selected_topic} {selected_title}"))

        cleaned: list[str] = []
        for item in candidates:
            text = self._clean_label(str(item or "").replace("#", ""))
            if not text or len(text) > 14:
                continue
            if self._is_banned(text) or self._is_banned_for_content_type(content_type, text):
                continue
            tag = f"#{text}"
            if tag not in cleaned:
                cleaned.append(tag)
        for fallback in ("#AI활용", "#업무자동화", "#프롬프트"):
            if len(cleaned) >= 6:
                break
            fallback_text = fallback.lstrip("#")
            if self._is_banned_for_content_type(content_type, fallback_text):
                continue
            if fallback not in cleaned:
                cleaned.append(fallback)
        return normalize_hashtags(cleaned)

        base_by_type = {
            "tax_refund": ("AI활용", "체크리스트", "생산성", "AI도구"),
            "policy_deadline": ("AI활용", "업무자동화", "체크리스트", "생산성"),
            "consumer_warning": ("AI보안", "리스크체크", "검수", "체크리스트"),
            "money_checklist": ("AI활용", "비용절감", "생산성", "체크리스트"),
            "platform_change": ("AI서비스", "기능변경", "설정체크", "AI활용"),
            "ai_work_tip": ("AI활용", "업무자동화", "생산성", "AI도구", "프롬프트", "AI보안"),
            "trend_decode": ("AI트렌드", "콘텐츠AI", "SNS자동화", "선택기준", "AI활용"),
        }
        candidates: list[str] = list(base_by_type.get(content_type, ()))
        candidates.extend(TOPIC_GROUP_LABELS.get(topic_group, ())[:3])
        candidates.extend(labels or [])
        candidates.extend(self._keyword_labels(f"{selected_topic} {selected_title}"))
        cleaned: list[str] = []
        for item in candidates:
            text = self._clean_label(str(item or "").replace("#", ""))
            if not text or len(text) > 14:
                continue
            if self._is_banned(text):
                continue
            tag = f"#{text}"
            if tag not in cleaned:
                cleaned.append(tag)
        for fallback in ("#AI활용", "#업무자동화", "#프롬프트"):
            if len(cleaned) >= 6:
                break
            if fallback not in cleaned:
                cleaned.append(fallback)
        return normalize_hashtags(cleaned)

    def _finalize(self, labels: list[str]) -> list[str]:
        cleaned: list[str] = []
        for label in labels:
            text = self._clean_label(label)
            if not text:
                continue
            if self._is_banned(text):
                continue
            if len(text) > 20:
                continue
            if text not in cleaned:
                cleaned.append(text)

        for fallback in (*COMMON_LABELS, "체크리스트", "선택기준"):
            if len(cleaned) >= 4:
                break
            text = self._clean_label(fallback)
            if text and text not in cleaned:
                cleaned.append(text)

        return normalize_labels(cleaned[:4])

    @staticmethod
    def _keyword_labels(text: str) -> list[str]:
        labels: list[str] = []
        compact = text.replace(" ", "")
        if "청년" in compact and "지원" in compact:
            labels.append("청년지원")
        if "배달" in compact:
            labels.append("배달앱")
        if "환불" in compact:
            labels.append("환불")
        if "개인정보" in compact:
            labels.append("개인정보보호")
        if "비밀번호" in compact:
            labels.append("비밀번호변경")
        if "계정" in compact or "피싱" in compact:
            labels.append("계정보안")
        if "AI" in text or "ai" in text.lower():
            labels.append("AI")
        if "구독" in compact or "요금" in compact:
            labels.append("요금변경")
        if "마감" in compact:
            labels.append("마감체크")
        if "애드센스" in compact:
            labels.append("애드센스")
        if "블로그스팟" in compact:
            labels.append("블로그스팟")
        if "자동화" in compact:
            labels.append("자동화")
        if "홈택스" in compact:
            labels.append("홈택스")
        if "구독" in compact:
            labels.append("구독관리")
        if "팬덤" in compact or "굿즈" in compact or "티켓팅" in compact:
            labels.append("팬덤소비")
        if "ott" in compact.lower() or "넷플릭스" in compact or "드라마" in compact:
            labels.append("OTT")
        if "스포츠" in compact or "경기" in compact or "야구" in compact or "축구" in compact:
            labels.append("스포츠반응")
        if "반응" in compact and "갈린" in compact:
            labels.append("이슈해석")
        return labels

    @staticmethod
    def _clean_label(label: str) -> str:
        return "".join(str(label or "").split()).strip(" ,.-_/\\")

    @staticmethod
    def _is_banned(label: str) -> bool:
        lowered = label.lower()
        return any(fragment.lower() in lowered for fragment in BANNED_LABEL_FRAGMENTS)

    @staticmethod
    def _is_banned_for_content_type(content_type: str, label: str) -> bool:
        forbidden = HASHTAG_BANNED_BY_CONTENT_TYPE.get(content_type or "", ())
        return any(term in label for term in forbidden)
