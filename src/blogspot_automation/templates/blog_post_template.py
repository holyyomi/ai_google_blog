"""고품질 블로그 포스트 HTML 템플릿 — 모바일 최적화, AdSense 친화적."""
from __future__ import annotations

from datetime import datetime
from html import escape
import json
from typing import Any

from blogspot_automation.services.seo_policy import normalize_hashtags, normalize_labels, prepare_blogspot_html

_CSS = """
<style>
/* Reset & Fonts */
*{box-sizing:border-box;margin:0;padding:0}
.yomi-post{font-family:'Pretendard','Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;max-width:760px;margin:0 auto;padding:24px 20px;color:#202124;line-height:1.75;font-size:16.5px;letter-spacing:-0.01em;background:#ffffff}

/* Headings - Modern Gradient Highlights */
.yomi-post h1{font-size:1.8rem;font-weight:900;color:#111827;margin:16px 0 24px;line-height:1.35;padding-bottom:16px;border-bottom:1px solid rgba(0,0,0,0.06);background:linear-gradient(90deg, #111827 0 34px, #3b82f6 34px 72px, #8b5cf6 72px 110px) bottom left/110px 4px no-repeat;letter-spacing:-0.02em}
.yomi-post h2{font-size:1.25rem;font-weight:800;color:#111827;margin:32px 0 16px;padding-bottom:10px;border-bottom:1px solid rgba(0,0,0,0.04);background:linear-gradient(90deg, #3b82f6, #10b981) bottom left/54px 3px no-repeat;letter-spacing:-0.01em}
.yomi-post h3{font-size:1.1rem;font-weight:750;color:#1f2937;margin:22px 0 10px}
.yomi-post p{margin-bottom:18px;color:#374151;line-height:1.8}
.yomi-post strong{color:#111827;font-weight:750;background:linear-gradient(transparent 60%, rgba(59,130,246,0.15) 60%);padding:0 2px}
.yomi-post a{color:#2563eb;text-decoration:none;font-weight:600;transition:all 0.2s ease}
.yomi-post a:hover{color:#1d4ed8;text-decoration:underline;text-underline-offset:4px}

/* Post Meta (Sleek Badges) */
.post-meta{display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.meta-tag{display:inline-flex;align-items:center;padding:4px 12px;border-radius:20px;font-size:0.75rem;font-weight:700;letter-spacing:0.02em;text-transform:uppercase}
.meta-category{background:linear-gradient(135deg, #eff6ff, #dbeafe);color:#1e40af;border:1px solid rgba(59,130,246,0.2)}
.meta-type{background:linear-gradient(135deg, #f0fdf4, #dcfce7);color:#166534;border:1px solid rgba(34,197,94,0.2)}
.meta-date{font-size:0.8rem;color:#6b7280;margin-left:auto;font-weight:500}

/* Summary Card (Dark Premium Glassmorphism) */
.summary-card{background:linear-gradient(145deg, #111827, #1f2937);color:#fff;border-radius:16px;padding:24px;margin:24px 0;box-shadow:0 12px 32px -4px rgba(15,23,42,0.2), inset 0 1px 0 rgba(255,255,255,0.1);position:relative;overflow:hidden}
.summary-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899)}
.summary-card table{width:100%;border-collapse:separate;border-spacing:0}
.summary-card td{padding:12px 8px;border-bottom:1px solid rgba(255,255,255,0.1);vertical-align:top}
.summary-card td:first-child{font-size:0.85rem;color:#94a3b8;white-space:nowrap;width:35%;padding-right:16px;font-weight:600;letter-spacing:0.02em}
.summary-card td:last-child{font-weight:700;font-size:0.98rem;color:#f8fafc}
.summary-card tr:last-child td{border-bottom:none;padding-bottom:0}

/* Info Boxes (Soft UI) */
.info-box{position:relative;background:#f8fafc;border:1px solid rgba(0,0,0,0.04);padding:20px 24px;margin:22px 0;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.02);overflow:hidden;transition:transform 0.3s ease}
.info-box:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,0.04)}
.info-box::before{content:'';position:absolute;top:0;left:0;bottom:0;width:6px}
.info-box.success{background:linear-gradient(to right, #f0fdf4, #ffffff);border-color:rgba(34,197,94,0.15)}
.info-box.success::before{background:#22c55e}
.info-box.warning{background:linear-gradient(to right, #fffbeb, #ffffff);border-color:rgba(245,158,11,0.15)}
.info-box.warning::before{background:#f59e0b}
.info-box.danger{background:linear-gradient(to right, #fef2f2, #ffffff);border-color:rgba(239,68,68,0.15)}
.info-box.danger::before{background:#ef4444}
.info-box-title{font-weight:800;font-size:1rem;margin-bottom:8px;display:flex;align-items:center;gap:8px;letter-spacing:-0.01em;color:#111827}

/* Compare Table (Modern Clean) */
.compare-table{overflow-x:auto;margin:24px 0;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,0.04);border:1px solid rgba(0,0,0,0.05)}
.compare-table table{width:100%;border-collapse:collapse;min-width:360px;background:#fff}
.compare-table th{background:#f8fafc;color:#334155;padding:14px 16px;text-align:left;font-size:0.85rem;font-weight:800;border-bottom:2px solid rgba(0,0,0,0.05);text-transform:uppercase;letter-spacing:0.03em}
.compare-table td{padding:14px 16px;border-bottom:1px solid rgba(0,0,0,0.03);font-size:0.95rem;vertical-align:top;color:#1f2937}
.compare-table tr:hover td{background:#f1f5f9;transition:background 0.2s}
.compare-table tr:last-child td{border-bottom:none}

/* Steps (Dynamic Path) */
.steps{list-style:none;padding:0;margin:24px 0;counter-reset:step}
.steps li{position:relative;display:flex;align-items:flex-start;gap:16px;margin-bottom:16px;padding:20px;background:#ffffff;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.03);border:1px solid rgba(0,0,0,0.04);counter-increment:step;transition:all 0.3s ease}
.steps li:hover{transform:translateX(4px);box-shadow:0 6px 16px rgba(0,0,0,0.06);border-color:rgba(59,130,246,0.2)}
.steps li::before{content:counter(step);background:linear-gradient(135deg, #3b82f6, #2563eb);color:#fff;min-width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:0.9rem;flex-shrink:0;box-shadow:0 4px 10px rgba(59,130,246,0.3)}
.steps li .step-title{font-weight:800;color:#111827;display:block;margin-bottom:6px;font-size:1.05rem}
.steps li .step-desc{font-size:0.95rem;color:#4b5563;line-height:1.6}

/* FAQ Section (Accordion Style) */
.faq-section{margin:28px 0;display:flex;flex-direction:column;gap:12px}
.faq-item{background:#ffffff;border:1px solid rgba(0,0,0,0.05);border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.02);overflow:hidden;transition:all 0.3s}
.faq-item:hover{border-color:rgba(59,130,246,0.2);box-shadow:0 4px 12px rgba(59,130,246,0.05)}
.faq-q{background:#f8fafc;padding:16px 20px;font-weight:800;color:#1e293b;font-size:0.98rem;display:flex;align-items:center;gap:12px;cursor:pointer}
.faq-q::before{content:"Q";background:#3b82f6;color:#fff;min-width:24px;height:24px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:900}
.faq-a{padding:16px 20px 20px 56px;font-size:0.95rem;color:#334155;border-top:1px solid rgba(0,0,0,0.03);line-height:1.7}

/* Deadline/Action Box (Pulsing Highlight) */
.deadline-box{position:relative;background:linear-gradient(135deg, #fffbeb, #fef3c7);border:none;border-radius:16px;padding:28px 24px;margin:32px 0;text-align:center;box-shadow:0 8px 24px rgba(245,158,11,0.15)}
.deadline-box::after{content:'';position:absolute;top:0;left:0;right:0;bottom:0;border-radius:16px;border:2px dashed rgba(245,158,11,0.3);pointer-events:none}
.deadline-box .dl-icon{font-size:2.5rem;display:block;margin-bottom:12px;animation:bounce 2s infinite}
@keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
.deadline-box .dl-title{font-size:1.3rem;font-weight:900;display:block;margin-bottom:8px;color:#92400e;letter-spacing:-0.01em}
.deadline-box .dl-desc{font-size:0.95rem;color:#52525b;line-height:1.7;font-weight:500}

/* Checklist (Custom Icons) */
.checklist{list-style:none;padding:0;margin:20px 0;background:#f8fafc;border-radius:12px;padding:16px 24px;border:1px solid rgba(0,0,0,0.03)}
.checklist li{padding:10px 0 10px 32px;position:relative;border-bottom:1px solid rgba(0,0,0,0.04);font-size:0.95rem;color:#334155;font-weight:500}
.checklist li::before{content:"✓";position:absolute;left:0;top:10px;font-size:1rem;font-weight:900;color:#10b981;background:rgba(16,185,129,0.1);width:22px;height:22px;display:flex;align-items:center;justify-content:center;border-radius:50%}
.checklist li:last-child{border-bottom:none}

/* Tags & Badges */
.tag-list{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0}
.tag{display:inline-block;padding:6px 14px;background:#f1f5f9;color:#475569;border-radius:999px;font-size:0.8rem;font-weight:700;transition:all 0.2s}
.tag:hover{background:#e2e8f0;color:#1e293b}

/* Source Note */
.source-note{font-size:0.8rem;color:#94a3b8;margin-top:32px;padding-top:16px;border-top:1px solid rgba(0,0,0,0.06);line-height:1.6;text-align:center}

/* Responsive Overrides */
@media(max-width:640px){
  .yomi-post{padding:16px 12px;font-size:15.5px}
  .yomi-post h1{font-size:1.5rem}
  .summary-card{padding:20px 16px;border-radius:12px}
  .summary-card td:first-child{width:100%;display:block;padding-bottom:4px;color:#cbd5e1}
  .summary-card td:last-child{display:block;padding-top:0}
  .info-box{padding:16px}
  .steps li{padding:16px;flex-direction:column;gap:12px}
  .steps li::before{margin-bottom:4px}
  .faq-q{padding:14px 16px}
  .faq-a{padding:12px 16px 16px 16px;border-top:none}
}
</style>
"""


