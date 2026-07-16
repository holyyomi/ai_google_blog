from __future__ import annotations

import re
from hashlib import sha1
from html import escape, unescape
import os
from urllib.parse import unquote, urlsplit

from blogspot_automation.services.publish_history_service import PublishHistoryService
from blogspot_automation.services.title_integrity_policy import audit_title_integrity

MAX_BLOGSPOT_LABELS = 5
# 본문 해시태그 적정 개수: 핵심 키워드 + 인물/기관 + 주제군 + 롱테일 1개.
# 5개 이상은 네이버/다음에서 스팸 신호가 될 수 있어 4로 캡.
MAX_CONTENT_HASHTAGS = 4
MAX_PERMALINK_SLUG_LENGTH = 48

BLOGSPOT_HOME_URL = os.getenv("BLOGSPOT_HOME_URL", "https://holyyomiai.blogspot.com/")
BLOGSPOT_HOST = urlsplit(BLOGSPOT_HOME_URL).netloc or "holyyomiai.blogspot.com"
DEFAULT_BLOGSPOT_LABELS = ("AI활용", "업무자동화", "AI도구")
DEFAULT_INTERNAL_LINKS: tuple[tuple[str, str], ...] = (
    ("AI 업무 자동화 최신 글 보기", BLOGSPOT_HOME_URL),
    ("AI 도구 비교 글 모아보기", f"{BLOGSPOT_HOME_URL.rstrip('/')}/search/label/AI%EB%8F%84%EA%B5%AC"),
    ("프롬프트 실전 글 모아보기", f"{BLOGSPOT_HOME_URL.rstrip('/')}/search/label/%ED%94%84%EB%A1%AC%ED%94%84%ED%8A%B8"),
)
YOMI_CLEAN_ARTICLE_STYLE = """<style>
/* ── 디자인 시스템: 잉크/그레이 중립 + 글당 악센트 1색(--a1) + 경고 1색만 사용 ──
   모든 섹션은 동일한 카드 규격(테두리·라운드·패딩·간격)을 쓴다. 박스 안/밖이
   섞이거나 섹션마다 색이 다른 느낌을 없애기 위한 통일 규칙. */
.yomi-clean-post{--a1:#0f766e;--ink:#1c2430;--body:#3b4657;--muted:#69748a;--line:#e4e9f1;--soft:#f6f8fb;max-width:744px;margin:0 auto;padding:10px 0 42px;font-family:'Pretendard Variable',Pretendard,'Noto Sans KR',-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:var(--ink);line-height:1.84;font-size:17px;letter-spacing:0;word-break:keep-all;overflow-wrap:anywhere}
.yomi-clean-post *{box-sizing:border-box;max-width:100%}
.yomi-clean-post h1{font-size:1.74rem;line-height:1.32;margin:6px 0 24px;color:var(--ink);font-weight:800;padding:0 0 16px;border-bottom:1px solid var(--line);background:linear-gradient(var(--a1),var(--a1)) bottom left/64px 3px no-repeat}
.yomi-clean-post h2{font-size:1.26rem;line-height:1.42;margin:42px 0 16px;color:var(--ink);font-weight:800;padding:0 0 10px;border-bottom:1px solid var(--line);background:linear-gradient(var(--a1),var(--a1)) bottom left/40px 3px no-repeat}
.yomi-clean-post h3{font-size:1.04rem;line-height:1.48;margin:18px 0 8px;color:var(--ink);font-weight:750}
.yomi-clean-post p{margin:0 0 16px;color:var(--body)}
.yomi-clean-post ul,.yomi-clean-post ol{margin:10px 0 18px;padding-left:22px}
.yomi-clean-post li{margin:8px 0;color:var(--body)}
.yomi-clean-post li::marker{color:var(--muted);font-weight:700}
.yomi-clean-post strong{color:var(--ink)}
.yomi-clean-post a{color:var(--a1);text-decoration:none;border-bottom:1px solid transparent}
.yomi-clean-post a:hover{border-bottom-color:var(--a1)}
/* 섹션 라벨: 필(알약) 장식 제거 — 작은 악센트 텍스트로 통일 */
.section-label,.yomi-kicker{display:block;margin:0 0 10px;padding:0;border:0;background:none;color:var(--a1);font-size:.82rem;font-weight:800;line-height:1.4;letter-spacing:.01em}
.section-label:before,.yomi-kicker:before{content:none;display:none}
/* ── 카드 공통 규격: 모든 섹션 동일 ── */
.yomi-lede,.preview-hook,.hero-summary-box,
.yomi-note,.yomi-judgment-box,.real-criterion,.core-message-box,.target-reader-box,
.misconception-box,.quick-decision-table,
.actions-box,.action-guide-box,.checklist,.quality-checklist,
.yomi-faq .intent-qa-item,.faq-card,.faq-item,.intent-qa-item,
.yomi-paa-compact,.yomi-engine-support,
.confirmed-section,.check-needed-section,
.yomi-internal-links,.tool-summary,.pricing-table,
.who-for-rec,.who-for-non,.risk-note,.verdict-box,.use-case-card{
  margin:26px 0;padding:18px 20px;border:1px solid var(--line);background:#fff;border-radius:10px;box-shadow:none}
.yomi-faq .intent-qa-item,.faq-card,.faq-item,.intent-qa-item,.confirmed-section,.check-needed-section,.use-case-card{margin:0 0 12px}
/* 강조 카드는 딱 두 곳: 도입(리드)과 결론 — 악센트 왼줄 3px */
.yomi-lede,.preview-hook,.hero-summary-box{background:var(--soft);border-left:3px solid var(--a1)}
.yomi-lede p,.preview-hook p,.hero-summary-box p{font-size:1.03em;color:var(--ink)}
.yomi-lede p:last-child,.preview-hook p:last-child,.hero-summary-box p:last-child{margin-bottom:0}
.yomi-judgment-box{border-left:3px solid var(--a1)}
.yomi-note p{color:var(--body);font-weight:600}
.yomi-note p:last-child,.yomi-judgment-box p:last-child{margin-bottom:0}
.yomi-note h2,.yomi-judgment-box h2,.real-criterion h2,.core-message-box h2,.target-reader-box h2{margin-top:0;border:0;padding:0;background:none;font-size:1.06rem}
.real-criterion{white-space:pre-line}
/* ── 표 기본값: 래퍼 클래스 없이 나온 표도 최소한의 규격을 보장 ──
   (LLM이 래퍼를 빼먹은 비교표가 무스타일 브라우저 기본값으로 노출되던 결함 방어.
   아래 '표 공통' 박스 규칙이 같은 특이도로 뒤에 오므로 박스 표는 그쪽이 이긴다.) */
.yomi-clean-post table{width:100%;border-collapse:separate;border-spacing:0;margin:14px 0;font-size:.95rem;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.yomi-clean-post th{background:var(--soft);color:var(--ink);text-align:left;padding:12px 14px;font-weight:750;vertical-align:top;font-size:.92rem;border-bottom:1px solid var(--line)}
.yomi-clean-post td{border-top:1px solid var(--line);padding:12px 14px;vertical-align:top;background:#fff;color:var(--body)}
.yomi-clean-post tr:first-child td{border-top:0}
/* ── 표 공통: 헤더는 중립 그레이, 줄무늬 없음 ── */
.misconception-box table,.quick-decision-table table,.pricing-table table,.yomi-risk{width:100%;border-collapse:separate;border-spacing:0;margin:12px 0 4px;font-size:.95rem;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.misconception-box th,.quick-decision-table th,.pricing-table th,.yomi-risk th{background:var(--soft);color:var(--ink);text-align:left;padding:12px 14px;font-weight:750;vertical-align:top;font-size:.92rem;border-bottom:1px solid var(--line)}
.misconception-box td,.quick-decision-table td,.pricing-table td,.yomi-risk td{border-top:1px solid var(--line);padding:12px 14px;vertical-align:top;background:#fff;color:var(--body)}
.misconception-box tr:first-child td,.quick-decision-table tr:first-child td,.pricing-table tr:first-child td,.yomi-risk tr:first-child td{border-top:0}
.misconception-box td:first-child,.quick-decision-table td:first-child,.yomi-risk td:first-child{font-weight:650;color:var(--ink)}
.misconception-box,.quick-decision-table,.pricing-table{overflow-x:auto}
.pricing-table caption{caption-side:top;text-align:left;color:var(--muted);font-size:.88rem;margin-bottom:8px}
/* ── 번호 행동 리스트 ── */
.actions-box ol,.yomi-list{counter-reset:yomi-step;list-style:none;margin:12px 0 4px;padding:0}
.actions-box li,.yomi-list li{counter-increment:yomi-step;position:relative;margin:0;padding:13px 0 13px 44px;border-top:1px dashed var(--line)}
.actions-box li:first-child,.yomi-list li:first-child{border-top:0}
.actions-box li:before,.yomi-list li:before{content:attr(data-step);position:absolute;left:0;top:13px;width:28px;height:28px;border-radius:8px;background:var(--ink);color:#fff;font-size:.78rem;line-height:28px;text-align:center;font-weight:800}
.actions-box li:not([data-step]):before,.yomi-list li:not([data-step]):before{content:counter(yomi-step)}
.yomi-list li::marker{content:""}
.actions-box strong{color:var(--ink)}
/* ── 카드 그리드 ── */
.yomi-thesis,.key-fact-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:22px 0}
.yomi-thesis div,.key-fact-cards .fact-card{border:1px solid var(--line);background:#fff;padding:16px 17px;border-radius:10px}
.yomi-lens{display:grid;grid-template-columns:1fr;gap:11px;margin:22px 0}
.yomi-lens article{border:1px solid var(--line);background:#fff;padding:15px 17px;border-radius:10px}
.yomi-lens article p{margin-bottom:0}
.yomi-thesis b,.yomi-lens b,.key-fact-cards strong{display:block;margin-bottom:8px;color:var(--ink);font-size:1.01em}
.yomi-tag{display:inline-block;font-size:.78rem;font-weight:800;padding:3px 10px;border-radius:999px;background:#eef2f7;color:var(--body);margin-bottom:5px}
.yomi-tag.red,.yomi-tag.amber,.yomi-tag.blue{background:#eef2f7;color:var(--body)}
/* ── FAQ ── */
.yomi-faq,.faq-block{margin:30px 0}
.yomi-faq h3,.faq-card h3,.faq-item h3,.intent-qa-item h3{margin-top:0;color:var(--ink);padding-left:12px;border-left:3px solid var(--a1)}
.yomi-faq p:last-child,.faq-card p:last-child,.faq-item p:last-child,.intent-qa-item p:last-child{margin-bottom:0}
.yomi-paa-compact h2{font-size:1.05rem;margin:0 0 10px;color:var(--ink);border:0;padding:0;background:none}
.yomi-paa-compact ul{margin:0;padding-left:20px}
.yomi-paa-compact li{margin:7px 0}
.yomi-engine-support{padding-bottom:4px}
/* ── 검증/확인 ── */
.confirmed-needed-box{margin:30px 0;padding:0}
.confirmed-needed-box h2{margin-top:0}
.confirmed-section h3,.check-needed-section h3{margin-top:0;display:flex;align-items:center;gap:8px}
.confirmed-section h3:before{content:"OK";flex:none;width:30px;height:22px;border-radius:6px;background:#eef2f7;color:var(--body);font-size:.66rem;line-height:22px;text-align:center;font-weight:800}
.check-needed-section h3:before{content:"CHK";flex:none;width:34px;height:22px;border-radius:6px;background:#fdf3e3;color:#8a5a12;font-size:.64rem;line-height:22px;text-align:center;font-weight:800}
.check-needed-section{border-left:3px solid #d9a24a}
/* ── 주의(경고 톤은 이 한 곳만) ── */
.risk-note{border-left:3px solid #d9a24a}
.risk-note .section-label{color:#8a5a12}
.risk-note ul{margin:10px 0 2px;padding-left:20px}
.risk-note li{margin:7px 0}
/* ── 출처/해시태그/내부링크 ── */
.yomi-source{font-size:.92rem;color:var(--muted);border-top:1px solid var(--line);margin-top:36px;padding-top:18px}
.yomi-source h2{font-size:1.02rem;border:0;padding:0;margin:0 0 10px;color:var(--body);background:none}
.yomi-source li{margin-bottom:7px}
.yomi-source p{color:var(--muted)}
.yomi-hashtags,.hashtag-box{margin:28px 0 8px;padding:16px 0 0;border-top:1px solid var(--line);background:transparent}
.yomi-hashtags p,.hashtag-box p{margin:0;color:var(--a1);font-size:.93rem;line-height:2;font-weight:750}
.yomi-internal-links h2{font-size:1.05rem;margin:0 0 12px;color:var(--ink);border:0;padding:0;background:none}
.yomi-internal-links ul{margin:0;padding:0;list-style:none}
.yomi-internal-links li{margin:9px 0;padding-left:20px;position:relative}
.yomi-internal-links li:before{content:"";position:absolute;left:2px;top:.62em;width:7px;height:7px;border-top:2px solid var(--a1);border-right:2px solid var(--a1);transform:rotate(45deg)}
.yomi-internal-links a{font-weight:650}
/* ── 프롬프트 카드 ── */
.prompt-recipe-box{margin:26px 0}
.prompt-card{border:1px solid var(--line);border-radius:10px;margin:0 0 14px;overflow:hidden}
.prompt-card-label{margin:0!important;padding:10px 15px!important;background:var(--soft)!important;color:var(--ink)!important;font-size:.86rem;font-weight:750;border-bottom:1px solid var(--line)}
.yomi-clean-post .prompt-code{margin:0!important;padding:16px 17px!important;background:#fbfcfe!important;color:var(--ink)!important;font-family:'D2Coding','Consolas','Courier New',monospace;font-size:.92rem;line-height:1.75;white-space:pre-wrap;word-break:break-word;overflow-x:auto}
/* ── 마감 CTA 카드: 결론 강조 카드 (리드와 함께 강조 2곳 원칙 유지) ── */
.deadline-box{margin:30px 0 8px;padding:20px 22px;border:1px solid var(--line);border-left:3px solid var(--a1);background:var(--soft);border-radius:10px}
.deadline-box .dl-icon{display:inline-block;font-size:1.4rem;line-height:1;margin-right:8px;vertical-align:-3px}
.deadline-box .dl-title{display:inline-block;font-weight:800;color:var(--ink);font-size:1.05rem}
.deadline-box .dl-desc{margin:10px 0 0;color:var(--ink);font-size:1.01em}
/* ── 체크리스트 ── */
.quality-checklist ul{margin:10px 0 2px;padding:0;list-style:none}
.quality-checklist li{margin:0;padding:10px 0 10px 30px;position:relative;border-top:1px dashed var(--line);color:var(--body)}
.quality-checklist li:first-child{border-top:0}
.quality-checklist li:before{content:"\\2713";position:absolute;left:2px;top:9px;color:var(--a1);font-weight:800;font-size:1.1em}
/* ── 요약/추천/판정 ── */
.tool-summary p[itemprop="description"]{margin:0;color:var(--ink);font-weight:600;font-size:1.02em}
.who-for{margin:26px 0}
.who-for-cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}
.who-for-rec,.who-for-non{margin:0}
.who-for-rec h3,.who-for-non h3{margin:0 0 9px;font-size:1rem}
.who-for ul{margin:0;padding-left:20px}
.who-for li{margin:7px 0}
.verdict-box{border-left:3px solid var(--a1)}
.verdict-box p{margin:0 0 8px;color:var(--ink)}
.verdict-box p:last-child{margin-bottom:0}
.verdict-rating{color:var(--a1);font-size:1.1rem;font-weight:800;letter-spacing:2px}
.use-cases{margin:26px 0}
.use-case-when{margin:0 0 5px;font-weight:750;color:var(--ink)}
.use-case-how{margin:0;color:var(--body)}
/* ── 커버/히어로: 그라디언트 제거, 악센트 단색 ── */
.ai-cover-image,figure[data-yomi-block="cover-image"]{margin:0 0 24px}
.ai-cover-image img,figure[data-yomi-block="cover-image"] img{width:100%;height:auto;display:block;aspect-ratio:16/9;object-fit:cover;border-radius:10px;border:1px solid var(--line)}
.ai-hero{display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin:2px 0 28px;padding:20px 22px;border-radius:12px;background:var(--a1);color:#fff}
.ai-hero-icon{font-size:1.7rem;line-height:1}
.ai-hero-badge{font-size:.78rem;font-weight:800;letter-spacing:.02em;background:rgba(255,255,255,.18);padding:5px 12px;border-radius:999px}
.ai-hero-title{flex:1 1 100%;font-size:1.14rem;font-weight:750;line-height:1.42;margin-top:4px}
/* ── 글별 악센트 테마: --a1 한 색만 바뀐다 ── */
.yomi-clean-post.theme-teal{--a1:#0f766e}
.yomi-clean-post.theme-violet{--a1:#6d28d9}
.yomi-clean-post.theme-blue{--a1:#1d4ed8}
.yomi-clean-post.theme-emerald{--a1:#047857}
.yomi-clean-post.theme-rose{--a1:#be123c}
.yomi-clean-post.theme-indigo{--a1:#4338ca}
.yomi-clean-post.theme-sky{--a1:#0369a1}
.yomi-clean-post.theme-amber{--a1:#b45309}
@media(max-width:640px){
.post-title.entry-title{font-size:19px!important;line-height:1.28!important;word-break:keep-all!important;overflow-wrap:normal!important;letter-spacing:0!important}
.yomi-clean-post{width:100%;max-width:100%;font-size:16px;line-height:1.78;padding:0 16px 30px!important;overflow-x:hidden;word-break:normal}
.yomi-clean-post h1{font-size:1.42rem}
.yomi-clean-post h2{font-size:1.16rem;overflow-wrap:anywhere;margin:34px 0 14px}
.yomi-lede,.preview-hook,.hero-summary-box,.yomi-note,.yomi-judgment-box,.misconception-box,.quick-decision-table,.actions-box,.action-guide-box,.checklist,.quality-checklist,.yomi-paa-compact,.confirmed-section,.check-needed-section,.yomi-internal-links,.yomi-engine-support,.tool-summary,.pricing-table,.risk-note,.verdict-box,.deadline-box{padding:15px 16px;border-radius:10px}
.yomi-clean-post table{display:block;overflow-x:auto}
.yomi-thesis,.yomi-lens,.key-fact-cards,.who-for-cols{grid-template-columns:1fr;gap:12px}
.ai-hero{padding:16px 17px;border-radius:11px}
.ai-hero-title{font-size:1.04rem}
.misconception-box table,.quick-decision-table table,.pricing-table table,.yomi-risk{display:block;border:0;background:transparent}
.misconception-box thead,.quick-decision-table thead,.pricing-table thead,.yomi-risk thead{display:none}
.misconception-box tbody,.quick-decision-table tbody,.pricing-table tbody,.yomi-risk tbody{display:block}
.misconception-box tr,.quick-decision-table tr,.pricing-table tr,.yomi-risk tr{display:block;border:1px solid var(--line);border-radius:8px;margin:0 0 12px;background:#fff;overflow:hidden}
.misconception-box td,.quick-decision-table td,.pricing-table td,.yomi-risk td{display:block;width:100%;border:0!important;border-top:1px solid var(--line)!important;padding:11px 13px!important;background:#fff!important}
.misconception-box td:first-child,.quick-decision-table td:first-child,.pricing-table td:first-child,.yomi-risk td:first-child{border-top:0!important;background:var(--soft)!important;font-weight:750;color:var(--ink)}
}
</style>"""

