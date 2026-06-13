"""고품질 블로그 포스트 HTML 템플릿 — 모바일 최적화, AdSense 친화적."""
from __future__ import annotations

from datetime import datetime
from html import escape
import json
from typing import Any

from blogspot_automation.services.seo_policy import normalize_hashtags, normalize_labels, prepare_blogspot_html

_CSS = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
.yomi-post{font-family:'Pretendard','Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;max-width:744px;margin:0 auto;padding:20px 16px;color:#172026;line-height:1.8;font-size:16px;letter-spacing:0}
.yomi-post h1{font-size:1.6rem;font-weight:850;color:#111827;margin:12px 0 20px;line-height:1.35;padding-bottom:14px;border-bottom:1px solid #dbe3ee;background:linear-gradient(90deg,#111827 0 34px,#00a3a3 34px 72px,#f59e0b 72px 108px) bottom left/108px 4px no-repeat}
.yomi-post h2{font-size:1.15rem;font-weight:800;color:#111827;margin:28px 0 12px;padding-bottom:8px;border-bottom:1px solid #dbe3ee;background:linear-gradient(90deg,#00a3a3,#84cc16) bottom left/48px 3px no-repeat}
.yomi-post h3{font-size:1.0rem;font-weight:700;color:#374151;margin:18px 0 8px}
.yomi-post p{margin-bottom:14px;color:#374151}
.yomi-post strong{color:#111827}
.yomi-post a{color:#0f766e;text-decoration:none}
.yomi-post a:hover{text-decoration:underline}

/* 포스트 헤더 메타 */
.post-meta{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.meta-tag{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.78rem;font-weight:600}
.meta-category{background:#f4fffc;color:#0f766e;border:1px solid #bcebe1}
.meta-type{background:#f7fee7;color:#3f6212;border:1px solid #d9f99d}
.meta-date{font-size:0.8rem;color:#9ca3af;margin-left:auto}

/* 핵심 요약 카드 (블루 그라디언트) */
.summary-card{background:#111827;color:#fff;border-radius:8px;padding:22px 20px;margin:20px 0;box-shadow:0 10px 24px rgba(15,23,42,.16)}
.summary-card table{width:100%;border-collapse:collapse}
.summary-card td{padding:9px 6px;border-bottom:1px solid rgba(255,255,255,.18);vertical-align:top}
.summary-card td:first-child{font-size:.82rem;opacity:.8;white-space:nowrap;width:38%;padding-right:14px}
.summary-card td:last-child{font-weight:700;font-size:.95rem}
.summary-card tr:last-child td{border-bottom:none}

/* 정보 박스 */
.info-box{border:1px solid #bcebe1;border-left:6px solid #00a3a3;background:#f4fffc;padding:16px 18px;margin:18px 0;border-radius:8px}
.info-box.warning{border-color:#f59e0b;background:#fffbeb}
.info-box.success{border-color:#22c55e;background:#f0fdf4}
.info-box.danger{border-color:#ef4444;background:#fef2f2}
.info-box-title{font-weight:700;font-size:.9rem;margin-bottom:7px;display:flex;align-items:center;gap:6px}

/* 비교 표 */
.compare-table{overflow-x:auto;margin:18px 0;border-radius:8px;box-shadow:0 8px 20px rgba(15,23,42,.06)}
.compare-table table{width:100%;border-collapse:collapse;min-width:320px}
.compare-table th{background:#111827;color:#fff;padding:12px 14px;text-align:left;font-size:.88rem;font-weight:800}
.compare-table th:first-child{border-radius:8px 0 0 0}
.compare-table th:last-child{border-radius:0 8px 0 0}
.compare-table td{padding:11px 14px;border-bottom:1px solid #f0f0f0;font-size:.9rem;vertical-align:top}
.compare-table tr:nth-child(even) td{background:#f9fafb}
.compare-table .badge-yes{color:#166534;font-weight:700}
.compare-table .badge-no{color:#dc2626;font-weight:700}

/* 단계별 (Steps) */
.steps{list-style:none;padding:0;margin:18px 0;counter-reset:step}
.steps li{display:flex;align-items:flex-start;gap:14px;margin-bottom:14px;padding:16px;background:#fff;border-radius:8px;border:1px solid #dbe3ee;border-left:6px solid #00a3a3;counter-increment:step}
.steps li::before{content:counter(step);background:#111827;color:#fff;min-width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:.85rem;flex-shrink:0;margin-top:1px}
.steps li .step-title{font-weight:800;color:#111827;display:block;margin-bottom:5px;font-size:.95rem}
.steps li .step-desc{font-size:.88rem;color:#6b7280;line-height:1.6}

/* FAQ */
.faq-section{margin:24px 0}
.faq-item{border:1px solid #dbe3ee;border-radius:8px;margin-bottom:12px;overflow:hidden}
.faq-q{background:#f8fafc;padding:14px 16px;font-weight:800;color:#111827;font-size:.93rem;display:flex;align-items:flex-start;gap:8px}
.faq-q::before{content:"Q";background:#00a3a3;color:#fff;min-width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:800;flex-shrink:0;margin-top:1px}
.faq-a{padding:14px 16px;font-size:.9rem;color:#374151;border-top:1px solid #f0f0f0;display:flex;align-items:flex-start;gap:8px}
.faq-a::before{content:"A";background:#84cc16;color:#111827;min-width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:900;flex-shrink:0;margin-top:1px}

/* 마감/행동 촉구 박스 — 배경색 없음, 테두리+아이콘으로 강조 */
.deadline-box{background:#fffaf2;border:2px solid #f59e0b;border-radius:8px;padding:22px 24px;margin:24px 0;text-align:center}
.deadline-box .dl-icon{font-size:2rem;display:block;margin-bottom:8px}
.deadline-box .dl-title{font-size:1.2rem;font-weight:800;display:block;margin-bottom:6px;color:#92400e}
.deadline-box .dl-desc{font-size:.9rem;color:#374151;line-height:1.7}

/* 체크리스트 */
.checklist{list-style:none;padding:0;margin:14px 0}
.checklist li{padding:9px 0 9px 32px;position:relative;border-bottom:1px dashed #e5e7eb;font-size:.92rem;color:#374151}
.checklist li::before{content:"✅";position:absolute;left:0;font-size:1rem}
.checklist li:last-child{border-bottom:none}

/* 목차 */
.toc{background:#fbfdff;border:1px solid #dbe3ee;border-radius:8px;padding:16px 20px;margin:20px 0}
.toc-title{font-weight:700;font-size:.88rem;color:#6b7280;margin-bottom:10px;text-transform:uppercase;letter-spacing:.05em}
.toc ol{padding-left:20px;margin:0}
.toc li{margin-bottom:6px;font-size:.9rem}
.toc a{color:#0f766e}

/* 숫자 강조 */
.big-number{font-size:2.2rem;font-weight:900;color:#0f766e;line-height:1.1}
.big-number-unit{font-size:1rem;color:#6b7280;font-weight:400;margin-left:4px}

/* 카드 그리드 */
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0}
.card{background:#fff;border:1px solid #dbe3ee;border-radius:8px;padding:16px;box-shadow:0 8px 20px rgba(15,23,42,.05)}
.card-icon{font-size:1.8rem;margin-bottom:8px;display:block}
.card-title{font-weight:800;color:#111827;font-size:.92rem;margin-bottom:5px}
.card-desc{font-size:.85rem;color:#6b7280}

/* CTA 버튼 */
.cta-button{display:block;background:#111827;color:#fff !important;text-align:center;padding:16px;border-radius:8px;font-weight:850;font-size:1.05rem;margin:14px 0;text-decoration:none !important;border:none;cursor:pointer;box-shadow:0 8px 20px rgba(15,23,42,.16)}
.cta-button:hover{background:#0f766e;text-decoration:none}

/* 관련 글 */
.related-posts{margin:32px 0 16px;padding:20px;background:#fbfdff;border-radius:8px;border:1px solid #dbe3ee}
.related-posts h3{font-size:.95rem;color:#374151;margin-bottom:12px;font-weight:700}
.related-item{display:flex;align-items:center;padding:9px 0;border-bottom:1px solid #e5e7eb;gap:10px;font-size:.9rem;color:#374151;text-decoration:none}
.related-item:last-child{border-bottom:none}
.related-item::before{content:"→";color:#00a3a3;font-weight:800;flex-shrink:0}
.related-item:hover{color:#0f766e}

/* 태그 */
.tag-list{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0}
.tag{display:inline-block;padding:4px 12px;background:#f4fffc;color:#0f766e;border:1px solid #bcebe1;border-radius:999px;font-size:.78rem;font-weight:800}

/* 네이버 블로그 CTA */
.naver-cta{display:flex;align-items:center;gap:16px;background:#f7fee7;border:1.5px solid #d9f99d;border-radius:8px;padding:18px 20px;margin:28px 0 8px;text-decoration:none;color:inherit}
.naver-cta:hover{background:#dcfce7}
.naver-cta-icon{font-size:2rem;flex-shrink:0;line-height:1}
.naver-cta-body{flex:1;min-width:0}
.naver-cta-title{font-weight:800;font-size:.98rem;color:#15803d;display:block;margin-bottom:3px}
.naver-cta-desc{font-size:.83rem;color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.naver-cta-btn{flex-shrink:0;background:#03c75a;color:#fff !important;padding:9px 16px;border-radius:20px;font-size:.82rem;font-weight:700;text-decoration:none;white-space:nowrap}
.naver-cta-btn:hover{background:#02a44a}
@media(max-width:600px){.naver-cta{flex-wrap:wrap;gap:10px}.naver-cta-btn{width:100%;text-align:center;padding:10px}}

/* 출처 / 업데이트 노트 */
.source-note{font-size:.78rem;color:#9ca3af;margin-top:28px;padding-top:14px;border-top:1px solid #e5e7eb;line-height:1.6}

/* 하이라이트 텍스트 */
.hl-blue{color:#0f766e;font-weight:800}
.hl-red{color:#dc2626;font-weight:700}
.hl-green{color:#16a34a;font-weight:700}

/* 모바일 반응형 */
@media(max-width:600px){
  .yomi-post{padding:14px 12px;font-size:15px}
  .yomi-post h1{font-size:1.3rem}
  .summary-card{padding:16px}
  .compare-table th,.compare-table td{padding:9px 10px;font-size:.85rem}
  .steps li{padding:13px}
  .card-grid{grid-template-columns:1fr 1fr}
  .deadline-box{padding:18px 16px}
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

    source_note = (
        f'<p class="source-note">'
        f'이 글은 {today} 기준으로 작성됐습니다. '
        f'정책·서비스·가격 등은 변경될 수 있으니 최신 공식 안내를 확인하세요.'
        f'</p>'
    )

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
<div class="yomi-post">
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
{source_note}
</div>""")


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
