# 블로그스팟 AI 블로그 완전 마스터 가이드
> Codex / Claude Code가 실행 가능한 수준의 구조화된 지침서  
> 대상: AI 주제 블로그스팟 블로그 | 목표: 조회수 폭발 + 애드센스 수익 극대화 + AI 인용 최적화

---

## INDEX

1. [AI 블로그 콘텐츠 방향성 & 구성 원칙](#1-ai-블로그-콘텐츠-방향성--구성-원칙)
2. [포스팅 구조 & 작성 패턴](#2-포스팅-구조--작성-패턴)
3. [SEO 세팅 (구글 검색 최적화)](#3-seo-세팅-구글-검색-최적화)
4. [AEO 세팅 (Answer Engine Optimization)](#4-aeo-세팅-answer-engine-optimization)
5. [GEO / SGE 세팅 (AI 인용 최적화)](#5-geo--sge-세팅-ai-인용-최적화)
6. [JSON-LD 구조화 데이터 전체 템플릿](#6-json-ld-구조화-데이터-전체-템플릿)
7. [블로그스팟 HTML 템플릿 세팅](#7-블로그스팟-html-템플릿-세팅)
8. [조회수 폭발 전략](#8-조회수-폭발-전략)
9. [애드센스 수익 극대화 세팅](#9-애드센스-수익-극대화-세팅)
10. [기타 필수 세팅 체크리스트](#10-기타-필수-세팅-체크리스트)

---

## 1. AI 블로그 콘텐츠 방향성 & 구성 원칙

### 1-1. AI 블로그가 다뤄야 할 핵심 주제 카테고리

```
Category A: AI 툴 리뷰 (Tool Review)
  - 단일 툴 심층 리뷰
  - A vs B 비교 리뷰
  - 무료 vs 유료 비교

Category B: AI 워크플로우 (Workflow)
  - 특정 업무에 AI 적용하는 법
  - AI 툴 스택 조합법
  - 자동화 파이프라인 구성

Category C: AI 뉴스 & 트렌드 해설 (News Commentary)
  - 신규 모델 출시 분석
  - 업계 이슈 역발상 해설
  - 정책/규제 임팩트 분석

Category D: AI 입문 가이드 (Beginner Guide)
  - 처음 쓰는 법
  - 자주 하는 실수
  - 용어 정리
```

### 1-2. 콘텐츠 원칙 (Codex/Claude Code 실행 기준)

```yaml
content_principles:
  minimum_word_count: 2000  # 구글 E-E-A-T 신뢰도 기준
  required_sections:
    - hook_paragraph        # 첫 150자 내 독자 문제 명시
    - tool_one_line_summary # 툴 1줄 요약 (AI 인용용)
    - who_is_this_for       # 대상 독자 명시
    - hands_on_evidence     # 직접 사용 증거 (스크린샷/수치)
    - free_vs_paid_boundary # 무료/유료 경계 설명
    - final_verdict         # 명확한 결론 1줄
    - related_posts_cta     # 내부 링크 최소 2개
  
  forbidden_patterns:
    - vague_superlatives    # "최고", "완벽한" 근거 없는 표현
    - feature_listing_only  # 기능 나열만 하는 구조
    - no_evidence_claims    # 직접 사용 증거 없는 주장
```

### 1-3. AI 주제 블로그에서 높은 RPM을 내는 틈새 키워드 방향

```
HIGH RPM 방향 (애드센스 기준 $3~$15 CPM):
  - "AI + B2B 업무 자동화" 키워드
  - "AI + 특정 직군 (마케터, 의사, 변호사)"
  - "AI 툴 가격 비교 / 구독 플랜"
  - "AI 코딩 도구 비교" (개발자 타깃)

AVOID (저 RPM, $0.5 미만):
  - 단순 ChatGPT 입문 키워드
  - AI 밈 / 유머 컨텐츠
  - "무료 AI 툴" 단독 키워드
```

---

## 2. 포스팅 구조 & 작성 패턴

### 2-1. 표준 포스팅 HTML 구조 (블로그스팟용)

```html
<!-- ===== POST BODY TEMPLATE (블로그스팟 body-only 버전) ===== -->

<!-- [1] 리드 섹션: 훅 + 1줄 요약 -->
<div class="yomi-lead-section">
  <p class="yomi-hook">
    <!-- 독자 문제/상황 공감 → 해결책 암시 (150자 이내) -->
  </p>
  <div class="yomi-tool-summary" itemscope itemtype="https://schema.org/SoftwareApplication">
    <strong>한 줄 요약:</strong>
    <span itemprop="description"><!-- 툴 핵심 기능 1줄 --></span>
  </div>
</div>

<!-- [2] 목차 (AEO: Featured Snippet 최적화) -->
<div class="yomi-toc">
  <h2>목차</h2>
  <ol>
    <li><a href="#what-is">이게 뭔데?</a></li>
    <li><a href="#who-for">누구에게 맞나</a></li>
    <li><a href="#hands-on">직접 써본 결과</a></li>
    <li><a href="#pricing">무료/유료 경계</a></li>
    <li><a href="#verdict">최종 판정</a></li>
  </ol>
</div>

<!-- [3] 본문 섹션들 -->
<section id="what-is">
  <h2><!-- 툴명 --> 이게 뭔데?</h2>
  <!-- 200~300자. FAQ Schema 타깃 -->
  <p><!-- 설명 --></p>
</section>

<section id="who-for">
  <h2>이런 사람에게 맞다 / 이런 사람은 패스</h2>
  <div class="yomi-two-col">
    <div class="yomi-pros">
      <h3>✅ 추천 대상</h3>
      <ul><!-- 리스트 --></ul>
    </div>
    <div class="yomi-cons">
      <h3>❌ 비추 대상</h3>
      <ul><!-- 리스트 --></ul>
    </div>
  </div>
</section>

<section id="hands-on">
  <h2>직접 써봤다: 실제 결과</h2>
  <!-- 반드시 스크린샷 alt텍스트에 키워드 포함 -->
  <figure>
    <img src="<!-- URL -->" 
         alt="<!-- 메인 키워드 + 사용 상황 설명 -->"
         loading="lazy"
         width="800" height="450">
    <figcaption><!-- 캡션: 수치/결과 명시 --></figcaption>
  </figure>
  <p><!-- 실제 경험 서술 --></p>
</section>

<section id="pricing">
  <h2>무료로 뭘 할 수 있나? 유료는 어디서부터?</h2>
  <table class="yomi-pricing-table">
    <thead>
      <tr><th>플랜</th><th>가격</th><th>핵심 기능</th><th>한계</th></tr>
    </thead>
    <tbody>
      <tr><td>무료</td><td>$0</td><td><!-- --></td><td><!-- --></td></tr>
      <tr><td>유료</td><td>$<!-- -->/월</td><td><!-- --></td><td><!-- --></td></tr>
    </tbody>
  </table>
</section>

<section id="verdict">
  <h2>최종 판정</h2>
  <div class="yomi-verdict-box">
    <p><strong>한 줄 결론:</strong> <!-- 명확한 추천/비추천 + 이유 --></p>
    <p><strong>점수:</strong> ⭐⭐⭐⭐☆ (4/5)</p>
  </div>
</section>

<!-- [4] 관련 포스팅 (내부 링크) -->
<div class="yomi-related">
  <h3>함께 읽으면 좋은 글</h3>
  <ul>
    <li><a href="<!-- URL -->"><!-- 관련글 제목 --></a></li>
    <li><a href="<!-- URL -->"><!-- 관련글 제목 --></a></li>
  </ul>
</div>
```

### 2-2. 3가지 포스팅 패턴 선택 기준

```
패턴 A: 단일 툴 리뷰
  언제: 신규 툴 출시 직후 (속보성)
  구조: 훅 → 정체 → 대상 → 직접사용 → 가격 → 판정
  목표 키워드: "[툴명] 리뷰", "[툴명] 사용법", "[툴명] 한국어"
  예상 RPM: 중간

패턴 B: A vs B 비교
  언제: 경쟁 툴 2개가 동일 카테고리에서 경쟁 중일 때
  구조: 비교 기준표 → 항목별 승자 → 상황별 추천 → 내 결론
  목표 키워드: "[툴A] vs [툴B]", "[카테고리] 최고 AI 툴"
  예상 RPM: 높음 (구매 의도 키워드)

패턴 C: 워크플로우 공개
  언제: 실제로 반복 사용하는 프로세스가 생겼을 때
  구조: 문제 → 사용 툴 스택 → 단계별 과정 → 결과 수치 → 응용
  목표 키워드: "AI로 [업무] 자동화", "[직군] AI 툴 추천"
  예상 RPM: 높음 (B2B 광고주 타깃)
```

---

## 3. SEO 세팅 (구글 검색 최적화)

### 3-1. 블로그스팟 기본 SEO 세팅

```html
<!-- 블로그스팟 테마 HTML <head> 섹션에 추가 -->

<!-- Canonical -->
<link rel="canonical" expr:href='data:post.url'/>

<!-- Open Graph -->
<meta property="og:type" content="article"/>
<meta expr:property='"og:title"' expr:content='data:post.title'/>
<meta expr:property='"og:url"' expr:content='data:post.url'/>
<meta expr:property='"og:description"' expr:content='data:post.snippet'/>
<meta property="og:site_name" content="<!-- 블로그명 -->"/>

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image"/>
<meta expr:name='"twitter:title"' expr:content='data:post.title'/>

<!-- Article 메타 -->
<meta expr:name='"article:published_time"' 
      expr:content='data:post.date.iso8601'/>
<meta name="article:author" content="<!-- 작성자명 -->"/>
```

### 3-2. 포스팅 내 SEO 체크리스트

```yaml
on_page_seo:
  title:
    format: "[메인 키워드] + [부가 설명] + [연도/상황]"
    example: "Claude AI 사용법: 2026년 무료로 최대한 활용하는 법"
    length: "50~60자 이내"
    
  meta_description:
    length: "150~160자"
    must_include:
      - main_keyword
      - benefit_statement
      - year_if_relevant
    
  headings:
    H1: 1개만, 타이틀과 동일하거나 유사
    H2: 3~6개, 섹션 구분
    H3: H2 하위, 세부 항목
    rule: "H2/H3에 LSI 키워드(연관 키워드) 자연스럽게 포함"
    
  images:
    alt_text: "메인 키워드 + 상황 설명 (40자 이내)"
    filename: "main-keyword-description.webp"
    format: "webp 우선, jpg 차선"
    lazy_loading: true
    
  internal_links:
    minimum: 2
    anchor_text: "설명형 앵커텍스트 (클릭 여기 X)"
    
  external_links:
    target: "공신력 있는 출처 (공식 사이트, 연구 논문)"
    attribute: 'rel="noopener"'
```

### 3-3. 키워드 타겟팅 전략

```
메인 키워드 (1개):
  - 검색량 300~3,000/월 (Ahrefs 기준) → 경쟁 적당
  - 너무 높으면 (10,000+) 레드오션

LSI 키워드 (5~8개):
  - 메인 키워드의 동의어/연관어
  - 본문에 자연스럽게 산포

롱테일 키워드 (H2/H3 헤딩에):
  - "X 툴 한국어 지원 되나요"
  - "X 툴 무료 한계가 뭔가요"
  - "X 툴 vs Y 툴 뭐가 나아요"
  → 이런 질문 형태 = Featured Snippet + AEO 동시 타깃
```

---

## 4. AEO 세팅 (Answer Engine Optimization)

> AEO = 구글 Featured Snippet, People Also Ask, 직접 답변 박스 점유 전략

### 4-1. Featured Snippet 점유 구조

```html
<!-- 질문형 H2 + 즉시 답변 패턴 -->
<h2>Claude AI는 무료로 사용할 수 있나요?</h2>
<p>
  <!-- ✅ 첫 문장에 직접 답변 -->
  Claude AI는 무료 플랜을 제공하며, 하루 제한 횟수 내에서 
  Claude Sonnet 모델을 무료로 사용할 수 있습니다.
  <!-- 이후 상세 설명 -->
  다만 Claude Opus 등 고급 모델은 Pro 플랜($20/월) 이상에서만 접근 가능합니다.
</p>

<!-- ✅ 정의형 Featured Snippet -->
<h2>GEO(Generative Engine Optimization)란?</h2>
<p>
  <strong>GEO(생성형 엔진 최적화)</strong>는 ChatGPT, Perplexity, 
  Google AI Overview 등 AI 기반 검색 엔진이 콘텐츠를 인용하도록 
  최적화하는 전략입니다. 기존 SEO가 구글 파란 링크를 
  타깃으로 한다면, GEO는 AI의 답변 소스가 되는 것을 목표로 합니다.
</p>
```

### 4-2. FAQ 섹션 필수 추가

```html
<!-- 포스팅 하단에 FAQ 섹션 추가 (People Also Ask 점유) -->
<section class="yomi-faq" itemscope itemtype="https://schema.org/FAQPage">

  <h2>자주 묻는 질문</h2>

  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
    <h3 itemprop="name"><!-- 질문 --></h3>
    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
      <p itemprop="text"><!-- 50~100자 직접 답변 --></p>
    </div>
  </div>

  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
    <h3 itemprop="name"><!-- 질문 2 --></h3>
    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
      <p itemprop="text"><!-- 답변 --></p>
    </div>
  </div>

</section>
```

### 4-3. AEO 작성 원칙

```yaml
aeo_writing_rules:
  
  answer_first:
    rule: "H2 질문 직후 첫 문장에 직접 답변"
    bad:  "Claude AI에 대해 알아보기 전에 먼저..."
    good: "Claude AI는 Anthropic이 만든 AI 어시스턴트로..."
  
  definition_format:
    pattern: "[용어]는 [핵심 정의]입니다. [부연 설명]."
    use_for: "AI 용어 설명 섹션"
  
  list_for_steps:
    rule: "프로세스/순서는 반드시 번호 목록으로"
    reason: "구글이 순서 있는 리스트를 Snippet으로 자주 추출"
  
  table_for_comparison:
    rule: "비교는 반드시 HTML <table>로 (마크다운 테이블 X)"
    reason: "구글이 테이블 Snippet 형태로 노출"
```

---

## 5. GEO / SGE 세팅 (AI 인용 최적화)

> GEO = ChatGPT, Perplexity, Claude, Gemini 등 AI가 답변 생성 시 내 글을 소스로 사용하도록 최적화

### 5-1. AI가 콘텐츠를 인용하는 조건

```
AI 인용 트리거 조건:
  1. 명확한 사실 진술 (수치, 날짜, 정의 포함)
  2. 출처 신뢰도 신호 (작성자 정보, 최신 날짜 표시)
  3. 구조화된 정보 (리스트, 테이블, 정의 박스)
  4. 원본 데이터 또는 직접 테스트 결과
  5. 권위 있는 외부 소스 인용 포함
```

### 5-2. GEO 최적화 콘텐츠 패턴

```html
<!-- ✅ 패턴 1: 명확한 사실 + 출처 -->
<p>
  Perplexity AI의 일일 활성 사용자는 2025년 기준 약 1,500만 명으로,
  전년 대비 3배 성장했습니다.
  <a href="https://출처URL" rel="noopener">
    <cite>출처: Perplexity 공식 발표 (2025.01)</cite>
  </a>
</p>

<!-- ✅ 패턴 2: 정의 박스 (AI 인용 최적화) -->
<div class="yomi-definition-box" 
     itemscope itemtype="https://schema.org/DefinedTerm">
  <strong itemprop="name">SGE (Search Generative Experience)</strong>
  <p itemprop="description">
    구글이 검색 결과 상단에 AI가 생성한 요약 답변을 제공하는 기능.
    2024년부터 "AI Overview"로 명칭 변경. 
    검색어에 대한 AI 종합 답변 + 소스 링크를 함께 제공한다.
  </p>
</div>

<!-- ✅ 패턴 3: 비교 데이터 테이블 -->
<table class="yomi-comparison-table">
  <caption>AI 챗봇 주요 비교 (2026년 기준)</caption>
  <thead>
    <tr>
      <th scope="col">서비스</th>
      <th scope="col">무료 모델</th>
      <th scope="col">유료 플랜</th>
      <th scope="col">특징</th>
    </tr>
  </thead>
  <tbody>
    <!-- 데이터 -->
  </tbody>
</table>
```

### 5-3. E-E-A-T 신호 강화 (AI 인용 신뢰도)

```html
<!-- 포스팅 상단 작성자 정보 박스 -->
<div class="yomi-author-box" 
     itemscope itemtype="https://schema.org/Person">
  <img src="<!-- 프로필 이미지 -->" 
       alt="요미 프로필" 
       itemprop="image">
  <div>
    <strong itemprop="name">요미 (Yomi)</strong>
    <span itemprop="jobTitle">AI 마케팅 전략가 & 콘텐츠 크리에이터</span>
    <p itemprop="description">
      AI 툴 직접 테스트 및 디지털 마케팅 전략 전문. 
      네이버·블로그스팟 운영 중.
    </p>
  </div>
</div>

<!-- 포스팅 최하단: 업데이트 날짜 명시 -->
<p class="yomi-update-notice">
  <time datetime="2026-06-14">최종 업데이트: 2026년 6월 14일</time>
  | 직접 테스트 기간: 2주
</p>
```

### 5-4. Perplexity / ChatGPT 인용 최적화 추가 설정

```yaml
perplexity_optimization:
  - robots.txt에서 PerplexityBot 허용 명시
  - 포스팅에 명확한 날짜 메타데이터
  - 외부 신뢰 소스 링크 최소 2개
  - 원본 데이터/테스트 결과 포함

chatgpt_browsing_optimization:
  - OpenAI GPTBot robots.txt 허용
  - 구조화된 헤딩 계층 (H1>H2>H3)
  - 각 섹션 100~200자 요약 가능한 밀도
```

---

## 6. JSON-LD 구조화 데이터 전체 템플릿

### 6-1. AI 툴 리뷰 포스팅용 JSON-LD

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Article",
      "@id": "<!-- 포스팅 URL -->#article",
      "headline": "<!-- 포스팅 제목 -->",
      "description": "<!-- 메타 디스크립션 -->",
      "datePublished": "<!-- YYYY-MM-DD -->",
      "dateModified": "<!-- YYYY-MM-DD -->",
      "author": {
        "@type": "Person",
        "name": "요미 (Yomi)",
        "url": "https://holyeverymoments.blogspot.com"
      },
      "publisher": {
        "@type": "Organization",
        "name": "요미의 오늘 이슈",
        "url": "https://holyeverymoments.blogspot.com",
        "logo": {
          "@type": "ImageObject",
          "url": "<!-- 로고 URL -->"
        }
      },
      "image": {
        "@type": "ImageObject",
        "url": "<!-- 대표 이미지 URL -->",
        "width": 1200,
        "height": 630
      },
      "mainEntityOfPage": {
        "@type": "WebPage",
        "@id": "<!-- 포스팅 URL -->"
      }
    },
    {
      "@type": "Review",
      "itemReviewed": {
        "@type": "SoftwareApplication",
        "name": "<!-- AI 툴명 -->",
        "applicationCategory": "AIApplication",
        "operatingSystem": "Web, iOS, Android",
        "offers": {
          "@type": "Offer",
          "price": "0",
          "priceCurrency": "USD",
          "description": "무료 플랜 제공"
        }
      },
      "reviewRating": {
        "@type": "Rating",
        "ratingValue": "<!-- 점수 (예: 4.2) -->",
        "bestRating": "5",
        "worstRating": "1"
      },
      "author": {
        "@type": "Person",
        "name": "요미 (Yomi)"
      },
      "reviewBody": "<!-- 100자 이상 리뷰 요약 -->"
    },
    {
      "@type": "FAQPage",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "<!-- 질문 1 -->",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "<!-- 답변 1 -->"
          }
        },
        {
          "@type": "Question",
          "name": "<!-- 질문 2 -->",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "<!-- 답변 2 -->"
          }
        }
      ]
    },
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        {
          "@type": "ListItem",
          "position": 1,
          "name": "홈",
          "item": "https://holyeverymoments.blogspot.com"
        },
        {
          "@type": "ListItem",
          "position": 2,
          "name": "AI 툴 리뷰",
          "item": "https://holyeverymoments.blogspot.com/search/label/AI툴리뷰"
        },
        {
          "@type": "ListItem",
          "position": 3,
          "name": "<!-- 포스팅 제목 -->",
          "item": "<!-- 포스팅 URL -->"
        }
      ]
    }
  ]
}
</script>
```

### 6-2. 블로그스팟에 JSON-LD 삽입 위치

```
방법 1 (권장): 포스팅 본문 맨 마지막에 직접 삽입
  → 각 포스팅마다 커스터마이즈 가능

방법 2: 테마 HTML의 <head> 내 조건부 삽입
  → 블로그스팟 b:if 태그로 포스팅 페이지에만 출력
  
  <b:if cond='data:view.isPost'>
    <!-- JSON-LD 공통 부분만 여기 -->
  </b:if>
```

---

## 7. 블로그스팟 HTML 템플릿 세팅

### 7-1. 필수 CSS (테마 Edit HTML에 추가)

```css
/* ===== YOMI BLOG CUSTOM CSS ===== */

/* 리드 섹션 */
.yomi-lead-section {
  background: #f8f9fa;
  border-left: 4px solid #0066cc;
  padding: 16px 20px;
  margin: 20px 0;
  border-radius: 0 8px 8px 0;
}

/* 툴 요약 박스 */
.yomi-tool-summary {
  background: #e8f4fd;
  padding: 12px 16px;
  border-radius: 6px;
  margin-top: 10px;
  font-size: 0.95em;
}

/* 목차 */
.yomi-toc {
  background: #fff;
  border: 1px solid #e0e0e0;
  padding: 16px 24px;
  border-radius: 8px;
  margin: 24px 0;
}
.yomi-toc h2 {
  font-size: 1em;
  margin: 0 0 10px 0;
  color: #333;
}
.yomi-toc ol {
  margin: 0;
  padding-left: 20px;
}
.yomi-toc li {
  margin: 6px 0;
}

/* 두 컬럼 레이아웃 */
.yomi-two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 16px 0;
}
@media (max-width: 600px) {
  .yomi-two-col { grid-template-columns: 1fr; }
}