def render_full_post(
    *,
    title: str,
    content_html: str,
    category: str = "AI활용",
    content_type: str = "",
    labels: list[str] | None = None,
    hashtags: list[str] | None = None,
    meta_description: str = "",
    today: str = "",
    schema_faq: list[dict] | None = None,
) -> str:
    """LLM이 생성한 content_html을 완성된 블로그 포스트 HTML로 감싼다."""
    today = today or datetime.now().strftime("%Y.%m.%d")
    title_esc = escape(title)
    meta_desc_esc = escape(meta_description or title[:120])

    type_label = _TYPE_LABEL.get(content_type, content_type or "이슈")
    category_esc = escape(category or "AI활용")

    normalized_labels = normalize_labels(labels or [])

    labels_html = ""
    if normalized_labels:
        tags = "".join(f'<span class="tag">{escape(str(l))}</span>' for l in normalized_labels)
        labels_html = f'<div class="tag-list">{tags}</div>'

    hashtags_html = ""
    if hashtags:
        ht = " ".join(normalize_hashtags(hashtags))
        hashtags_html = f'<p class="source-note">{escape(ht)}</p>'

    # 하단 기준일·면책 문구는 발행 시 SOURCE_TRUST_BLOCK(yomi-source)이 주제별로
    # 더 자세히("...기준", "정책에 따라 바뀔 수 있으니 공식 페이지 확인") 넣어주므로
    # 여기서 별도 source-note를 붙이면 같은 안내가 두 번 반복된다 → 붙이지 않는다.

    faq_ld_script = ""
    if schema_faq:
        faq_ld = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["Q"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["A"]},
                }
                for item in schema_faq[:5]
                if item.get("Q") and item.get("A")
            ],
        }
        faq_ld_script = (
            f'<script type="application/ld+json">'
            f'{json.dumps(faq_ld, ensure_ascii=False)}'
            f'</script>'
        )

    article_ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": meta_description or title,
        "datePublished": datetime.now().strftime("%Y-%m-%d"),
        "dateModified": datetime.now().strftime("%Y-%m-%d"),
        "author": {"@type": "Person", "name": "요미"},
        "mainEntityOfPage": {"@type": "WebPage"},
        "keywords": ", ".join(normalized_labels),
    }
    article_ld_script = (
        f'<script type="application/ld+json">'
        f'{json.dumps(article_ld, ensure_ascii=False)}'
        f'</script>'
    )

    return prepare_blogspot_html(f"""<meta name="description" content="{meta_desc_esc}">
{_CSS}
{article_ld_script}
{faq_ld_script}
<article class="yomi-clean-post">
  <div class="post-meta">
    <span class="meta-tag meta-category">{category_esc}</span>
    <span class="meta-tag meta-type">유형: {escape(type_label)}</span>
    <span class="meta-date">기준일: {today}</span>
  </div>
  <h1>{title_esc}</h1>
  <div class="post-content">
{content_html}
  </div>
{labels_html}
{hashtags_html}
</article>""")


_TYPE_LABEL: dict[str, str] = {
    "platform_change": "platform_change",
    "money_checklist": "생활비 체크",
    "tax_refund": "세금·환급",
    "policy_benefit": "정책·지원금",
    "viral_issue_decode": "이슈 분석",
    "ai_work_tip": "AI 활용",
    "consumer_warning": "소비자 주의",
    "general_life": "생활 정보",
    "digital_survival": "디지털 생존",
}
