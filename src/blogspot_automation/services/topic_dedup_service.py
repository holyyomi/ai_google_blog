from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any

from blogspot_automation.models.news_models import ScoredNewsCandidate


STOPWORDS = {
    "오늘",
    "이슈",
    "뉴스",
    "논란",
    "화제",
    "이유",
    "진짜",
    "알고보니",
    "갑자기",
    # 이 블로그는 AI 전용(ai_blog.yml)이라 "ai"가 후보·이력 텍스트 거의
    # 전부에 등장하는 사실상의 도메인 불용어다. 겹침 임계값(>=2)에서
    # "ai"가 한 자리를 공짜로 채우면, 나머지 한 단어만 우연히 겹쳐도
    # 무관한 후보가 오탐 차단된다(2026-07-11 publish_draft 리허설 실측:
    # "오픈AI 공개 AI 소식"이 candidate.reason의 상투어 "직장인"과
    # 과거 "...직장인 업무에 미치는 영향" 글의 "직장인"만 겹쳐 차단).
    "ai",
    # 영어 전환(2026-07-17) 추가 — 영어 제목/요약의 filler 단어가 키워드 겹침
    # (>=2 차단)의 자리를 공짜로 채우지 않도록 하는 영어 불용어.
    "the",
    "a",
    "an",
    "and",
    "or",
    "for",
    "to",
    "of",
    "in",
    "on",
    "with",
    "your",
    "you",
    "how",
    "what",
    "why",
    "when",
    "is",
    "are",
    "it",
    "this",
    "that",
    "vs",
    "versus",
    "best",
    "guide",
    "tools",
    "tool",
    "new",
    "free",
    "2025",
    "2026",
    "worth",
    "really",
    "actually",
    "tested",
    "explained",
    "complete",
    "ultimate",
    "tips",
    "ways",
    "top",
}
GENERIC_DEDUP_KEYWORD_PREFIXES = (
    "신청",
    "대상",
    "조건",
    "지급",
    "사용처",
    "방법",
    "마감",
    "기간",
    "체크",
    "정리",
    "확인",
    "지원",
    "보조",
    "환급",
    "혜택",
    "금액",
    "최대",
    "먼저",
    "가지",
)
GENERIC_DEDUP_KEYWORDS = {
    "지원금",
    "정부지원금",
    "피해지원금",
    "신청방법",
    "대상조건",
    "지급일",
    "필요서류",
    "공식",
    "안내",
    "체크리스트",
    # AI 뉴스 템플릿 상투어(2026-07-11): "{회사} AI 기능 설정" / "{회사} AI 소식"
    # 틀이 실제 사건과 무관하게 매주 반복돼, 서로 다른 회사·뉴스인 후보끼리도
    # "ai"+"기능"+"설정" 2단어 겹침으로 오탐 dedup 차단됐다(라이브 리허설 실측:
    # 삼성D 게이밍 OLED 뉴스가 "구글 지도 AI 기능 설정"과 겹침 판정). 겹침
    # 판정은 실제 엔티티·사건 단어로만 이뤄져야 한다.
    "기능",
    "설정",
    "소식",
    "공개",
    # ScoredNewsCandidate.reason(스코어링 근거 문구)이 _candidate_texts()에
    # 포함되는데, "AI 서비스 변화는 직장인 생산성과 연결돼…" 같은 상투
    # 독자층 설명이 거의 모든 후보에 반복돼 실제 주제와 무관하게 겹침을
    # 만든다(2026-07-11 리허설 실측).
    "직장인",
    # 영어 전환(2026-07-17) 추가 — 영어 AI 뉴스 템플릿 상투 토큰. 겹침 판정은
    # 단일 토큰 비교이므로 구("how to use")가 아닌 토큰 단위로 등록한다.
    # 실제 엔티티·사건 단어만 겹침 신호가 되도록 generic 토큰을 제외한다.
    "use",
    "using",
    "feature",
    "features",
    "update",
    "updates",
    "settings",
    "setup",
    "news",
}