/* 판정 박스 */
.yomi-verdict-box {
  background: #f0f7ff;
  border: 2px solid #0066cc;
  padding: 20px;
  border-radius: 8px;
  margin: 24px 0;
}

/* 정의 박스 (GEO 최적화) */
.yomi-definition-box {
  background: #fff8e1;
  border-left: 4px solid #f59e0b;
  padding: 16px 20px;
  margin: 20px 0;
  border-radius: 0 8px 8px 0;
}
.yomi-definition-box strong {
  display: block;
  font-size: 1.05em;
  margin-bottom: 8px;
  color: #92400e;
}

/* 가격 테이블 */
.yomi-pricing-table,
.yomi-comparison-table {
  width: 100%;
  border-collapse: collapse;
  margin: 20px 0;
  font-size: 0.9em;
}
.yomi-pricing-table th,
.yomi-comparison-table th {
  background: #0066cc;
  color: #fff;
  padding: 10px 12px;
  text-align: left;
}
.yomi-pricing-table td,
.yomi-comparison-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e0e0e0;
}
.yomi-pricing-table tr:nth-child(even) td,
.yomi-comparison-table tr:nth-child(even) td {
  background: #f8f9fa;
}

/* FAQ 섹션 */
.yomi-faq h3 {
  font-size: 1em;
  color: #1a1a2e;
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 6px;
}

