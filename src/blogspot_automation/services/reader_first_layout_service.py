"""독자 우선 레이아웃 — 발행 HTML의 GEO/SEO 블록을 본문 뒤로 재배치한다.

문제(2026-07-02): 발행 글이 h1 → 30초 요약 → AI 인용 요약 → 업데이트 날짜 →
이 글이 도움 되는 사람 → Q&A → 관련 검색어 → 목차 → (그제서야) 본문 순서라
독자 입장에서 "글"이 아니라 SEO 블록 나열로 읽혔다.

해결: 블록 삭제 없이 순서만 바꾼다 (GEO/SGE/품질 게이트는 블록 존재 여부만
검사하므로 재배치는 안전). 재배치 후 순서:

  h1 → 커버 → 30초 요약(BLUF) → 업데이트 날짜 → 목차 → 본문 전체
  → FAQ → 관련 검색어 → 이슈 컨텍스트 → AI 인용 요약 → 검증/출처 → 해시태그

보호 파일(golden_article_preview_service.py 등)은 수정하지 않고,
파이프라인 발행 직전 단계에서 후처리로만 적용한다.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 본문 뒤로 이동할 블록 id — 이동 후에도 이 순서대로 배치된다.
_MOVABLE_BLOCK_IDS: tuple[str, ...] = (
    "INTENT_ANSWER_BLOCK",       # ❓ 자주 묻는 질문
    "PEOPLE_ALSO_ASK_BLOCK",     # 🔎 관련 검색어
    "ISSUE_CONTEXT_BLOCK",       # 🎯 이 글이 도움이 되는 사람
    "AI_CITATION_SUMMARY",       # AI 인용용 요약 (h2 없음)
)

# 이동 블록을 이 앵커 "앞"에 삽입한다 (첫 번째로 발견되는 앵커 사용).
_INSERT_ANCHORS: tuple[str, ...] = (
    '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"',
    '<section id="SOURCE_TRUST_BLOCK"',
    '<section class="related-ai-blog-box"',
    '<section class="yomi-hashtags"',
)

# 본문이 실제 존재할 때만 재배치한다 (이 마커가 없으면 원본 유지).
_BODY_MARKERS: tuple[str, ...] = ('class="yomi-lede"', 'class="ai-toc"', 'id="sec-1"')


def _extract_block(html: str, block_id: str) -> tuple[str, str]:
    """block_id 최상위 section을 제거한 html과 추출된 블록을 반환한다.

    블록 내부에 중첩 <section>이 있으면 안전하게 건너뛴다(추출 안 함).
    """
    pattern = re.compile(
        rf'[ \t]*<section\b[^>]*\bid="{re.escape(block_id)}"[^>]*>.*?</section>[ \t]*\n?',
        re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        return html, ""
    block = match.group(0)
    inner = block[block.index(">") + 1:]
    if "<section" in inner:
        # 중첩 section — 비탐욕 매칭이 잘못 잘랐을 수 있으므로 이동하지 않는다.
        return html, ""
    return html[: match.start()] + html[match.end():], block.strip("\n")


def reorder_for_reader_first(html: str) -> str:
    """GEO/SEO 블록을 본문 뒤로 이동한 HTML을 반환한다. 실패 시 원본 그대로.

    - 블록을 삭제하지 않는다 (이동만).
    - 본문 마커가 없거나 앵커를 못 찾으면 원본을 반환한다.
    """
    if not html or not any(marker in html for marker in _BODY_MARKERS):
        return html

    working = html
    moved: list[str] = []
    for block_id in _MOVABLE_BLOCK_IDS:
        working, block = _extract_block(working, block_id)
        if block:
            moved.append(block)

    if not moved:
        return html

    insert_at = -1
    for anchor in _INSERT_ANCHORS:
        idx = working.find(anchor)
        if idx != -1:
            insert_at = idx
            break

    moved_html = "\n".join(moved) + "\n"
    if insert_at == -1:
        # 앵커가 없으면 마지막 </section> 뒤에 덧붙인다.
        last_close = working.rfind("</section>")
        if last_close == -1:
            return html
        insert_at = last_close + len("</section>")

    # 재적용 시 개행이 누적되지 않도록 삽입 지점 앞 개행을 정확히 1개로 맞춘다.
    before = working[:insert_at]
    if not before.endswith("\n"):
        before += "\n"
    result = before + moved_html + working[insert_at:]

    # 안전 검증: 이동 과정에서 블록이 유실되면 원본을 반환한다.
    for block_id in _MOVABLE_BLOCK_IDS:
        if f'id="{block_id}"' in html and f'id="{block_id}"' not in result:
            logger.warning("reader_first_layout: block %s lost during reorder — keeping original", block_id)
            return html
    logger.info("reader_first_layout: moved %d GEO/SEO block(s) below body", len(moved))
    return result
