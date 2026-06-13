from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from html import unescape
from urllib.request import Request, urlopen

from blogspot_automation.services.answer_engine_policy import answer_engine_coverage
from blogspot_automation.services.cover_image_policy import cover_image_coverage
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.news_focus_policy import evaluate_news_focus
from blogspot_automation.services.title_integrity_policy import audit_title_integrity
from blogspot_automation.utils.html_meta import extract_meta_description


@dataclass(frozen=True, slots=True)
class PostPublishAuditResult:
    url: str
    passed: bool
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    meta_description_present: bool
    canonical_self_referencing: bool
    answer_engine_ready: bool
    cover_image_present: bool
    expected_title: str
    actual_title: str
    title_matches_expected: bool
    temporary_slug_title_absent: bool
    permalink_slug_matches: bool
    content_quality_ready: bool
    expected_labels: tuple[str, ...]
    actual_labels: tuple[str, ...]
    labels_valid: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def fetch_and_audit_post(
    *,
    url: str,
    require_cover_image: bool = False,
    expected_title: str = "",
    expected_permalink_slug: str = "",
    expected_labels: list[str] | tuple[str, ...] | None = None,
    content_type: str = "",
    topic_group: str = "",
    timeout: int = 30,
) -> PostPublishAuditResult:
    request = Request(url, headers={"User-Agent": "blogspot-post-publish-audit/1.0"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    return audit_post_html(
        url=url,
        html=html,
        require_cover_image=require_cover_image,
        expected_title=expected_title,
        expected_permalink_slug=expected_permalink_slug,
        expected_labels=expected_labels,
        content_type=content_type,
        topic_group=topic_group,
    )


def audit_post_html(
    *,
    url: str,
    html: str,
    require_cover_image: bool = False,
    expected_title: str = "",
    expected_permalink_slug: str = "",
    expected_labels: list[str] | tuple[str, ...] | None = None,
    content_type: str = "",
    topic_group: str = "",
) -> PostPublishAuditResult:
    content = html or ""
    issues: list[str] = []
    warnings: list[str] = []
    visible_text = _visible_text(content)

    slug = _slug_from_url(url)
    if _is_weak_slug(slug):
        issues.append("weak_permalink_slug")
    permalink_slug_matches = True
    expected_slug = (expected_permalink_slug or "").strip()
    if expected_slug:
        from blogspot_automation.services.seo_policy import url_matches_permalink_slug

        permalink_slug_matches = url_matches_permalink_slug(url, expected_slug)
        if not permalink_slug_matches:
            issues.append("permalink_slug_mismatch")

    head = _head_html(content)
    meta_description_present = bool(extract_meta_description(head))
    # Blogger renders a head <meta name="description"> only when the blog-level
    # "search description" dashboard toggle is enabled. Our publish path already
    # sends searchDescription/metaDescription via the API, so a missing head meta
    # is a Blogger config issue — NOT grounds to delete a live post. Keep advisory.
    if not meta_description_present:
        warnings.append("missing_meta_description")
        if extract_meta_description(content):
            warnings.append("body_only_meta_description")
    elif _body_meta_description_present(content):
        warnings.append("body_only_meta_description")
    canonical_self_referencing = _canonical_self_referencing(url=url, html=content)
    if not canonical_self_referencing:
        issues.append("canonical_not_self_referencing")
    og_description = _og_description(head)
    if not og_description:
        warnings.append("missing_og_description")
    elif expected_title and not _description_matches_title(og_description, expected_title):
        issues.append("og_description_not_post_specific")

    coverage = answer_engine_coverage(content)
    answer_engine_ready = (
        bool(coverage.get("ai_overview_target_answer_present"))
        and bool(coverage.get("intent_answer_present"))
        and int(coverage.get("intent_qa_count") or 0) >= 3
        and bool(coverage.get("people_also_ask_present"))
        and int(coverage.get("people_also_ask_count") or 0) >= 5
        and bool(coverage.get("confirmed_vs_check_needed_present"))
        and bool(coverage.get("source_trust_block_present"))
        and bool(coverage.get("faqpage_json_ld_present"))
        and bool(coverage.get("blogposting_json_ld_present"))
    )
    if not answer_engine_ready:
        issues.append("answer_engine_blocks_missing_or_incomplete")

    focus = evaluate_news_focus(topic=slug.replace("-", " "), raw={})
    if not focus.allowed:
        issues.append("ai_topic_leaked_to_news_blog")

    actual_title = _extract_actual_title(content)
    actual_title_integrity = audit_title_integrity(
        actual_title,
        content_type=content_type,
        topic_group=topic_group,
    )
    issues.extend(f"published_title_integrity:{issue}" for issue in actual_title_integrity.get("blocking_issues", []))
    expected_title_clean = _normalize_text(expected_title)
    title_matches_expected = True
    if expected_title_clean:
        title_matches_expected = expected_title_clean in _normalize_text(visible_text)
        if not title_matches_expected:
            issues.append("published_title_mismatch")

    temporary_slug_title_absent = True
    if expected_slug:
        temporary_title = expected_slug.replace("-", " ")
        temporary_slug_title_absent = _normalize_text(temporary_title) not in _normalize_text(visible_text)
        if not temporary_slug_title_absent:
            issues.append("temporary_permalink_title_visible")

    image = cover_image_coverage(content)
    cover_image_present = bool(image.get("cover_image_present"))
    if require_cover_image and not cover_image_present:
        issues.append("missing_cover_image")
    elif not cover_image_present:
        warnings.append("cover_image_missing_optional")

    article_scope = _extract_post_article_html(content)
    content_quality = audit_final_html_quality(
        article_scope,
        topic=expected_title or slug.replace("-", " "),
        content_type=content_type,
        topic_group=topic_group,
    )
    issues.extend(str(issue) for issue in content_quality.get("issues", []))
    warnings.extend(str(warning) for warning in content_quality.get("warnings", []))
    content_quality_ready = not content_quality.get("issues")

    actual_labels = tuple(_extract_blogger_labels(content))
    normalized_expected_labels = tuple(
        " ".join(str(label or "").split()).strip()
        for label in (expected_labels or ())
        if " ".join(str(label or "").split()).strip()
    )
    label_issues = _label_issues(actual_labels=actual_labels, expected_labels=normalized_expected_labels)
    issues.extend(label_issues)
    labels_valid = not label_issues

    return PostPublishAuditResult(
        url=url,
        passed=not issues,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
        meta_description_present=meta_description_present,
        canonical_self_referencing=canonical_self_referencing,
        answer_engine_ready=answer_engine_ready,
        cover_image_present=cover_image_present,
        expected_title=expected_title,
        actual_title=actual_title,
        title_matches_expected=title_matches_expected,
        temporary_slug_title_absent=temporary_slug_title_absent,
        permalink_slug_matches=permalink_slug_matches,
        content_quality_ready=content_quality_ready,
        expected_labels=normalized_expected_labels,
        actual_labels=actual_labels,
        labels_valid=labels_valid,
    )


def _canonical_self_referencing(*, url: str, html: str) -> bool:
    match = re.search(
        r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)[\"']|"
        r"<link\b[^>]*href=[\"']([^\"']+)[\"'][^>]*rel=[\"']canonical[\"']",
        html or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    canonical = (match.group(1) or match.group(2) or "").strip().rstrip("/")
    return canonical == (url or "").strip().rstrip("/")


def _head_html(html: str) -> str:
    match = re.search(r"<head\b[^>]*>(.*?)</head>", html or "", flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _extract_post_article_html(html: str) -> str:
    for pattern in (
        r'<article\b[^>]*class=["\'][^"\']*\byomi-clean-post\b[^"\']*["\'][^>]*>.*?</article>',
        r'<article\b[^>]*>.*?</article>',
        r'<div\b[^>]*class=["\'][^"\']*\bpost-body\b[^"\']*["\'][^>]*>.*?</div>',
    ):
        match = re.search(pattern, html or "", flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(0)
    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", html or "", flags=re.IGNORECASE | re.DOTALL)
    return body_match.group(1) if body_match else (html or "")


def _body_meta_description_present(html: str) -> bool:
    after_head = re.sub(r"^.*?</head>", "", html or "", count=1, flags=re.IGNORECASE | re.DOTALL)
    return bool(
        re.search(
            r'<meta\b(?=[^>]*\bname\s*=\s*["\']description["\'])',
            after_head,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _extract_blogger_labels(html: str) -> list[str]:
    labels: list[str] = []
    tag_pattern = re.compile(
        r'<a\b(?=[^>]*\brel=["\']tag["\'])[^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in tag_pattern.finditer(html or ""):
        text = _normalize_text(_strip_tags(match.group(1)))
        if text and text not in labels:
            labels.append(text)
    return labels


def _label_issues(*, actual_labels: tuple[str, ...], expected_labels: tuple[str, ...]) -> list[str]:
    issues: list[str] = []
    if expected_labels and not actual_labels:
        issues.append("published_labels_missing")
    if any(_looks_mojibake(label) for label in actual_labels):
        issues.append("published_labels_mojibake")
    if expected_labels and actual_labels:
        missing = [label for label in expected_labels if label not in actual_labels]
        if missing:
            issues.append("published_labels_do_not_match_expected")
    return issues


def _looks_mojibake(value: str) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if "\ufffd" in text:
        return True
    if re.fullmatch(r"\?{2,}", text):
        return True
    return len(re.findall(r"[ÃÂìíîïêëð]", text)) >= 2


def _og_description(head_html: str) -> str:
    match = re.search(
        r"<meta\b(?=[^>]*property=[\"']og:description[\"'])(?=[^>]*content=[\"']([^\"']+)[\"'])[^>]*>",
        head_html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return unescape(match.group(1)).strip() if match else ""


def _description_matches_title(description: str, title: str) -> bool:
    title_terms = [
        term
        for term in re.findall(r"[가-힣A-Za-z0-9]+", title or "")
        if len(term) >= 2 and term not in {"오늘", "이슈", "핵심", "정리", "먼저", "가지"}
    ]
    if not title_terms:
        return True
    matched = sum(1 for term in title_terms[:6] if term in description)
    return matched >= min(2, len(title_terms))


def _slug_from_url(url: str) -> str:
    path = (url or "").split("?", 1)[0].rstrip("/")
    return re.sub(r"\.html$", "", path.rsplit("/", 1)[-1], flags=re.IGNORECASE)


def _is_weak_slug(slug: str) -> bool:
    return bool(
        re.fullmatch(r"blog-post(?:_\d+)?", slug or "")
        or re.fullmatch(r"\d+(?:[-_]\d+)*", slug or "")
        or len(slug or "") < 8
    )


def _extract_actual_title(html: str) -> str:
    for pattern in (
        r"<h3\b[^>]*class=[\"'][^\"']*post-title[^\"']*[\"'][^>]*>(.*?)</h3>",
        r"<h1\b[^>]*class=[\"'][^\"']*post-title[^\"']*[\"'][^>]*>(.*?)</h1>",
        r"<title\b[^>]*>(.*?)</title>",
        r"<h1\b[^>]*>(.*?)</h1>",
    ):
        match = re.search(pattern, html or "", flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _normalize_text(_strip_tags(match.group(1)))
    return ""


def _visible_text(html: str) -> str:
    content = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    return _normalize_text(_strip_tags(content))


def _strip_tags(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", value or ""))


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()
