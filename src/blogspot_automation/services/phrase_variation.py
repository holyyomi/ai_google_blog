"""글마다 다른 보일러플레이트 문장을 만들기 위한 결정적 조합기.

배경 (2026-09-10 실측): holyyomiai 발행글 47편 전문을 내려받아 문장 단위로
세어 보니, 아래처럼 **토씨 하나 안 틀리고 같은 문장**이 반복되고 있었다.

    42/47  Where can you verify the current details?
    33/47  Test it on one low-stakes task first, review the output yourself, ...
    20/47  Plan limits and pricing match what was publicly listed as of this writing.
    16/47  AI output still needs human review before you use it for real work.

원인은 "변주 풀"의 크기다. 기존 코드는 3~5개짜리 고정 튜플에서
`md5(seed) % len(pool)` 로 하나를 골랐다 — 풀이 3개면 47편 중 약 16편이 같은
문장을 받는다. 구글은 페이지에서 boilerplate 를 걷어낸 뒤 남는 고유 본문으로
가치를 판단하므로, 이 반복은 "크롤링됨 - 색인 안 함" 의 직접 원인이 된다.

해결은 두 단계다.
1) **본문에서 뽑아 쓴다** (최우선). 호출부가 본문 사실을 넘길 수 있으면 템플릿을
   아예 쓰지 않는다.
2) 그래도 템플릿이 필요한 자리(면책·주의 문구처럼 법적/품질상 지울 수 없는 것)는
   **여러 개의 독립 조각 풀을 각각 다른 salt 로 골라 조립**한다. 조각 풀이
   7개씩 3자리면 343가지가 나오고, 한 조각만 봐도 47편에서 같은 조각을 받는 글은
   6~7편으로 떨어진다. 문장 전체가 겹칠 확률은 사실상 0에 가깝다.

이 모듈은 2)를 담당한다. 선택은 여전히 **결정적**이다 — 같은 글(seed)은 언제
렌더해도 같은 문장을 얻는다(재렌더 시 문장이 흔들려 게이트가 오작동하는 것 방지).
"""

from __future__ import annotations

import hashlib
from itertools import product
from typing import Iterable, Sequence


def variant_index(seed: str, salt: str, modulo: int) -> int:
    """seed+salt 로 결정적 인덱스를 만든다. modulo <= 0 이면 0."""
    if modulo <= 0:
        return 0
    digest = hashlib.md5(f"{salt}\x1f{seed or 'seed'}".encode("utf-8")).hexdigest()
    return int(digest, 16) % modulo


def pick(pool: Sequence[str], seed: str, salt: str) -> str:
    """풀에서 결정적으로 하나 고른다."""
    if not pool:
        return ""
    return pool[variant_index(seed, salt, len(pool))]


def compose(seed: str, salt: str, *pools: Sequence[str], joiner: str = " ") -> str:
    """여러 조각 풀에서 **각각 다른 salt** 로 골라 이어붙인다.

    조각마다 salt 를 달리해야 조합 수가 곱으로 늘어난다. 같은 salt 를 쓰면
    모든 조각이 같은 인덱스로 몰려 풀 하나 크기의 변주밖에 못 얻는다.
    """
    parts = [
        pick(pool, seed, f"{salt}#{i}")
        for i, pool in enumerate(pools)
        if pool
    ]
    return joiner.join(p for p in parts if p).strip()


def all_compositions(*pools: Sequence[str], joiner: str = " ") -> tuple[str, ...]:
    """compose() 가 만들 수 있는 모든 문장. 템플릿 문구 판별용 집합에 쓴다.

    (예: lede 가 템플릿 상투어로 시작하지 못하게 막을 때, 실제로 나올 수 있는
    문장을 전부 알고 있어야 걸러낼 수 있다.)
    """
    live = [tuple(p) for p in pools if p]
    if not live:
        return ()
    return tuple(joiner.join(combo) for combo in product(*live))


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = " ".join(str(value or "").split()).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(" ".join(str(value).split()).strip())
    return out