/* 작성자 박스 */
.yomi-author-box {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #f8f9fa;
  padding: 16px;
  border-radius: 8px;
  margin: 32px 0 16px;
}
.yomi-author-box img {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  object-fit: cover;
}

/* 관련 포스팅 */
.yomi-related {
  border-top: 2px solid #e0e0e0;
  margin-top: 40px;
  padding-top: 20px;
}

/* 업데이트 표시 */
.yomi-update-notice {
  font-size: 0.82em;
  color: #666;
  margin-top: 24px;
}

/* 훅 문단 강조 */
.yomi-hook {
  font-size: 1.05em;
  line-height: 1.8;
  color: #1a1a2e;
}
```

### 7-2. 블로그스팟 robots.txt 설정

```
# Blogger 자동 생성 robots.txt는 직접 수정 불가
# Settings > Crawlers and indexing > Custom robots.txt 에서 설정

User-agent: *
Disallow: /search
Allow: /

# AI 봇 명시적 허용
User-agent: GPTBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Googlebot
Allow: /

Sitemap: https://holyeverymoments.blogspot.com/sitemap.xml
```

---

## 8. 조회수 폭발 전략

### 8-1. 속보성 포스팅 전략 (트래픽 스파이크)

```yaml
news_posting_strategy:
  trigger: "AI 툴 신규 출시 / 업데이트 / 논란"
  
  timing:
    goal: "공식 발표 후 24시간 이내 발행"
    keyword_target: "[툴명] [연도]", "[툴명] 출시", "[툴명] 후기"
  
  structure:
    - 뉴스 요약 (3줄)
    - 이게 왜 중요한가
    - 실제로 써봤다 (가능하면)
    - 기존 툴 대비 어떤가
    - 내 결론
    
  length: "1,500자 최소 (빠른 발행 우선)"
  update_plan: "3일 후 심층 내용 추가 & 날짜 업데이트"