# 회사/소재 쿨다운 (2026-07 운영 방침: 같은 회사·소재는 7일에 1회만 발행).
# 서로 다른 뉴스가 같은 주체(네이버/구글/OpenAI 등)로 며칠 연속 발행되는
# "주제 모양 중복"을 막는다. 제목·주제가 조금씩 달라 키워드 겹침 규칙을
# 빠져나가더라도, 같은 주체면 쿨다운 기간 내 재발행을 차단한다.
ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "naver": ("네이버", "naver", "클로바", "clova", "하이퍼클로바", "큐", "cue"),
    "google": ("구글", "google", "제미나이", "gemini", "바드", "bard"),
    "openai": ("오픈ai", "openai", "챗gpt", "chatgpt", "gpt", "소라", "sora"),
    "anthropic": ("앤트로픽", "anthropic", "클로드", "claude"),
    "microsoft": ("마이크로소프트", "microsoft", "코파일럿", "copilot", "빙", "bing"),
    "meta": ("메타", "meta", "라마", "llama"),
    "perplexity": ("퍼플렉시티", "perplexity"),
    "mistral": ("미스트랄", "mistral"),
    "kakao": ("카카오", "kakao", "카나나", "kanana"),
    "apple": ("애플", "apple"),
    "amazon": ("아마존", "amazon", "알렉사", "alexa"),
    "xai": ("그록", "grok", "xai"),
}
# 짧거나 다른 단어에 섞여 오탐 위험이 큰 alias는 토큰 경계로만 매칭한다
# (예: "메타"는 "메타버스"에, "gpt"는 "chatgpt"에 substring으로 걸리면 안 됨).
_TOKEN_ONLY_ALIASES = {
    "gpt",
    "meta",
    "메타",
    "bard",
    "바드",
    "bing",
    "빙",
    "cue",
    "큐",
    "sora",
    "소라",
    "grok",
    "그록",
    "xai",
    "ms",
    "alexa",
    "알렉사",
    "llama",
    "라마",
}


# draft_saved_for_review 소프트 소비(2026-07-18 실측): 초안으로 끝난 주제는
# published=False라서 record_blocks_duplicate가 걸러내고, 다음 실행이 곧바로
# 같은 주제를 재선택해 고아 초안이 3연속 쌓였다. 초안은 실발행이 아니므로
# 영구 dedup·엔티티 쿨다운 근거로는 계속 제외하되, 사람이 검토할 48시간
# 동안만 같은 주제 재선택을 막는다.
DRAFT_REVIEW_STATUS = "draft_saved_for_review"
DRAFT_SOFT_CONSUME_HOURS = 48


