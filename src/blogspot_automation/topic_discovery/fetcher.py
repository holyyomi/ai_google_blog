from __future__ import annotations

from dataclasses import dataclass
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from blogspot_automation.topic_discovery.sources import SourceDefinition
from blogspot_automation.utils.retry import retry_call


logger = logging.getLogger(__name__)

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_article_body(url: str, timeout: int = 10, max_chars: int = 2000) -> str:
    """기사 URL에서 본문 텍스트를 추출한다. 실패하면 빈 문자열을 반환한다."""
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(url, timeout=timeout, headers=_FETCH_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "figure"]):
            tag.decompose()

        # <article> 태그 우선 추출, 없으면 전체 <p> 태그 사용
        article_tag = soup.find("article")
        container = article_tag if article_tag else soup
        paragraphs = container.find_all("p")
        text = " ".join(
            p.get_text(separator=" ", strip=True)
            for p in paragraphs
            if len(p.get_text(strip=True)) > 30
        )
        cleaned = " ".join(text.split())
        return cleaned[:max_chars]
    except Exception as exc:
        logger.debug("fetch_article_body failed for %s: %s", url, exc)
        return ""


@dataclass(slots=True)
class FetchedSource:
    source: SourceDefinition
    content: str


def fetch_source(source: SourceDefinition, timeout_seconds: int = 15) -> FetchedSource | None:
    request = Request(
        source.url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
        },
    )
    try:
        def _fetch() -> FetchedSource:
            with urlopen(request, timeout=timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                content = response.read().decode(charset, errors="replace")
            return FetchedSource(source=source, content=content)

        return retry_call(
            operation=_fetch,
            attempts=3,
            delay_seconds=1.0,
            operation_name=f"fetch_source:{source.name}",
            logger=logger,
        )
    except (HTTPError, URLError, TimeoutError):
        return None