```

### 8-2. 영원한 트래픽 키워드 (에버그린 콘텐츠)

```
에버그린 AI 키워드 패턴:
  "[AI 툴명] 무료 사용법"        → 지속 검색
  "[AI 툴명] 한국어 설정"        → 국내 특화 롱테일
  "[AI 툴명] 오류 해결"          → 문제 해결형 (전환율 높음)
  "AI로 [업무] 하는 법"         → 업무 자동화 수요
  "[AI 툴명] 대안 / 대체 서비스" → 툴 전환 수요

업데이트 주기:
  - 연 2회: 제목에 연도 포함된 글 날짜 업데이트
  - 분기 1회: 가격/기능 변경 사항 반영
  - 날짜 업데이트 시 Google Search Console에서 재크롤링 요청
```

### 8-3. SNS 유입 증폭 전략

```
채널별 전략:
  
  트위터(X):
    - 포스팅 핵심 인사이트 3줄 요약 → 링크
    - AI 관련 해시태그: #AI툴 #ChatGPT #인공지능
    - 발행 직후 + 3일 후 재포스팅
    
  카카오 오픈채팅:
    - AI 관련 채팅방에 가치 있는 정보로 공유
    - 직접 광고 X, 인사이트 공유 형식
    
  네이버 카페:
    - IT/마케팅/재테크 카페 타깃
    - 요약 + "전문 읽기" 링크 형식
    
  Pinterest:
    - 비교표, 인포그래픽 이미지 → 블로그 링크
    - AI 툴 비교 이미지는 핀터레스트 트래픽 효과적