class TopicDedupService:
    def __init__(
        self,
        *,
        state_dir: str | Path = "state",
        dedup_days: int = 7,
        entity_cooldown_days: int | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.dedup_days = max(0, dedup_days)
        # 회사/소재 쿨다운 창. 기본 3일(2026-07-22 사용자 지시로 7→3 단축 —
        # AI 전문 블로그에서는 ChatGPT/OpenAI/Google 같은 상시 엔티티가 거의 모든
        # 주제에 등장해, 7일 창이 에버그린 뱅크 전체를 차단하고 발행 0건 슬롯을
        # 만들었다: 2026-07-22 아침 슬롯 실측 skipped_after_retry_limit).
        # ENTITY_COOLDOWN_DAYS env로 조정 가능, 0이면 비활성, 호출부 명시값 우선.
        if entity_cooldown_days is None:
            raw = (os.getenv("ENTITY_COOLDOWN_DAYS", "") or "").strip()
            entity_cooldown_days = int(raw) if raw.isdigit() else 3
        self.entity_cooldown_days = max(0, entity_cooldown_days)

    def exclude_recent_duplicates(
        self,
        candidates: list[ScoredNewsCandidate],
        *,
        history_records: list[dict[str, Any]] | None = None,
    ) -> list[ScoredNewsCandidate]:
        history_records = history_records if history_records is not None else self.load_history()
        if not history_records:
            return candidates

        filtered: list[ScoredNewsCandidate] = []
        for candidate in candidates:
            if not self.is_duplicate(candidate, history_records):
                filtered.append(candidate)
        return filtered

    def load_history(self) -> list[dict]:
        history_files = [
            self.state_dir / "published_history.json",
            self.state_dir / "news_published_history.json",
        ]
        history_path = next((path for path in history_files if path.exists()), None)
        if history_path is None:
            return []

        try:
            raw = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            for key in ("records", "list", "items", "history"):
                value = raw.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def recent_published_entities(
        self, *, days: int, history_records: list[dict[str, Any]]
    ) -> set[str]:
        """최근 N일간 실제 발행된 글들의 엔티티 합집합.

        엔티티 쿨다운(하드 차단)과 달리, 이건 evergreen 폴백 후보를 정렬할 때
        "최근에 안 다룬 AI를 우선"하는 소프트 랭킹 신호로만 쓴다 — 다양성은
        원하지만 후보 풀이 전멸하면 안 되기 때문(2026-07-22 실측 사고).
        """
        entities: set[str] = set()
        for record in history_records:
            if not self.record_blocks_duplicate(record):
                continue
            if not self._is_within_window(record, days):
                continue
            entities |= self.extract_entities(self._history_subject_text(record))
        return entities

    def is_duplicate(self, candidate: ScoredNewsCandidate, history_records: list[dict]) -> bool:
        candidate_texts = self._candidate_texts(candidate)
        candidate_norms = [
            norm
            for norm in (self.normalize_text(text) for text in candidate_texts)
            if norm
        ]
        candidate_text = " ".join(candidate_texts).strip()
        candidate_keywords = self.extract_keywords(candidate_text)
        candidate_entities = self.extract_entities(self._candidate_subject_text(candidate))

        for record in history_records:
            if not self.record_blocks_duplicate(record):
                # 초안(draft_saved_for_review)은 발행이 아니므로 영구 dedup·엔티티
                # 쿨다운에는 넣지 않지만, 검토 대기 48시간 동안은 같은 주제
                # 재선택(=고아 초안 반복 생성)만 소프트 차단한다.
                if self._draft_soft_blocks(record, candidate_norms, candidate_keywords):
                    return True
                continue

            in_dedup_window = self._is_within_dedup_window(record)

            # 회사/소재 쿨다운: 같은 주체(네이버/구글/OpenAI 등)를 쿨다운 창 안에
            # 이미 발행했으면, 제목·주제가 달라도 재발행을 막는다.
            # 단, 에버그린 폴백(evergreen_fallback=True)은 예외 — AI 툴 비교/가격
            # 콘텐츠는 구조적으로 상시 엔티티(ChatGPT/Claude/Gemini 등)를 반복
            # 언급하므로 이 규칙을 그대로 적용하면 며칠 안에 뱅크 전체가 봉쇄된다
            # (2026-07-22 실측: 골든패턴 매칭 14개가 엔티티 쿨다운에서 전부 제외돼
            # 발행 0건). 콘텐츠 레벨 dedup(제목/키워드 근접중복)은 계속 적용된다.
            if (
                candidate_entities
                and not self._is_entity_cooldown_exempt(candidate)
                and self._is_within_window(record, self.entity_cooldown_days)
            ):
                history_entities = self.extract_entities(
                    self._history_subject_text(record)
                )
                if candidate_entities & history_entities:
                    return True

            if not in_dedup_window:
                continue

            history_texts = self._history_texts(record)
            if not history_texts:
                continue

            history_norms = [
                norm
                for norm in (self.normalize_text(text) for text in history_texts)
                if norm
            ]
            if any(
                self._norms_match(candidate_norm, history_norm)
                for candidate_norm in candidate_norms
                for history_norm in history_norms
            ):
                return True

            history_text = " ".join(history_texts)
            history_keywords = self.extract_keywords(history_text)
            overlap_count = len(candidate_keywords & history_keywords)
            if overlap_count >= 2:
                return True

        return False

    @staticmethod
    def _is_entity_cooldown_exempt(candidate: ScoredNewsCandidate) -> bool:
        if (os.getenv("ENTITY_COOLDOWN_APPLIES_TO_EVERGREEN", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return False
        raw = candidate.candidate.raw if isinstance(candidate.candidate.raw, dict) else {}
        return bool(raw.get("evergreen_fallback"))

    def candidate_entities(self, candidate: ScoredNewsCandidate) -> set[str]:
        return self.extract_entities(self._candidate_subject_text(candidate))

    def extract_entities(self, text: str) -> set[str]:
        """텍스트에서 알려진 회사/소재 엔티티를 뽑는다.

        오탐을 줄이려고 구별성 높은 브랜드명은 substring으로, 짧거나 다른
        단어에 섞이기 쉬운 alias(_TOKEN_ONLY_ALIASES)는 토큰 경계로만 찾는다.
        """
        if not text:
            return set()
        lowered = text.lower()
        cleaned = re.sub(r"[^0-9a-z가-힣\s]", " ", lowered)
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return set()
        tokens = set(cleaned.split())
        found: set[str] = set()
        for entity, aliases in ENTITY_ALIASES.items():
            for alias in aliases:
                normalized_alias = alias.lower()
                if normalized_alias in _TOKEN_ONLY_ALIASES:
                    matched = normalized_alias in tokens
                elif " " in normalized_alias:
                    matched = normalized_alias in cleaned
                else:
                    matched = normalized_alias in cleaned
                if matched:
                    found.add(entity)
                    break
        return found

    def _candidate_subject_text(self, candidate: ScoredNewsCandidate) -> str:
        """엔티티 판정용 텍스트 — 요약/근거는 빼고 '무엇에 관한 글인가'만 본다.

        요약·근거에는 경쟁사 언급이 섞여 엔티티를 오검출할 수 있어 제외한다.
        """
        raw = candidate.candidate.raw if isinstance(candidate.candidate.raw, dict) else {}
        fields = (
            candidate.candidate.topic,
            raw.get("search_demand_topic"),
            raw.get("original_topic"),
            raw.get("transformed_topic"),
            raw.get("title"),
            raw.get("selected_title"),
        )
        return " ".join(str(value).strip() for value in fields if str(value or "").strip())

    def _history_subject_text(self, record: dict[str, Any]) -> str:
        fields = ("topic", "selected_topic", "search_demand_topic", "title", "selected_title")
        return " ".join(
            str(record.get(field, "")).strip()
            for field in fields
            if str(record.get(field, "") or "").strip()
        )

    def normalize_text(self, text: str) -> str:
        lowered = text.lower()
        compact = re.sub(r"[^0-9a-z가-힣\s]", " ", lowered)
        compact = " ".join(compact.split())
        if not compact:
            return ""
        tokens = [token for token in compact.split() if token not in STOPWORDS and len(token) > 1]
        return " ".join(tokens)

    def extract_keywords(self, text: str) -> set[str]:
        normalized = self.normalize_text(text)
        if not normalized:
            return set()
        return {
            token
            for token in normalized.split()
            if token not in STOPWORDS
            and len(token) > 1
            and not token.isdigit()
            and not self._is_generic_keyword(token)
        }

    def _is_generic_keyword(self, token: str) -> bool:
        compact = token.strip().lower()
        if compact in GENERIC_DEDUP_KEYWORDS:
            return True
        return any(compact.startswith(prefix) for prefix in GENERIC_DEDUP_KEYWORD_PREFIXES)

    def _candidate_texts(self, candidate: ScoredNewsCandidate) -> list[str]:
        raw = candidate.candidate.raw if isinstance(candidate.candidate.raw, dict) else {}
        fields = (
            candidate.candidate.topic,
            raw.get("search_demand_topic"),
            raw.get("original_topic"),
            raw.get("transformed_topic"),
            raw.get("source_title"),
            raw.get("title"),
            raw.get("selected_title"),
            candidate.candidate.summary,
            candidate.reason,
        )
        values = [str(value).strip() for value in fields if str(value or "").strip()]
        return list(dict.fromkeys(values))

    def _history_texts(self, record: dict[str, Any]) -> list[str]:
        # "url" 포함 이유: 토픽 필드가 비어도 슬러그 단어("ai-work-automation-
        # productivity")가 근사매칭 신호가 된다. 대가: url이 "/2026/07/..."를
        # 항상 포함해 "2026" 같은 순수 숫자 토큰이 모든 레코드에 공통으로
        # 섞여 들어간다 — extract_keywords()가 숫자만인 토큰을 걸러내
        # 이 오염을 차단한다(2026-07-11 라이브 리허설 실측: "AI"+"2026" 우연
        # 일치로 무관한 후보 9개 전부가 dedup에 걸림).
        fields = (
            "topic",
            "selected_topic",
            "search_demand_topic",
            "title",
            "selected_title",
            "source_title",
            "keyword",
            "url",
            "summary",
        )
        values = [str(record.get(field, "")).strip() for field in fields]
        return list(dict.fromkeys(value for value in values if value))

    def _history_text(self, record: dict[str, Any]) -> str:
        return " ".join(self._history_texts(record))

    @staticmethod
    def record_blocks_duplicate(record: dict[str, Any]) -> bool:
        """Return True only for records that represent an actual published post.

        Failed, held, or duplicate-skipped attempts are useful for scheduling and
        learning, but they must not make the next run think a topic was already
        published.
        """
        status = str(record.get("status") or "").strip().lower()
        if status in {"published", "trending_published"}:
            return True
        if record.get("published") is True or record.get("publish_succeeded") is True:
            return True
        if record.get("published") is False or record.get("publish_succeeded") is False:
            return False
        if status:
            return False
        return bool(
            record.get("url")
            or record.get("post_url")
            or record.get("published_url")
            or record.get("blogger_url")
            or record.get("post_id")
        )

    @staticmethod
    def _norms_match(candidate_norm: str, history_norm: str) -> bool:
        if not candidate_norm or not history_norm:
            return False
        if candidate_norm == history_norm:
            return True
        shorter, longer = sorted((candidate_norm, history_norm), key=len)
        shorter_compact = shorter.replace(" ", "")
        longer_compact = longer.replace(" ", "")
        return len(shorter_compact) >= 6 and shorter_compact in longer_compact

    def _draft_soft_blocks(
        self,
        record: dict[str, Any],
        candidate_norms: list[str],
        candidate_keywords: set[str],
    ) -> bool:
        """검토 대기 초안이 48시간 동안 같은 주제 재선택을 소프트 차단하는지 판정.

        record_blocks_duplicate가 False인 레코드에만 호출된다 — 즉 초안은 여전히
        영구 dedup·엔티티 쿨다운에는 포함되지 않는다.
        """
        status = str(record.get("status") or "").strip().lower()
        if status != DRAFT_REVIEW_STATUS:
            return False
        if not self._is_within_hours(record, DRAFT_SOFT_CONSUME_HOURS):
            return False
        history_texts = self._history_texts(record)
        if not history_texts:
            return False
        history_norms = [
            norm
            for norm in (self.normalize_text(text) for text in history_texts)
            if norm
        ]
        if any(
            self._norms_match(candidate_norm, history_norm)
            for candidate_norm in candidate_norms
            for history_norm in history_norms
        ):
            return True
        history_keywords = self.extract_keywords(" ".join(history_texts))
        return len(candidate_keywords & history_keywords) >= 2

    def _is_within_hours(self, record: dict[str, Any], window_hours: int) -> bool:
        if window_hours <= 0:
            return False
        parsed = None
        for value in (
            record.get("date"),
            record.get("published_at"),
            record.get("created_at"),
            record.get("updated_at"),
        ):
            parsed = self._parse_datetime(value)
            if parsed is not None:
                break
        if parsed is None:
            # 날짜를 알 수 없으면 보수적으로 창 안으로 취급 (_is_within_window와 동일)
            return True
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return now - parsed <= timedelta(hours=window_hours)

    def _parse_datetime(self, value: Any) -> datetime | None:
        """ISO datetime을 시간 단위까지 파싱하고, 날짜만 있으면 자정으로 승격.

        기존 _parse_date(날짜 단위)를 폴백으로 재사용한다.
        """
        if not value or not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        parsed_date = self._parse_date(text)
        if parsed_date is None:
            return None
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day)

    def _is_within_dedup_window(self, record: dict[str, Any]) -> bool:
        return self._is_within_window(record, self.dedup_days)

    def _is_within_window(self, record: dict[str, Any], window_days: int) -> bool:
        if window_days <= 0:
            return False
        date_candidates = [
            record.get("date"),
            record.get("published_at"),
            record.get("created_at"),
            record.get("updated_at"),
        ]
        parsed_date = None
        for value in date_candidates:
            parsed_date = self._parse_date(value)
            if parsed_date is not None:
                break

        if parsed_date is None:
            # 날짜를 알 수 없으면 보수적으로 비교 대상에 포함
            return True

        cutoff = date.today() - timedelta(days=window_days)
        return parsed_date >= cutoff

    def _parse_date(self, value: Any) -> date | None:
        if not value or not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        # ISO datetime("2026-04-27T...")도 앞 10자리로 안전 파싱
        token = text[:10]
        try:
            return date.fromisoformat(token)
        except ValueError:
            return None