_BANNED_LABEL_FRAGMENTS = (
    "http://",
    "https://",
    "blog.naver.com",
    "n.news.naver.com",
    "v.daum.net",
    ".com",
    ".co.kr",
    "{{",
    "}}",
)

_NAVER_CTA_PATTERNS = (
    r'<div\b[^>]*>\s*(?:(?!</div>).)*blog\.naver\.com/holyyomi(?:(?!</div>).)*</div>',
    r'<section\b[^>]*class=["\'][^"\']*naver[^"\']*["\'][^>]*>.*?</section>',
    r'<a\b[^>]*href=["\']https?://blog\.naver\.com/holyyomi[^"\']*["\'][^>]*>.*?</a>',
)
_OWN_LINK_HOSTS = (BLOGSPOT_HOST,)
_OFFICIAL_SOURCE_HOSTS = (
    "www.gov.kr",
    "gov.kr",
    "www.bokjiro.go.kr",
    "bokjiro.go.kr",
    "www.hometax.go.kr",
    "hometax.go.kr",
    "m.hometax.go.kr",
    "www.nts.go.kr",
    "nts.go.kr",
    "www.kca.go.kr",
    "kca.go.kr",
    "www.ftc.go.kr",
    "ftc.go.kr",
    "www.fss.or.kr",
    "fss.or.kr",
    "www.kcc.go.kr",
    "kcc.go.kr",
    "dart.fss.or.kr",
    "kind.krx.co.kr",
)
_ALLOWED_LINK_HOSTS = _OWN_LINK_HOSTS + _OFFICIAL_SOURCE_HOSTS
_ANCHOR_WITH_HREF_RE = re.compile(
    r"<a\b(?P<before>[^>]*)\bhref=(?P<quote>[\"'])(?P<href>.*?)(?P=quote)(?P<after>[^>]*)>(?P<body>.*?)</a>",
    flags=re.IGNORECASE | re.DOTALL,
)

