# -*- coding: utf-8 -*-
"""네이버 블로그 RSS 감지 + 모바일 본문 크롤링 서비스."""
from __future__ import annotations

import json
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

NAVER_BLOG_ID = "holyyomi"
_RSS_URL = f"https://rss.blog.naver.com/{NAVER_BLOG_ID}.xml"
_PROCESSED_PATH = Path("data/naver_processed.json")

# AI Blogspot 재작성 전용 추적 파일 (cli_naver.py와 독립)
_AI_REWRITTEN_PATH = Path("data/naver_ai_rewritten.json")

# AI 관련 포스트 판별 키워드 (제목 기준)
_AI_KEYWORDS: tuple[str, ...] = (
    "AI", "인공지능", "ChatGPT", "챗GPT", "GPT", "Claude",
    "자동화", "업무자동화", "생산성", "프롬프트", "LLM",
    "생성AI", "AI 활용", "AI도구", "AI 업무", "업무 AI",
    "Copilot", "코파일럿", "n8n", "Zapier",
)
_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


@dataclass
class NaverPost:
    title: str
    link: str
    log_no: str
    pub_date: str
    rss_excerpt: str
    full_text: str = ""


def fetch_latest_unprocessed() -> NaverPost | None:
    """RSS에서 미처리 최신 글을 찾아 전체 본문 크롤링 후 반환."""
    processed = _load_processed()
    posts = _fetch_rss()
    logger.info("네이버 RSS 글 %d개 조회, 처리 완료 %d개", len(posts), len(processed))

    for post in posts:
        if post.link in processed:
            continue
        logger.info("미처리 글 발견: %s", post.title)
        post.full_text = _fetch_full_text(post.log_no, post.title)
        if len(post.full_text) < 300:
            logger.warning("본문 추출 실패 (너무 짧음: %d자) — 스킵", len(post.full_text))
            continue
        logger.info("본문 크롤링 성공: %d자", len(post.full_text))
        return post

    logger.info("새 미처리 네이버 글 없음")
    return None


def mark_processed(post: NaverPost) -> None:
    """발행 완료 후 처리 기록 저장 (중복 방지)."""
    processed = _load_processed()
    processed[post.link] = datetime.now(timezone.utc).isoformat()
    _PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROCESSED_PATH.write_text(
        json.dumps(processed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("처리 완료 기록: %s", post.title)


def fetch_latest_ai_post_for_blogspot(
    *,
    keywords: tuple[str, ...] = _AI_KEYWORDS,
    fetch_full_text: bool = True,
) -> NaverPost | None:
    """AI 관련 Naver 포스트 중 Blogspot 재작성 미완료 최신 글을 반환한다.

    - _AI_KEYWORDS로 제목 필터링
    - _AI_REWRITTEN_PATH로 already_rewritten 체크 (cli_naver.py와 독립)
    - fetch_full_text=False면 전체 본문 크롤링 생략 (테스트/경량용)
    """
    ai_rewritten = _load_ai_rewritten()
    posts = _fetch_rss()
    logger.info(
        "NaverAI: RSS 글 %d개 조회, AI 재작성 완료 %d개",
        len(posts), len(ai_rewritten),
    )

    for post in posts:
        if post.link in ai_rewritten:
            logger.debug("NaverAI: 이미 재작성됨 — 스킵: %s", post.title[:40])
            continue
        if not _is_ai_post(post, keywords):
            logger.debug("NaverAI: AI 키워드 미포함 — 스킵: %s", post.title[:40])
            continue
        logger.info("NaverAI: AI 포스트 발견 — %s", post.title)
        if fetch_full_text:
            post.full_text = _fetch_full_text(post.log_no, post.title)
            if len(post.full_text) < 100:
                logger.warning(
                    "NaverAI: 본문 추출 실패 (%d자) — 스킵", len(post.full_text)
                )
                continue
        return post

    logger.info("NaverAI: 재작성 가능한 AI 포스트 없음")
    return None


def mark_ai_blogspot_rewritten(post: NaverPost) -> None:
    """AI Blogspot 재작성 완료 후 추적 파일에 기록한다."""
    ai_rewritten = _load_ai_rewritten()
    ai_rewritten[post.link] = {
        "rewritten_at": datetime.now(timezone.utc).isoformat(),
        "title": post.title,
        "log_no": post.log_no,
    }
    _AI_REWRITTEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _AI_REWRITTEN_PATH.write_text(
        json.dumps(ai_rewritten, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("NaverAI: Blogspot 재작성 기록: %s", post.title[:50])


# ── 내부 함수 ────────────────────────────────────────────────────────────────

def _is_ai_post(post: NaverPost, keywords: tuple[str, ...]) -> bool:
    """제목 또는 RSS excerpt에 AI 키워드가 포함되면 True."""
    combined = f"{post.title} {post.rss_excerpt}"
    return any(kw in combined for kw in keywords)


def _load_ai_rewritten() -> dict[str, object]:
    if _AI_REWRITTEN_PATH.exists():
        try:
            return json.loads(_AI_REWRITTEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _load_processed() -> dict[str, str]:
    if _PROCESSED_PATH.exists():
        try:
            return json.loads(_PROCESSED_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _fetch_rss() -> list[NaverPost]:
    req = urllib.request.Request(_RSS_URL, headers=_MOBILE_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.error("네이버 RSS 요청 실패: %s", exc)
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.error("네이버 RSS XML 파싱 실패: %s", exc)
        return []

    posts: list[NaverPost] = []
    for item in root.findall(".//item"):
        link = item.findtext("link", "").strip()
        log_no = _extract_log_no(link)
        if not log_no:
            continue
        posts.append(NaverPost(
            title=item.findtext("title", "").strip(),
            link=link,
            log_no=log_no,
            pub_date=item.findtext("pubDate", "").strip(),
            rss_excerpt=item.findtext("description", "").strip(),
        ))
    return posts


def _extract_log_no(link: str) -> str:
    m = re.search(r"/(\d{9,})", link)
    return m.group(1) if m else ""


def _fetch_full_text(log_no: str, title: str) -> str:
    url = f"https://m.blog.naver.com/{NAVER_BLOG_ID}/{log_no}"
    req = urllib.request.Request(url, headers=_MOBILE_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.error("네이버 모바일 크롤링 실패 log_no=%s: %s", log_no, exc)
        return ""
    return _extract_main_content(html, title)


def _extract_main_content(html: str, title: str) -> str:
    """네이버 모바일 블로그 HTML에서 본문 텍스트만 추출."""
    # 스크립트·스타일·JSON 제거
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # HTML 태그·엔티티 제거
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # 네비게이션 제거: 제목이 두 번 나오면 두 번째부터가 실제 본문
    short = title[:12].strip()
    if short:
        idx1 = text.find(short)
        if idx1 >= 0:
            idx2 = text.find(short, idx1 + len(short))
            start = idx2 if idx2 > idx1 else idx1
            text = text[start:]

    # 푸터 제거 (댓글·이웃추가 이하)
    for marker in ["이웃추가", "공감한 사람", "이 블로그 홈", "카테고리 이동"]:
        idx = text.find(marker)
        if 300 < idx:
            text = text[:idx]
            break

    return text.strip()
