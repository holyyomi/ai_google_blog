from __future__ import annotations

from dataclasses import asdict
from html.parser import HTMLParser
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from blogspot_automation.models import FactPack, SourcePack, TopicCandidateStatus
from blogspot_automation.storage import StateStore
from blogspot_automation.utils.retry import retry_call


logger = logging.getLogger(__name__)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self._parts.append(cleaned)

    def as_text(self) -> str:
        return " ".join(self._parts)


def build_fact_pack(*, topic_id: str, store: StateStore) -> FactPack:
    topic_data = store.get_topic_by_id(topic_id)
    source_content, uncertainty_notes = _fetch_source_content(topic_data["source_url"])
    excerpts = _build_excerpts(source_content, topic_data)
    source_pack = SourcePack(
        topic_id=topic_id,
        source_name=str(topic_data["source_name"]),
        source_type=str(topic_data["source_type"]),
        source_url=str(topic_data["source_url"]),
        official_source_exists=True,
        source_urls=[str(topic_data["source_url"])],
        source_titles=[str(topic_data["candidate_title"])],
        source_excerpts=excerpts,
        source_quality_notes=[
            "Official source prioritized." if topic_data["source_type"] in {"rss", "page"} else "Source type requires manual review."
        ],
        uncertainty_notes=uncertainty_notes,
    )
    fact_pack_payload = {
        "what_it_is": _what_it_is(topic_data),
        "why_it_matters": _why_it_matters(topic_data),
        "who_it_is_for": _who_it_is_for(topic_data),
        "key_points": _key_points(topic_data, excerpts),
        "constraints": _constraints(topic_data),
        "risks": _risks(topic_data),
        "examples": _examples(topic_data),
        "source_urls": [str(topic_data["source_url"])],
        "unsupported_claims_to_avoid": _unsupported_claims(topic_data),
        "uncertainty_notes": uncertainty_notes,
    }
    payload = FactPack(
        topic_id=topic_id,
        topic_data=topic_data,
        source_pack=asdict(source_pack),
        fact_pack=fact_pack_payload,
    )
    store.save_source_pack(topic_id, {"topic_data": topic_data, "source_pack": asdict(source_pack)})
    store.save_fact_pack(topic_id, asdict(payload))
    store.update_topic_candidate_status(topic_id, TopicCandidateStatus.FACT_PACKED.value)
    return payload


def _fetch_source_content(source_url: str) -> tuple[str, list[str]]:
    request = Request(
        source_url,
        headers={
            "User-Agent": "blogspot-automation/0.1 (+https://local-cli)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    uncertainty_notes: list[str] = []

    def _send() -> str:
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    try:
        html = retry_call(
            operation=_send,
            attempts=3,
            delay_seconds=1.0,
            operation_name="build_fact_pack_source_fetch",
            logger=logger,
        )
    except (HTTPError, URLError, TimeoutError) as exc:
        uncertainty_notes.append(f"Could not refetch source page: {exc}")
        return "", uncertainty_notes

    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", parser.as_text()).strip()
    if len(text) < 120:
        uncertainty_notes.append("Source page text extraction was limited. Review the original source manually.")
    return text, uncertainty_notes


def _build_excerpts(source_content: str, topic_data: dict[str, object]) -> list[str]:
    if not source_content:
        return [str(topic_data["candidate_summary"])]
    sentences = re.split(r"(?<=[.!?])\s+", source_content)
    selected = [sentence.strip() for sentence in sentences if len(sentence.strip()) > 40][:5]
    return selected or [str(topic_data["candidate_summary"])]


def _what_it_is(topic_data: dict[str, object]) -> str:
    return (
        f"{topic_data['topic_name']} is an {topic_data['topic_type']} topic within the "
        f"{topic_data['topic_cluster']} cluster. It is grounded in the original source and should be explained without hype."
    )


def _why_it_matters(topic_data: dict[str, object]) -> str:
    return (
        f"It matters now because it supports the search angle '{topic_data['search_angle']}' "
        f"and maps to a practical reader intent of '{topic_data['user_intent']}'."
    )


def _who_it_is_for(topic_data: dict[str, object]) -> str:
    return (
        f"This topic is most relevant for {topic_data['audience_level']} readers interested in "
        f"{topic_data['topic_subcluster']} and globally understandable AI use cases."
    )


def _key_points(topic_data: dict[str, object], excerpts: list[str]) -> list[str]:
    base = [
        f"Main keyword: {topic_data['main_keyword']}",
        f"User intent: {topic_data['user_intent']}",
        f"Automation angle: {topic_data['automation_angle']}",
    ]
    return base + excerpts[:2]


def _constraints(topic_data: dict[str, object]) -> list[str]:
    return [
        "Use only source-grounded claims for features, pricing, availability, and launch details.",
        f"Keep the article scoped to the {topic_data['topic_cluster']} cluster instead of drifting into unrelated AI news.",
    ]


def _risks(topic_data: dict[str, object]) -> list[str]:
    return [
        "Do not overstate adoption, market share, or business outcomes without explicit source evidence.",
        "Do not infer product availability by country unless the source confirms it.",
        f"Do not present the monetization angle '{topic_data['monetization_angle']}' as a guaranteed outcome.",
    ]


def _examples(topic_data: dict[str, object]) -> list[str]:
    return [
        f"Example explainer block: define {topic_data['main_keyword']} in one clear paragraph.",
        f"Example checklist block: evaluate fit for {topic_data['topic_subcluster']}.",
        f"Example practical block: connect the topic to {topic_data['automation_angle']}.",
    ]


def _unsupported_claims(topic_data: dict[str, object]) -> list[str]:
    return [
        "Unverified pricing claims",
        "Unverified user growth numbers",
        "Unverified regional rollout claims",
        f"Claims that {topic_data['topic_name']} will automatically improve ROI",
    ]
