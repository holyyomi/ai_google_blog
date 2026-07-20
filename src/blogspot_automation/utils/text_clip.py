"""단어 경계 안전 절단 유틸.

2026-07-20 라이브 감사 실측: 하드 슬라이스(`text[:N]`)가 본문·앵커·주제문에
"rollout can vary by acco", "pricing starts J", "actually sends t" 같은
단어 중간 절단을 그대로 노출시켰다. 잘라야 하는 모든 표시용 문자열은
이 헬퍼를 거쳐 단어 경계에서만 잘라야 한다.
"""
from __future__ import annotations


def clip_at_word_boundary(text: str, max_len: int, *, ellipsis: str = "") -> str:
    """max_len 이내로 자르되 단어 중간에서는 절대 자르지 않는다.

    - text가 max_len 이하면 그대로 반환.
    - 초과하면 max_len 안의 마지막 공백에서 자르고 꼬리 구두점을 정리한다.
    - 공백이 전혀 없으면(한 단어가 max_len 초과) 어쩔 수 없이 하드컷.
    - ellipsis를 주면 잘렸을 때만 덧붙인다(덧붙여도 max_len+len(ellipsis) 이내).
    """
    compact = " ".join((text or "").split()).strip()
    if len(compact) <= max_len:
        return compact
    clipped = compact[:max_len]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped.rstrip(" ,.;:-–—·")
    if ellipsis and clipped:
        return clipped + ellipsis
    return clipped