```

### 8-4. 내부 링크 허브 구조 (트래픽 순환)

```
허브 포스팅 구조:

  [메인 허브] "2026년 AI 툴 완전 가이드"
       ↓ 내부 링크
  ├── [서브] ChatGPT 리뷰
  ├── [서브] Claude AI 리뷰  
  ├── [서브] Perplexity 리뷰
  ├── [서브] AI 글쓰기 툴 비교
  └── [서브] AI 이미지 생성 툴 비교

효과:
  - 신규 포스팅이 허브에서 링크 받아 빠른 인덱싱
  - 체류 시간 증가 → 이탈률 감소 → 랭킹 상승
  - 허브 포스팅이 도메인 권위 집중
```

---

## 9. 애드센스 수익 극대화 세팅

### 9-1. 광고 배치 최적화

```
최고 RPM 광고 배치 위치:

  1위: 본문 첫 단락 아래 (Above the fold 직후)
       → CTR 가장 높음
       
  2위: 목차와 첫 번째 H2 사이
       → 독자가 스크롤 시작 시점
       
  3위: 본문 중간 (글 전체 50% 지점)
       → 계속 읽는 독자 = 관심도 높음
       
  4위: 포스팅 맨 하단 (관련 포스팅 위)
       → 읽기 완료 독자 = 전환 의도 높음

