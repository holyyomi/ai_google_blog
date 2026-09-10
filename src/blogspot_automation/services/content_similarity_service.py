"""발행 본문 재탕(near-duplicate) 감지 — 문장 지문 기반.

배경: 골든패턴 슬롯의 LLM 보강이 실패하면 정적 템플릿 텍스트로 폴백되는데,
이 폴백 본문은 매번 동일하다. 그대로 두면 사실상 같은 글이 제목만 바꿔
반복 발행된다. 이를 막기 위해:

1. 발행 시 본문을 문장 단위 해시 지문(fingerprint)으로 발행 이력에 기록하고,
2. 새 후보의 지문과 과거 발행 글 지문의 겹침 비율을 계산해
3. 임계값 이상이면 품질 게이트가 발행을 차단한다.

LLM-judge 방식 대신 결정론적 해시 비교를 쓴다 — 비용 0, 재현 가능, 테스트 가능.
지문이 없는 과거 레코드(이 기능 도입 전 발행분)는 비교에서 제외되므로
도입 시점에 기존 이력과의 오탐은 발생하지 않는다.

2026-09-10 추가 — 6-gram Jaccard 지문:
문장 단위 해시(sentence_fingerprints)는 **완전일치**만 잡는다. 명사·조사만
바꿔 쓴 재사용은 문장 해시가 전혀 겹치지 않는데도 사실상 같은 문서다.
자매 블로그(오늘의이슈)에서 색인 0편의 원인을 6-gram Jaccard로 재측정했을 때
정상 블로그는 평균 0.005·최대 0.037, 색인 0 블로그는 평균 0.086·최대 0.510이
나왔다 — 문장 해시로는 안 보이던 차이다. 그래서 두 척도를 **병행**한다.
기존 sentence_fingerprints / max_overlap_ratio 계약은 그대로 두고
(발행 이력에 이미 645건 저장돼 있어 규칙을 바꾸면 전부 무효가 된다),
n-gram 쪽은 새 필드(content_ngram_fingerprint)로 따로 쌓는다.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# 정규화 후 이 길이 미만인 문장은 지문에서 제외 — 짧은 라벨/버튼 문구가
# 우연히 겹쳐 비율을 왜곡하는 것을 막는다.
_MIN_SENTENCE_CHARS = 15
# 레코드당 지문 상한 — publish_history.json 비대화 방지 (12 hex * 150 ≈ 2KB/글).
_MAX_FINGERPRINTS = 150

# ── 6-gram Jaccard 지문 (2026-09-10) ─────────────────────────────────────────
# 단어(어절) 6개 시퀀스. 6은 자매 repo(anti_google_blog)가 색인 0 원인 측정에
# 쓴 값과 동일 — 임계값 비교가 성립하려면 n이 같아야 한다.
_NGRAM_SIZE = 6
# 6-gram을 전부 저장하면 글 1편당 수천 개라 publish_history.json이 감당 못 한다.
# 해시 mod 샘플링으로 약 1/8만 남긴다. 샘플링은 교집합/합집합과 교환되므로
# (S(A∩B)=S(A)∩S(B), S(A∪B)=S(A)∪S(B)) 샘플끼리의 Jaccard가 원 집합 Jaccard의
# 불편추정치가 된다. 실측: 이 블로그 글 1편당 58~283개(≈1~4KB).
_NGRAM_SAMPLE_MODULUS = 8
# 샘플이 이보다 적으면 Jaccard가 요동친다 — 판정하지 않는다.
_MIN_NGRAM_SAMPLE = 12

# 모든 글에 똑같이 들어가는 정형 블록(면책·출처 안내·해시태그·맥락 리드).
# 실측(2026-09-10, runs/*/article.html 12편): 여기 문장들이 글마다 그대로
# 반복돼 문장 지문 공유 수를 중앙값 12개까지 밀어올리고 있었다. 이건 "재탕"이
# 아니라 템플릿 가구다. n-gram 지문은 **새 계약**이므로 처음부터 제외하고
# 센다(기존 sentence_fingerprints는 이력 호환 때문에 손대지 않는다).
_BOILERPLATE_SECTION_RE = re.compile(
    r"<section\b[^>]*(?:"
    r"id=['\"](?:AI_CITATION_SUMMARY|SOURCE_TRUST_BLOCK|ISSUE_CONTEXT_BLOCK|UPDATED_DATE_BLOCK)['\"]"
    r"|class=['\"][^'\"]*(?:yomi-citation-summary|yomi-source|yomi-note|yomi-hashtags)[^'\"]*['\"]"
    r")[^>]*>.*?</section>",
    flags=re.IGNORECASE | re.DOTALL,
)


def sentence_fingerprints(html: str, *, drop_boilerplate: bool = True) -> list[str]:
    """HTML 본문에서 문장 단위 지문 목록을 추출한다 (순서 유지, 중복 제거).

    2026-09-10: 정형 블록(출처 신뢰·인용 요약·해시태그·맥락 리드)을 기본 제외한다.
    그전에는 이 블록의 사이트 공통 면책 문장이 지문에 섞여, 후보별 공유 문장 수
    중앙값 12·최대 14를 만들고 있었다. 재탕이 아니라 모든 글에 붙는 고정 문구인데도
    중복 점수를 밀어올려, 임계값을 실질적으로 조일 수 없게 만들던 원인이다.

    이력에 저장된 기존 지문(정형 포함)과 섞여도 안전하다 — containment는
    |후보∩과거| / |후보| 라서 후보에서 정형이 빠지면 분자·분모가 함께 줄어
    비율이 낮아지는 방향이다(오탐 감소). 백필은 필요하지 않다.
    """
    html = _BOILERPLATE_SECTION_RE.sub(" ", html or "") if drop_boilerplate else (html or "")
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    fingerprints: list[str] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        normalized = re.sub(r"[\s\W_]+", "", sentence).lower()
        if len(normalized) < _MIN_SENTENCE_CHARS:
            continue
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        if digest in seen:
            continue
        seen.add(digest)
        fingerprints.append(digest)
        if len(fingerprints) >= _MAX_FINGERPRINTS:
            break
    return fingerprints


def max_overlap_ratio(
    candidate_fingerprints: list[str] | set[str],
    history_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """후보 지문과 과거 발행 레코드 지문의 최대 겹침 비율을 반환한다.

    비율 = |후보 ∩ 과거| / |후보| — "이 후보 본문의 몇 %가 과거 글에 이미
    있었는가"를 뜻한다. 지문이 없는 레코드는 건너뛴다.

    2026-09-10: `shared_sentences`(절대 공유 문장 수의 최대값)를 함께 돌려준다.
    비율만 보면 긴 글일수록 같은 문장 수를 공유해도 비율이 희석돼 통과한다 —
    "글을 길게 쓰면 재탕이 허용되는" 구멍이라 절대 개수 상한을 따로 둔다.
    """
    candidate_set = set(candidate_fingerprints or [])
    best_ratio = 0.0
    best_title = ""
    compared = 0
    max_shared = 0
    max_shared_title = ""
    if not candidate_set:
        return {
            "ratio": 0.0,
            "matched_title": "",
            "compared_records": 0,
            "shared_sentences": 0,
            "shared_sentences_title": "",
        }

    for record in history_records or []:
        if not isinstance(record, dict):
            continue
        past = record.get("content_fingerprint")
        if not isinstance(past, list) or not past:
            continue
        compared += 1
        shared = len(candidate_set & set(past))
        ratio = shared / len(candidate_set)
        if ratio > best_ratio:
            best_ratio = ratio
            best_title = str(record.get("title") or record.get("selected_topic") or "")
        if shared > max_shared:
            max_shared = shared
            max_shared_title = str(
                record.get("title") or record.get("selected_topic") or ""
            )

    return {
        "ratio": round(best_ratio, 4),
        "matched_title": best_title,
        "compared_records": compared,
        "shared_sentences": max_shared,
        "shared_sentences_title": max_shared_title,
    }


def ngram_fingerprints(html: str, *, n: int = _NGRAM_SIZE) -> list[str]:
    """본문 6단어 시퀀스 지문 목록 — 명사 치환형 재사용 탐지용 (정렬, 중복 제거).

    `sentence_fingerprints`와 **다른 계약**이다:
      · 정형 블록(면책·출처·해시태그·맥락 리드)을 먼저 걷어낸다.
      · 문장 경계가 아니라 6어절 슬라이딩 윈도우를 본다 — 문장을 쪼개거나
        명사만 갈아끼운 재사용도 시퀀스가 남아서 잡힌다.
      · 해시 mod 샘플링으로 약 1/8만 저장한다(_NGRAM_SAMPLE_MODULUS).

    이 규칙을 바꾸면 발행 이력에 저장된 `content_ngram_fingerprint`와 비교가
    깨진다. 바꿀 때는 이력을 재생성하거나, 새 필드명을 쓸 것.
    """
    stripped = _BOILERPLATE_SECTION_RE.sub(" ", html or "")
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    if not text:
        return []

    tokens = [
        token
        for token in (part.strip(" ,.-:;!?\"'“”‘’()[]") for part in text.split())
        if token
    ]
    if len(tokens) < n:
        return []

    fingerprints: set[str] = set()
    for index in range(len(tokens) - n + 1):
        digest = hashlib.sha1(
            " ".join(tokens[index:index + n]).encode("utf-8")
        ).hexdigest()
        # mod 샘플링 — 해시 마지막 바이트 기준. 원 집합의 약 1/8.
        if int(digest[-2:], 16) % _NGRAM_SAMPLE_MODULUS:
            continue
        fingerprints.add(digest[:12])
    return sorted(fingerprints)


def max_ngram_jaccard(
    candidate_fingerprints: list[str] | set[str],
    history_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """후보 6-gram 지문과 과거 발행 레코드의 최대 **Jaccard** 유사도.

    문장 게이트가 쓰는 containment(|A∩B|/|A|)가 아니라 |A∩B|/|A∪B| 다 —
    임계값 근거가 된 실측이 Jaccard로 측정됐기 때문에 같은 척도를 써야 한다.

    표본이 `_MIN_NGRAM_SAMPLE` 미만인 쪽(후보든 과거든)은 요동이 커서
    비교에서 제외한다. 그래서 `compared_records`가 0인 것과 "깨끗해서 0.0"인
    것은 전혀 다른 상태다 — 호출부는 반드시 이 필드를 함께 봐야 한다.
    """
    candidate_set = set(candidate_fingerprints or [])
    result: dict[str, Any] = {
        "jaccard": 0.0,
        "matched_title": "",
        "compared_records": 0,
        "candidate_sample_size": len(candidate_set),
        "sample_too_small": len(candidate_set) < _MIN_NGRAM_SAMPLE,
    }
    if result["sample_too_small"]:
        return result

    best = 0.0
    best_title = ""
    compared = 0
    for record in history_records or []:
        if not isinstance(record, dict):
            continue
        past = record.get("content_ngram_fingerprint")
        if not isinstance(past, list):
            continue
        past_set = set(past)
        if len(past_set) < _MIN_NGRAM_SAMPLE:
            continue
        compared += 1
        union = len(candidate_set | past_set)
        if not union:
            continue
        score = len(candidate_set & past_set) / union
        if score > best:
            best = score
            best_title = str(record.get("title") or record.get("selected_topic") or "")

    result["jaccard"] = round(best, 4)
    result["matched_title"] = best_title
    result["compared_records"] = compared
    return result
