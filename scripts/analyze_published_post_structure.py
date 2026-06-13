from __future__ import annotations

import json
import re
import sys
import urllib.request
from html import unescape


def visible(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def extract(pattern: str, html: str) -> list[str]:
    return [visible(match) for match in re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)]


def main() -> int:
    url = sys.argv[1]
    request = urllib.request.Request(url, headers={"User-Agent": "post-structure-audit/1.0"})
    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", errors="replace")
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        BeautifulSoup = None

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        article_node = soup.select_one("article.yomi-clean-post")
        article_found = article_node is not None
        root = article_node or soup

        def texts(selector: str) -> list[str]:
            return [" ".join(node.get_text(" ").split()) for node in root.select(selector)]

        headings = {
            "h1": texts("h1"),
            "h2": texts("h2"),
            "h3": texts("h3"),
        }
        visible_text = " ".join(root.get_text(" ").split())
        intent_qa_count = len(root.select(".intent-qa-item"))
        paa_item_count = len(root.select(".paa-item"))
        faq_card_count = len(root.select(".faq-card"))
        article = str(root)
    else:
        article_match = re.search(
            r'<article\b[^>]*class=["\'][^"\']*\byomi-clean-post\b[^"\']*["\'][^>]*>.*?</article>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        article = article_match.group(0) if article_match else html
        article_found = bool(article_match)
        headings = {
            "h1": extract(r"<h1\b[^>]*>(.*?)</h1>", article),
            "h2": extract(r"<h2\b[^>]*>(.*?)</h2>", article),
            "h3": extract(r"<h3\b[^>]*>(.*?)</h3>", article),
        }
        visible_text = visible(article)
        intent_qa_count = len(re.findall(r'class=["\'][^"\']*intent-qa-item', article, flags=re.IGNORECASE))
        paa_item_count = len(re.findall(r'class=["\'][^"\']*paa-item', article, flags=re.IGNORECASE))
        faq_card_count = len(re.findall(r'class=["\'][^"\']*faq-card', article, flags=re.IGNORECASE))
    all_heading_text = headings["h1"] + headings["h2"] + headings["h3"]
    question_headings = [text for text in all_heading_text if "?" in text or text.endswith("요") or "무엇" in text or "왜" in text]
    question_sentences = re.findall(r"[^.!?\n]{3,80}\?", visible_text)
    result = {
        "url": url,
        "article_found": article_found,
        "title": extract(r"<title\b[^>]*>(.*?)</title>", html)[:1],
        "post_title": extract(r'<h3\b[^>]*class=["\'][^"\']*post-title[^"\']*["\'][^>]*>(.*?)</h3>', html)[:1],
        "h2_count": len(headings["h2"]),
        "h3_count": len(headings["h3"]),
        "h2": headings["h2"],
        "h3": headings["h3"],
        "question_heading_count": len(question_headings),
        "question_headings": question_headings,
        "question_sentence_count": len(question_sentences),
        "intent_qa_count": intent_qa_count,
        "paa_item_count": paa_item_count,
        "faq_card_count": faq_card_count,
        "has_ai_overview_block": "AI_OVERVIEW_TARGET_ANSWER" in article,
        "has_issue_context_block": "ISSUE_CONTEXT_BLOCK" in article,
        "has_confirmed_block": "CONFIRMED_VS_CHECK_NEEDED_BLOCK" in article,
        "has_source_block": "SOURCE_TRUST_BLOCK" in article,
        "visible_length": len(visible_text),
        "bad_phrases": [
            phrase for phrase in ("재계는 지금", "화제 된 이 반응", "사람들이 본 에", "사람들이 본 의", "신청전 많이 묻는 질문", "신청 전 많이 묻는 질문")
            if phrase in visible_text
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
