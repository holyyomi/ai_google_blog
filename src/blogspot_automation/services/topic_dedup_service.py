from __future__ import annotations

from datetime import date, timedelta
import json
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
}


class TopicDedupService:
    def __init__(self, *, state_dir: str | Path = "state", dedup_days: int = 7) -> None:
        self.state_dir = Path(state_dir)
        self.dedup_days = max(0, dedup_days)

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

    def is_duplicate(self, candidate: ScoredNewsCandidate, history_records: list[dict]) -> bool:
        candidate_texts = self._candidate_texts(candidate)
        candidate_norms = [
            norm
            for norm in (self.normalize_text(text) for text in candidate_texts)
            if norm
        ]
        candidate_text = " ".join(candidate_texts).strip()
        candidate_keywords = self.extract_keywords(candidate_text)

        for record in history_records:
            if not self.record_blocks_duplicate(record):
                continue
            if not self._is_within_dedup_window(record):
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

    def _is_within_dedup_window(self, record: dict[str, Any]) -> bool:
        if self.dedup_days <= 0:
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

        cutoff = date.today() - timedelta(days=self.dedup_days)
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