_UNVERIFIED_EXPERIENCE_PATTERNS = (
    r"첫\s*수익\s*경험",
    r"(?:제가|저는|내가|직접)\s*[^<]{0,80}(?:수익|벌었|벌어|매출)",
    r"(?:월|하루|일)\s*\d[\d,]*(?:만\s*)?원\s*(?:수익|매출|벌)",
    r"\d[\d,]*\s*원(?:의)?\s*(?:수익|매출|입금)",
    r"월\s*\d[\d,]*(?:만\s*)?원\s*(?:이상|이하)?\s*(?:수익|매출|입금|벌)",
)

_SLUG_KEYWORD_MAP = (
    ("여론조사", "poll"),
    ("지지율", "approval"),
    ("선거", "election"),
    ("대통령", "president"),
    ("정치", "politics"),
    ("국회", "assembly"),
    ("정부", "government"),
    ("지원금", "support"),
    ("신청", "apply"),
    ("마감", "deadline"),
    ("환급", "refund"),
    ("세금", "tax"),
    ("소비자", "consumer"),
    ("피해", "warning"),
    ("환불", "refund"),
    ("가격", "price"),
    ("요금", "fee"),
    ("구독", "subscription"),
    ("배달", "delivery"),
    ("플랫폼", "platform"),
    ("서비스", "service"),
    ("스포츠", "sports"),
    ("야구", "baseball"),
    ("축구", "football"),
    ("드라마", "drama"),
    ("방송", "broadcast"),
    ("연예", "entertainment"),
    ("이슈", "issue"),
    ("논란", "controversy"),
    ("반응", "reaction"),
    # AI / 업무 / 생산성 (golden: ai_work_tip)
    ("인공지능", "ai"),
    ("자동화", "automation"),
    ("생산성", "productivity"),
    ("직장인", "worker"),
    ("업무", "work"),
    ("프롬프트", "prompt"),
    ("챗봇", "chatbot"),
    # IT / 기기 / 앱
    ("스마트폰", "smartphone"),
    ("아이폰", "iphone"),
    ("갤럭시", "galaxy"),
    # 게임 (golden: viral/corporate issue decode)
    ("게임", "game"),
    ("출시", "launch"),
    ("베타", "beta"),
    ("공개", "reveal"),
    ("콘솔", "console"),
    # OTT / 콘텐츠 (golden: ott_platform)
    ("넷플릭스", "netflix"),
    ("유튜브", "youtube"),
    ("티빙", "tving"),
    ("영화", "movie"),
    ("시즌", "season"),
    # 생활/머니
    ("할인", "discount"),
    ("금리", "rate"),
    ("채용", "hiring"),
    ("연봉", "salary"),
)

