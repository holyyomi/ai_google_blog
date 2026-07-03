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


def sentence_fingerprints(html: str) -> list[str]:
    """HTML 본문에서 문장 단위 지문 목록을 추출한다 (순서 유지, 중복 제거)."""
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
    """
    candidate_set = set(candidate_fingerprints or [])
    best_ratio = 0.0
    best_title = ""
    compared = 0
    if not candidate_set:
        return {"ratio": 0.0, "matched_title": "", "compared_records": 0}

    for record in history_records or []:
        if not isinstance(record, dict):
            continue
        past = record.get("content_fingerprint")
        if not isinstance(past, list) or not past:
            continue
        compared += 1
        ratio = len(candidate_set & set(past)) / len(candidate_set)
        if ratio > best_ratio:
            best_ratio = ratio
            best_title = str(record.get("title") or record.get("selected_topic") or "")

    return {
        "ratio": round(best_ratio, 4),
        "matched_title": best_title,
        "compared_records": compared,
    }