피해야 할 위치:
  ❌ H1 제목 바로 위 (구글 정책 위반 가능)
  ❌ 광고 3개 이상 연속 배치
  ❌ 이미지 바로 위아래 (콘텐츠 단절)
```

### 9-2. 애드센스 코드 블로그스팟 삽입

```html
<!-- 방법 1: 테마 HTML에서 포스팅 본문 태그 내 조건부 삽입 -->
<b:if cond='data:view.isPost'>
  <!-- 광고 1: 본문 상단 -->
  <div class="yomi-ad-top">
    <!-- AdSense 자동 광고 or 수동 광고 코드 -->
    <ins class="adsbygoogle"
         style="display:block"
         data-ad-client="ca-pub-XXXXXXXX"
         data-ad-slot="XXXXXXXXXX"
         data-ad-format="auto"
         data-full-width-responsive="true"></ins>
    <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
  </div>
</b:if>

<!-- 방법 2: 포스팅 본문 HTML에 직접 삽입 (더 정밀한 위치 제어) -->
```

### 9-3. RPM 높이는 콘텐츠 전략

```yaml
high_rpm_content_strategy:
  
  target_advertisers:
    - SaaS 소프트웨어 회사 (AI 툴 경쟁사 광고)
    - B2B 서비스 (CRM, 마케팅 자동화)
    - 온라인 교육 플랫폼
    → 이 광고주들이 AI 키워드에 높은 입찰가 책정
    
  high_value_keywords_to_include:
    - "AI 자동화 솔루션"
    - "마케팅 AI 툴"
    - "비즈니스 AI 소프트웨어"
    - "AI 구독 서비스 비교"
    
  content_length:
    rule: "2,500자+ 포스팅이 RPM 1.5~2배 높음"
    reason: "더 많은 광고 슬롯 + 체류 시간 증가"
    
  update_old_posts:
    action: "저 RPM 포스팅에 고가치 섹션 추가"
    example: "가격 비교표, 기업용 플랜 설명 추가"