_SLUG_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "this",
    "that",
    "news",
}

# 의미가 약해 SERP/CTR 기여가 낮은 generic filler 토큰.
# 실제 주제 키워드보다 뒤로 보내 7토큰 상한에서 키워드가 밀려나지 않게 한다.
_SLUG_GENERIC_TOKENS = {
    "today",
    "issue",
    "update",
    "korea",
    "news",
    "online",
}


def normalize_labels(labels: list[str] | tuple[str, ...] | None, *, fallback: tuple[str, ...] = DEFAULT_BLOGSPOT_LABELS) -> list[str]:
    cleaned: list[str] = []
    source_labels = list(labels or []) or list(fallback)
    for label in source_labels:
        text = _clean_label(str(label or ""))
        if not text:
            continue
        lowered = text.lower()
        if any(fragment in lowered for fragment in _BANNED_LABEL_FRAGMENTS):
            continue
        if len(text) > 24:
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= MAX_BLOGSPOT_LABELS:
            break
    return cleaned


def normalize_hashtags(hashtags: list[str] | tuple[str, ...] | None) -> list[str]:
    cleaned: list[str] = []
    for hashtag in hashtags or []:
        text = _clean_label(str(hashtag or "").lstrip("#"))
        if not text:
            continue
        lowered = text.lower()
        if any(fragment in lowered for fragment in _BANNED_LABEL_FRAGMENTS):
            continue
        if len(text) > 18:
            continue
        tag = f"#{text}"
        if tag not in cleaned:
            cleaned.append(tag)
        if len(cleaned) >= MAX_CONTENT_HASHTAGS:
            break
    return cleaned


def strip_naver_ctas(html: str) -> str:
    cleaned = html or ""
    for pattern in _NAVER_CTA_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_external_anchor_links(
    html: str,
    *,
    allowed_hosts: tuple[str, ...] = _ALLOWED_LINK_HOSTS,
    extra_allowed_urls: frozenset[str] | tuple[str, ...] = (),
) -> str:
    """Remove arbitrary outbound anchors while preserving verified source links.

    The visible anchor text stays in place for attribution/context, but the
    external href itself is removed. Internal Blogspot links, relative links,
    and official authority sources used for citations are preserved.

    extra_allowed_urls (2026-07-16): exact-match allowlist for citation links
    that were actually fetched this run (Naver news originallink/link, Exa
    result url) and threaded through by the caller — NOT a host allowlist, so
    an LLM hallucinating a random-looking anchor elsewhere in the body still
    gets stripped by the normal host check. Only URLs the caller explicitly
    vouches for (because they came straight out of a real API response, not
    from generated text) survive here.
    """
    if not html:
        return html
    extra_set = frozenset(extra_allowed_urls)

    def _replace(match: re.Match[str]) -> str:
        href = unescape(str(match.group("href") or "")).strip()
        if href in extra_set:
            return match.group(0)
        if _is_external_anchor_href(href, allowed_hosts=allowed_hosts):
            return str(match.group("body") or "")
        return match.group(0)

    return _ANCHOR_WITH_HREF_RE.sub(_replace, html)


