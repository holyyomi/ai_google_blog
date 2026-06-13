from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
import xml.etree.ElementTree as ET

from blogspot_automation.topic_discovery.fetcher import FetchedSource, fetch_article_body


@dataclass(slots=True)
class ParsedItem:
    source_name: str
    source_type: str
    source_url: str
    ai_name: str
    title: str
    summary: str
    published_at: str | None
    item_url: str
    tags: list[str]


def parse_source_payload(fetched: FetchedSource) -> list[ParsedItem]:
    try:
        if fetched.source.source_type == "rss":
            return _parse_rss(fetched)
        return _parse_html_page(fetched)
    except ET.ParseError:
        return []


def _parse_rss(fetched: FetchedSource) -> list[ParsedItem]:
    root = ET.fromstring(fetched.content)
    raw_items = root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[ParsedItem] = []
    body_fetch_count = 0
    for item in raw_items:
        title = _first_text(item, ("title", "{http://www.w3.org/2005/Atom}title"))
        rss_summary = _first_text(
            item,
            (
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            ),
        )
        link = _first_link(item)
        published_at = _normalize_datetime(
            _first_text(
                item,
                (
                    "pubDate",
                    "published",
                    "updated",
                    "{http://www.w3.org/2005/Atom}published",
                    "{http://www.w3.org/2005/Atom}updated",
                ),
            )
        )
        if not title or not link:
            continue

        # 상위 3개 기사에 한해 실제 본문 추출 시도, 실패하면 RSS summary 사용
        body_text = ""
        if body_fetch_count < 3 and link.startswith("http"):
            body_text = fetch_article_body(link)
            body_fetch_count += 1

        final_summary = body_text if body_text else _clean_text(rss_summary)[:400]

        items.append(
            ParsedItem(
                source_name=fetched.source.name,
                source_type=fetched.source.source_type,
                source_url=fetched.source.url,
                ai_name=fetched.source.ai_name,
                title=_clean_text(title),
                summary=final_summary,
                published_at=published_at,
                item_url=link,
                tags=list(fetched.source.tags),
            )
        )
    return items


class _SimpleLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        self._current_href = attributes.get("href")
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = _clean_text(" ".join(self._text_parts))
        if text and self._current_href.startswith("http"):
            self.links.append((text, self._current_href))
        self._current_href = None
        self._text_parts = []


def _parse_html_page(fetched: FetchedSource) -> list[ParsedItem]:
    parser = _SimpleLinkParser()
    parser.feed(fetched.content)
    items: list[ParsedItem] = []
    seen_urls: set[str] = set()
    for text, href in parser.links:
        if href in seen_urls or len(text.split()) < 3:
            continue
        if not _looks_like_topic_title(text):
            continue
        seen_urls.add(href)
        items.append(
            ParsedItem(
                source_name=fetched.source.name,
                source_type=fetched.source.source_type,
                source_url=fetched.source.url,
                ai_name=fetched.source.ai_name,
                title=text,
                summary="",
                published_at=None,
                item_url=href,
                tags=list(fetched.source.tags),
            )
        )
    return items[:20]


def _first_text(element: ET.Element, candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        child = element.find(candidate)
        if child is not None and child.text:
            return child.text
    return ""


def _first_link(element: ET.Element) -> str:
    link = _first_text(element, ("link", "{http://www.w3.org/2005/Atom}link"))
    if link:
        return link.strip()
    atom_link = element.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        href = atom_link.attrib.get("href")
        if href:
            return href.strip()
    return ""


def _normalize_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.isoformat()


def _clean_text(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", no_tags)
    return normalized.strip()


def _looks_like_topic_title(text: str) -> bool:
    lowered = text.lower()
    keywords = ("ai", "model", "agent", "release", "launch", "update", "reasoning", "api", "tool")
    return any(keyword in lowered for keyword in keywords)