```

### 9-4. 애드센스 수익 트래킹

```
Google Analytics 4 연동 확인 항목:
  - 페이지별 RPM 확인 (AdSense 리포트)
  - 체류 시간 vs RPM 상관관계
  - 트래픽 소스별 RPM (구글 검색 > 소셜 > 직접)
  - 모바일 vs 데스크탑 RPM 차이

월간 최적화 루틴:
  1. 최고 트래픽 5개 포스팅 → 광고 위치 A/B 테스트
  2. RPM 하위 포스팅 → 콘텐츠 보강 or 광고 단위 변경
  3. 신규 포스팅 → 자동 광고 + 수동 1개 병행 테스트
```

---

## 10. 기타 필수 세팅 체크리스트

### 10-1. 블로그스팟 기본 세팅 완료 확인

```yaml
blogger_settings_checklist:
  
  basic:
    - [ ] 커스텀 도메인 연결 (선택 but 권장)
    - [ ] HTTPS 활성화 (Settings > HTTPS)
    - [ ] 검색 엔진에 블로그 공개 설정
    - [ ] Meta 태그 활성화
    
  search_preferences:
    - [ ] 메타 디스크립션 활성화
    - [ ] 커스텀 robots.txt 설정 완료
    - [ ] 커스텀 robots 헤더 태그 설정
    
  pages:
    - [ ] About 페이지 생성 (E-E-A-T용)
    - [ ] Contact 페이지 생성
    - [ ] Privacy Policy 페이지 (애드센스 필수)
    - [ ] Disclaimer 페이지