def strip_inline_style_attributes(html: str) -> str:
    """Keep generated posts on the shared clean-post stylesheet."""
    return re.sub(r"\sstyle=(['\"]).*?\1", "", html or "", flags=re.IGNORECASE | re.DOTALL)


def strip_style_blocks(html: str) -> str:
    """Use one shared article stylesheet instead of mixed generator CSS."""
    return re.sub(r"<style\b[^>]*>.*?</style>", "", html or "", flags=re.IGNORECASE | re.DOTALL)


def strip_internal_link_sections(html: str) -> str:
    """Remove generated internal-link candidate blocks from publish HTML."""
    if not html:
        return html
    pattern = re.compile(
        r'\s*<section\b(?=[^>]*(?:data-yomi-block=["\']internal-links["\']|class=["\'][^"\']*\binternal-links\b))[^>]*>.*?</section>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", html)


def strip_hashtag_sections(html: str) -> str:
    """Remove generator hashtag blocks before the final controlled footer is added."""
    if not html:
        return html
    block_pattern = re.compile(
        r'\s*<(?P<tag>section|div)\b(?=[^>]*(?:data-yomi-block=["\']hashtags["\']|class=["\'][^"\']*\b(?:yomi-hashtags|hashtag-box|tag-list)\b))[^>]*>.*?</(?P=tag)>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = block_pattern.sub("", html)
    hashtag_note_pattern = re.compile(
        r'\s*<p\b(?=[^>]*class=["\'][^"\']*\bsource-note\b)[^>]*>[^<]*#[가-힣A-Za-z0-9_][^<]*</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = hashtag_note_pattern.sub("", cleaned)
    # LLM이 일반 문단 안에 쓴 떠돌이 해시태그 정리 — 통제된 푸터 블록은 이 단계
    # 이후(append_hashtags_block)에 붙으므로 여기서 지워도 안전하다. 방치하면
    # final_html_audit의 uncontrolled_visible_body_hashtags 게이트에 걸려 발행이 막힌다.
    # 인라인 태그로 감싼 해시태그 뭉치(<strong>#a #b</strong> 등)를 먼저 벗겨서
    # 아래 정리 패턴이 잡을 수 있게 한다.
    inline_wrapped_hashtags = re.compile(
        r'<(strong|em|b|span)\b[^>]*>((?:\s|&nbsp;|[,·|/]|#[가-힣A-Za-z0-9_]{2,})+)</\1>',
        flags=re.IGNORECASE,
    )
    cleaned = inline_wrapped_hashtags.sub(r"\2", cleaned)
    hashtag_only_element = re.compile(
        r'\s*<(p|li|div)\b[^>]*>(?:\s|&nbsp;|[,·|/]|<br\s*/?>|#[가-힣A-Za-z0-9_]{2,})+</\1>',
        flags=re.IGNORECASE,
    )
    cleaned = hashtag_only_element.sub("", cleaned)
    trailing_hashtag_run = re.compile(
        r'(?:\s|&nbsp;)*(?:#[가-힣A-Za-z0-9_]{2,}(?:\s|&nbsp;|[,·])*){2,}(</(?:p|li|div|h2|h3)>)',
        flags=re.IGNORECASE,
    )
    return trailing_hashtag_run.sub(r"\1", cleaned)


def count_external_anchor_links(
    html: str,
    *,
    allowed_hosts: tuple[str, ...] = _ALLOWED_LINK_HOSTS,
    extra_allowed_urls: frozenset[str] | tuple[str, ...] = (),
) -> int:
    """Count outbound anchors that would be stripped by strip_external_anchor_links.

    extra_allowed_urls mirrors strip_external_anchor_links: exact-match citation
    URLs the caller vouches for (fetched this run, not LLM-generated) don't count
    as blockable external anchors here either — keeps the gate and the stripper
    in agreement about which links are "real citations" vs. arbitrary outbound links.
    """
    if not html:
        return 0
    extra_set = frozenset(extra_allowed_urls)
    count = 0
    for match in _ANCHOR_WITH_HREF_RE.finditer(html):
        href = unescape(str(match.group("href") or "")).strip()
        if href in extra_set:
            continue
        if _is_external_anchor_href(href, allowed_hosts=allowed_hosts):
            count += 1
    return count


def strip_document_shell(html: str) -> str:
    """Return post body content only, never a full HTML document shell."""
    content = re.sub(r"<!doctype\b[^>]*>", "", html or "", flags=re.IGNORECASE)
    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", content, flags=re.IGNORECASE | re.DOTALL)
    if body_match:
        content = body_match.group(1)
    else:
        content = re.sub(r"<head\b[^>]*>.*?</head>", "", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"</?(?:html|body)\b[^>]*>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<title\b[^>]*>.*?</title>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<meta\b[^>]*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    return content.strip()


def strip_body_meta_tags(html: str) -> str:
    return re.sub(r"\s*<meta\b[^>]*>\s*", "\n", html or "", flags=re.IGNORECASE | re.DOTALL).strip()


def append_hashtags_block(
    html: str,
    hashtags: list[str] | tuple[str, ...] | None = None,
    *,
    labels: list[str] | tuple[str, ...] | None = None,
) -> str:
    content = strip_hashtag_sections(html or "")
    tags = normalize_hashtags(hashtags or labels or [])
    if not content or not tags:
        return content
    tag_text = " ".join(escape(tag) for tag in tags)
    block = (
        '<section class="yomi-hashtags" data-yomi-block="hashtags" aria-label="관련 해시태그">'
        f"<p>{tag_text}</p>"
        "</section>"
    )
    closes = list(re.finditer(r"</article>", content, flags=re.IGNORECASE))
    if closes:
        # 마지막 </article>(=최상위 본문 닫힘) 앞에 삽입한다. 과거의 "첫 번째
        # </article> 앞" 기준은 FAQ가 중첩 <article class="faq-item">일 때
        # 해시태그를 첫 FAQ 내부에 넣었고, 최종 계약의 답변 추출기가 해시태그를
        # faq 답변으로 오인해 low_quality로 발행을 차단했다(2026-07-08 실측).
        last = closes[-1]
        return f"{content[:last.start()]}{block}\n{content[last.start():]}"
    return f"{content.rstrip()}\n{block}"


def append_internal_links_block(
    html: str,
    *,
    links: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None = None,
    include_fallbacks: bool = False,
) -> str:
    if not html:
        return html
    cleaned = strip_internal_link_sections(html)
    selected_links = _fill_internal_links(links, include_fallbacks=include_fallbacks)
    if not selected_links:
        return cleaned
    items = "".join(
        f'<li><a href="{escape(url)}">{escape(title)}</a></li>'
        for title, url in selected_links[:3]
    )
    block = (
        '\n<section class="yomi-internal-links" data-yomi-block="internal-links">'
        "<h2>같이 보면 좋은 내부 글</h2>"
        f"<ul>{items}</ul>"
        "</section>"
    )
    if re.search(r"</article>", cleaned, flags=re.IGNORECASE):
        return re.sub(r"</article>", f"{block}\n</article>", cleaned, count=1, flags=re.IGNORECASE)
    if re.search(r"</body>", cleaned, flags=re.IGNORECASE):
        return re.sub(r"</body>", f"{block}\n</body>", cleaned, count=1, flags=re.IGNORECASE)
    return cleaned.rstrip() + block


def ensure_yomi_clean_article_layout(html: str) -> str:
    """Normalize publish HTML to the clean readable layout used by the preferred post."""
    if not html:
        return html
    content = _normalize_legacy_article_classes(html)
    content = _dedupe_yomi_lede_classes(content)
    content = _ensure_yomi_article_class(content)
    content = _ensure_yomi_clean_style(content)
    return content


def build_internal_links_from_history(
    records: list[dict] | tuple[dict, ...],
    *,
    current_title: str = "",
    current_topic: str = "",
    current_topic_group: str = "",
    current_content_type: str = "",
    current_url: str = "",
    limit: int = 3,
) -> tuple[tuple[str, str], ...]:
    """Build crawlable links to already-published Blogspot posts."""
    current_text = f"{current_title} {current_topic}".lower()
    current_tokens = {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", current_text)
        if token not in {"오늘", "이슈", "뉴스", "정리"}
    }
    candidates: list[tuple[int, str, str, str]] = []
    seen_urls: set[str] = set()

    for idx, record in enumerate(sorted(records or [], key=_history_sort_key, reverse=True)):
        url = _record_url(record)
        title = " ".join(str(record.get("title") or record.get("selected_title") or "").split())
        if not url or not title:
            continue
        if url == current_url or url in seen_urls or not _is_blogspot_post_url(url):
            continue
        if _has_weak_blogspot_slug(url):
            continue
        if current_title and title == current_title:
            continue
        if not _record_is_published(record):
            continue
        if record.get("post_publish_audit_passed") is False:
            continue
        if not _record_title_is_safe_for_internal_link(record, title=title):
            continue
        seen_urls.add(url)

        score = 10
        if current_topic_group and str(record.get("topic_group") or "") == current_topic_group:
            score += 8
        if current_content_type and str(record.get("content_type") or "") == current_content_type:
            score += 4
        record_text = f"{title} {record.get('selected_topic') or ''}".lower()
        overlap = sum(1 for token in current_tokens if token in record_text)
        score += min(5, overlap)
        score -= idx // 5
        candidates.append((score, title[:70], url, str(record.get("run_at") or "")))

    candidates.sort(key=lambda item: (item[0], item[3]), reverse=True)
    selected = tuple((title, url) for _, title, url, _ in candidates[: max(1, limit)])
    return _fill_internal_links(selected, current_url=current_url, limit=limit)


def _record_title_is_safe_for_internal_link(record: dict, *, title: str) -> bool:
    source_text = " ".join(
        str(record.get(key) or "")
        for key in ("selected_topic", "search_demand_topic", "topic", "source_title", "original_topic")
    )
    result = audit_title_integrity(
        title,
        content_type=str(record.get("content_type") or ""),
        topic_group=str(record.get("topic_group") or ""),
        source_text=source_text,
    )
    return bool(result.get("passed"))


def _fill_internal_links(
    links: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None,
    *,
    current_url: str = "",
    limit: int = 3,
    include_fallbacks: bool = False,
) -> tuple[tuple[str, str], ...]:
    target_limit = max(1, limit)
    selected: list[tuple[str, str]] = []
    used_urls: set[str] = set()

    for title, url in tuple(links or ()):
        clean_title = " ".join(str(title or "").split())
        clean_url = str(url or "").strip()
        if not clean_title or not clean_url or clean_url == current_url or clean_url in used_urls:
            continue
        selected.append((clean_title[:70], clean_url))
        used_urls.add(clean_url)
        if len(selected) >= target_limit:
            return tuple(selected)

    if not include_fallbacks:
        return tuple(selected)

    for title, url in DEFAULT_INTERNAL_LINKS:
        if len(selected) >= target_limit:
            break
        if url == current_url or url in used_urls:
            continue
        selected.append((title, url))
        used_urls.add(url)

    return tuple(selected)


def prepare_blogspot_html(
    html: str,
    *,
    links: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None = None,
    include_internal_links: bool = False,
    strip_document: bool = False,
    extra_allowed_urls: frozenset[str] | tuple[str, ...] = (),
) -> str:
    selected_links = _fill_internal_links(tuple(links or ()))
    source = strip_document_shell(html) if strip_document else (html or "")
    cleaned = strip_style_blocks(
        strip_inline_style_attributes(
            strip_external_anchor_links(strip_naver_ctas(source), extra_allowed_urls=extra_allowed_urls)
        )
    )
    if strip_document:
        cleaned = strip_body_meta_tags(cleaned)
    cleaned = strip_internal_link_sections(cleaned)
    cleaned = strip_hashtag_sections(cleaned)
    cleaned = ensure_yomi_clean_article_layout(cleaned)
    cleaned = _move_known_body_sections_inside_article(cleaned)
    if not include_internal_links:
        return cleaned
    return append_internal_links_block(cleaned, links=selected_links)


def improve_image_alt_text(html: str, *, image_alt_text: str = "") -> str:
    alt_text = " ".join((image_alt_text or "").split()).strip()
    if not html or not alt_text:
        return html

    def _replace(match: re.Match[str]) -> str:
        quote = match.group(1)
        current = " ".join((match.group(2) or "").split()).strip().lower()
        if current and current not in {"이미지", "내 사진", "image", "cover image", "커버 이미지"}:
            return match.group(0)
        return f'alt={quote}{escape(alt_text, quote=True)}{quote}'

    return re.sub(r'alt=(["\'])(.*?)\1', _replace, html, flags=re.IGNORECASE | re.DOTALL)


def build_english_permalink_slug(
    *,
    title: str,
    topic: str = "",
    labels: list[str] | tuple[str, ...] | None = None,
    topic_group: str = "",
    slug_hint: str = "",
) -> str:
    source = " ".join([title or "", topic or "", " ".join(labels or []), topic_group or ""]).strip()
    lowered_source = source.lower()
    tokens: list[str] = []

    # LLM이 제안한 영어 슬러그 힌트가 있으면 그 토큰을 최우선 사용.
    # 한국어 전용 제목은 아래 추출 로직이 generic 토큰("korea-issue-news")만
    # 만들기 때문에, 이슈 키워드가 담긴 힌트가 SERP 가독성·CTR에 유리하다.
    hint = re.sub(r"[^a-z0-9-]+", "-", (slug_hint or "").lower()).strip("-")
    for raw in hint.split("-"):
        token = raw.strip()
        if 2 <= len(token) <= 24 and token not in _SLUG_STOPWORDS:
            _append_unique(tokens, token)
        if len(tokens) >= 6:
            break

    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]{1,24}", lowered_source):
        token = re.sub(r"[^a-z0-9]+", "", raw.lower())
        if token and token not in _SLUG_STOPWORDS:
            _append_unique(tokens, token)

    for keyword, mapped in _SLUG_KEYWORD_MAP:
        if keyword in source:
            _append_unique(tokens, mapped)

    if re.search(r"\d+(?:\.\d+)?\s*%", source):
        _append_unique(tokens, "poll")
    if any(char.isdigit() for char in source):
        _append_unique(tokens, "update")
    if not tokens:
        tokens.extend(["korea", "issue"])
    if "news" not in tokens:
        tokens.append("news")

    # 실제 주제 키워드를 generic filler(today/issue/update/korea/news 등)보다 앞에 배치해
    # 7토큰 상한에서 키워드가 밀려나지 않게 한다. filler는 남는 슬롯만 채운다.
    primary = [token for token in tokens if token not in _SLUG_GENERIC_TOKENS]
    generic = [token for token in tokens if token in _SLUG_GENERIC_TOKENS]
    tokens = primary + generic

    digest = sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:6]
    trimmed = tokens[:7]
    if "news" not in trimmed:  # 카테고리 마커는 상한 안에서 유지
        trimmed = trimmed[:6] + ["news"]
    if len(trimmed) < 3:
        trimmed.append("korea")
    slug = "-".join(trimmed)
    if len(slug) < 16:
        slug = f"{slug}-{digest}"
    if digest not in slug:
        slug = f"{slug}-{digest}"
    return _normalize_slug(slug)


def url_matches_permalink_slug(url: str, slug: str) -> bool:
    """Return True when Blogger's returned URL kept the seeded English slug."""
    expected = _normalize_slug(slug)
    if not url or not expected:
        return False

    path_name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    actual = _normalize_slug(re.sub(r"\.html?$", "", path_name, flags=re.IGNORECASE))
    if not actual:
        return False
    if expected == actual or expected in actual:
        return True

    tokens = [token for token in expected.split("-") if token]
    digest = tokens[-1] if tokens and re.fullmatch(r"[a-f0-9]{6}", tokens[-1]) else ""
    if digest and digest in actual:
        return True

    informative = [
        token
        for token in tokens
        if token not in {"news", "update", "korea", "issue"} and token != digest
    ]
    required = informative[:2] or tokens[:2]
    return len(required) >= 2 and all(token in actual for token in required)


def normalize_search_description(*, title: str, description: str = "", html: str = "", topic: str = "") -> str:
    raw = " ".join((description or "").split()).strip()
    if not raw:
        raw = build_search_description(title=title, html=html, topic=topic)
    raw = unescape(re.sub(r"<[^>]+>", " ", raw))
    raw = " ".join(raw.split())
    if len(raw) < 80:
        raw = (
            f"{raw} 핵심 배경과 독자에게 미치는 영향, 확인할 지점을 한 번에 정리했습니다."
        ).strip()
    if len(raw) > 155:
        raw = raw[:155].rsplit(" ", 1)[0].rstrip(" .,")
    if len(raw) < 50:
        raise ValueError("Search description is too short.")
    return raw


def build_search_description(*, title: str, html: str = "", topic: str = "") -> str:
    # <style>/<script>를 먼저 제거하지 않으면 CSS 원문이 검색 설명에 새어 들어간다
    # (라이브 실측: search_description에 ".yomi-clean-post{max-width:744px…" 노출).
    stripped = re.sub(r"<style\b.*?</style>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    stripped = re.sub(r"<script\b.*?</script>", " ", stripped, flags=re.IGNORECASE | re.DOTALL)
    text = unescape(re.sub(r"<[^>]+>", " ", stripped))
    text = " ".join(text.split())
    seed = " ".join(part for part in [topic.strip(), title.strip()] if part)
    if text:
        first = re.split(r"(?:[.!?。]\s+|다\.\s+|요\.\s+)", text)[0]
        seed = " ".join(part for part in [seed, first] if part)
    if not seed:
        seed = "오늘의 주요 이슈"
    return normalize_search_description(title=title, description=seed, html="", topic=topic)


def _normalize_legacy_article_classes(html: str) -> str:
    replacements = {
        "golden-preview": "yomi-clean-post",
        "preview-hook": "yomi-lede",
        "hero-summary-box": "yomi-lede",
        "ai-overview-box": "yomi-lede",
        "issue-context-box": "yomi-note",
        "core-message-box": "yomi-note",
        "target-reader-box": "yomi-note",
        "callout": "yomi-note",
        "warning": "yomi-note",
        "key-fact-cards": "yomi-lens",
        "checklist-box": "yomi-list",
        "intent-answer-box": "yomi-faq",
        "paa-block": "yomi-paa-compact",
        "source-trust-box": "yomi-source",
        "faq faq-block": "yomi-faq",
        "answer-engine-support": "yomi-engine-support",
        # LLM 직접발행 본문이 쓰는 클래스 → 디자인 시스템 클래스로 정규화
        # (summary-card/faq-section/faq-item은 스타일 정의가 없어 브라우저
        # 기본값으로 노출되던 결함 — 라이브 발행 글에서 실측.)
        "summary-card": "quick-decision-table",
        "info-box": "yomi-note",
        "faq-section": "yomi-faq",
        # "faq-item": "faq-card" 매핑은 제거(2026-07-08) — faq-item이 표준이며
        # CSS가 직접 스타일한다. 이 매핑이 남아 있으면 prepare 경유 재렌더가
        # 발행 직전 faq-card를 부활시켜 overstack 게이트·최종 계약과 충돌한다.
    }
    content = html or ""
    for old, new in replacements.items():
        content = re.sub(
            rf'(\bclass=["\'][^"\']*)\b{re.escape(old)}\b',
            lambda match, replacement=new: f"{match.group(1)}{replacement}",
            content,
            flags=re.IGNORECASE,
        )
    return content


def _dedupe_yomi_lede_classes(html: str) -> str:
    content = html or ""
    lede_count = len(re.findall(r'class=["\'][^"\']*\byomi-lede\b', content, flags=re.IGNORECASE))
    if lede_count <= 1 or 'id="AI_OVERVIEW_TARGET_ANSWER"' not in content:
        return content

    pattern = re.compile(
        r'(<section\b(?=[^>]*\bid=["\']AI_OVERVIEW_TARGET_ANSWER["\'])(?P<attrs>[^>]*)>)',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def _replace(match: re.Match[str]) -> str:
        tag = match.group(1)
        class_match = re.search(r'class=(["\'])(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
        if not class_match:
            return tag
        classes = class_match.group(2).split()
        if "yomi-lede" not in classes:
            return tag
        classes = ["yomi-note" if item == "yomi-lede" else item for item in classes]
        new_classes = " ".join(dict.fromkeys(classes))
        return tag[: class_match.start(2)] + escape(new_classes, quote=True) + tag[class_match.end(2):]

    return pattern.sub(_replace, content, count=1)


def _ensure_yomi_article_class(html: str) -> str:
    if not html:
        return html
    if re.search(r"<article\b", html, flags=re.IGNORECASE):
        def _replace_article(match: re.Match[str]) -> str:
            tag = match.group(0)
            class_match = re.search(r'class=(["\'])(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
            if class_match:
                classes = class_match.group(2)
                if "yomi-clean-post" in classes.split():
                    return tag
                new_classes = f"yomi-clean-post {classes}".strip()
                return tag[: class_match.start(2)] + escape(new_classes, quote=True) + tag[class_match.end(2) :]
            return tag[:-1].rstrip() + ' class="yomi-clean-post">'

        return re.sub(r"<article\b[^>]*>", _replace_article, html, count=1, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"<body\b[^>]*>.*?</body>", html, flags=re.IGNORECASE | re.DOTALL):
        def _wrap_body(match: re.Match[str]) -> str:
            return f"{match.group(1)}\n<article class=\"yomi-clean-post\">\n{match.group(2).strip()}\n</article>\n{match.group(3)}"

        return re.sub(
            r"(<body\b[^>]*>)(.*?)(</body>)",
            _wrap_body,
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if re.search(r"</html>", html, flags=re.IGNORECASE):
        return html
    return f'<article class="yomi-clean-post">\n{html.strip()}\n</article>'


def _ensure_yomi_clean_style(html: str) -> str:
    if ".yomi-clean-post" in (html or ""):
        return html
    if re.search(r"</head>", html or "", flags=re.IGNORECASE):
        # 함수 치환 — STYLE의 CSS 이스케이프(\2713 등)가 그룹 참조로 오해석되지 않도록.
        return re.sub(
            r"</head>",
            lambda _m: f"{YOMI_CLEAN_ARTICLE_STYLE}\n</head>",
            html, count=1, flags=re.IGNORECASE,
        )
    return f"{YOMI_CLEAN_ARTICLE_STYLE}\n{html}"


def _move_known_body_sections_inside_article(html: str) -> str:
    """Keep late GEO/support blocks inside the styled article container."""
    if not html or not re.search(r"</article>", html, flags=re.IGNORECASE):
        return html
    if not re.search(r"</body>", html, flags=re.IGNORECASE):
        return html

    match = re.search(r"(</article>)(?P<tail>.*?)(</body>)", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return html

    moved_sections: list[str] = []
    section_pattern = re.compile(
        r'\s*(<section\b(?=[^>]*\bid=["\'](?:CONFIRMED_VS_CHECK_NEEDED_BLOCK|SOURCE_TRUST_BLOCK)["\'])[^>]*>.*?</section>)',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def _remove(match_section: re.Match[str]) -> str:
        moved_sections.append(match_section.group(1).strip())
        return ""

    tail = section_pattern.sub(_remove, match.group("tail"))
    if not moved_sections:
        return html

    moved = "\n" + "\n".join(moved_sections)
    return (
        html[: match.start(1)]
        + moved
        + "\n"
        + match.group(1)
        + tail
        + match.group(3)
        + html[match.end(3) :]
    )


def has_unverified_experience_or_income_claim(html: str) -> bool:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = " ".join(text.split())
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _UNVERIFIED_EXPERIENCE_PATTERNS)


def _clean_label(value: str) -> str:
    return "".join(value.split()).strip(" #,.-_/\\")


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > MAX_PERMALINK_SLUG_LENGTH:
        parts = [p for p in slug.split("-") if p]
        digest = parts[-1] if parts else ""
        # digest(-6자리 해시)는 항상 보존하고, 앞쪽 토큰을 토큰 경계에서만 채워
        # 'issu'처럼 단어가 토막나지 않게 한다.
        budget = MAX_PERMALINK_SLUG_LENGTH - (len(digest) + 1 if digest else 0)
        kept: list[str] = []
        length = 0
        for part in parts[:-1] if digest else parts:
            add = len(part) + (1 if kept else 0)
            if length + add > budget:
                break
            kept.append(part)
            length += add
        slug = "-".join(kept + ([digest] if digest else [])).strip("-")
        slug = slug[:MAX_PERMALINK_SLUG_LENGTH].rstrip("-")
    return slug or "korea-issue-news"


def _history_sort_key(record: dict) -> str:
    return str(record.get("run_at") or record.get("published_at") or record.get("date") or "")


def _record_url(record: dict) -> str:
    for key in ("url", "post_url", "published_url", "blogger_url"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _record_is_published(record: dict) -> bool:
    return PublishHistoryService.is_published_record(record)


def _is_blogspot_post_url(url: str) -> bool:
    parsed = urlsplit(url)
    if not parsed.netloc.endswith(BLOGSPOT_HOST):
        return False
    if "/search/" in parsed.path:
        return False
    return parsed.path.endswith(".html")


def _has_weak_blogspot_slug(url: str) -> bool:
    slug = unquote((urlsplit(url).path or "").rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"\.html$", "", slug, flags=re.IGNORECASE)
    return bool(
        re.fullmatch(r"blog-post(?:_\d+)?", slug or "")
        or re.fullmatch(r"\d+(?:[-_]\d+)*", slug or "")
        or len(slug) < 8
    )


def _is_external_anchor_href(href: str, *, allowed_hosts: tuple[str, ...]) -> bool:
    if not href or href.startswith(("#", "/", "?")):
        return False
    parsed = urlsplit(href)
    if parsed.scheme in {"", "http", "https"}:
        if not parsed.netloc:
            return False
        host = parsed.netloc.lower().split("@")[-1].split(":")[0]
        return not any(host == allowed.lower() or host.endswith(f".{allowed.lower()}") for allowed in allowed_hosts)
    return True