```

### 10-2. 서치콘솔 & 웹마스터 도구 등록

```
등록 필수 목록:
  1. Google Search Console
     → Sitemap: /sitemap.xml 제출
     
  2. Naver Search Advisor
     → 네이버 웹마스터도구 소유권 인증
     
  3. Bing Webmaster Tools
     → GSC 연동으로 자동 가져오기 가능
     
  4. Daum 검색등록
     → https://register.search.daum.net

사이트맵 제출 URL:
  https://holyeverymoments.blogspot.com/sitemap.xml
  https://holyeverymoments.blogspot.com/atom.xml
```

### 10-3. 페이지 속도 최적화

```
블로그스팟 속도 개선 체크리스트:

  이미지:
    - [ ] WebP 포맷 사용
    - [ ] 이미지 압축 (TinyPNG 등)
    - [ ] width/height 속성 명시 (CLS 방지)
    - [ ] loading="lazy" 적용 (첫 화면 제외)
    
  코드:
    - [ ] 불필요한 위젯 제거
    - [ ] 외부 폰트 최소화
    - [ ] 구글 폰트 사용 시 preconnect 추가
    
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
```

### 10-4. 핵심 지표 모니터링 루틴

```
주간 확인:
  □ Google Search Console → 클릭수/노출수/CTR 변화
  □ 새 포스팅 인덱싱 여부 확인
  □ 애드센스 RPM 트렌드

월간 확인:
  □ 상위 10개 포스팅 키워드 순위 변화
  □ 저성과 포스팅 리프레시 대상 선정
  □ 신규 AI 툴 트렌드 → 다음 달 콘텐츠 캘린더 수립
  □ 경쟁 블로그 포스팅 구조 벤치마킹
```

---

## QUICK REFERENCE: Codex / Claude Code용 실행 명령 요약

```
포스팅 생성 시 필수 체크:
  1. 키워드 확인 → 제목/H1 포함 여부
  2. JSON-LD 삽입 (Article + Review + FAQ + Breadcrumb)
  3. HTML 구조: 훅 → 목차 → 섹션들 → FAQ → 관련글
  4. FAQ 섹션: 최소 3개 질문 (AEO 타깃)
  5. 이미지: alt 텍스트에 키워드, WebP, lazy loading
  6. 내부 링크: 최소 2개
  7. 업데이트 날짜 명시
  8. 작성자 정보 박스 포함

robots.txt: GPTBot / PerplexityBot / ClaudeBot 허용
광고 위치: 본문 첫 단락 아래 + 중간 + 하단
RPM 최적화: 2,500자+, B2B 키워드, 가격 비교 섹션 포함
```

---

*작성: 요미의 오늘 이슈 | 블로그스팟 AI 블로그 운영 가이드 v1.0 | 2026.06*
