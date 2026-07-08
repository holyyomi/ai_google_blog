"""merge_publish_history 테스트 — 브랜치 무관 원장 병합의 안전성.

지키는 회귀(2026-07-08 감사): feature 브랜치 발행 기록이 main 원장에 합류하지
못해 dedup이 장님이 되던 문제. 병합은 (1) 양쪽 어느 기록도 잃지 않고
(2) 완전 동일 레코드만 접고 (3) 시간순을 유지해야 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from merge_publish_history import load_records, merge_ledgers, record_timestamp  # noqa: E402


def _r(run_at: str, topic: str, **extra) -> dict:
    return {"run_at": run_at, "selected_topic": topic, "status": "published", **extra}


def test_disjoint_union_keeps_everything() -> None:
    base = [_r("2026-07-01T01:00:00", "주제A")]
    incoming = [_r("2026-07-02T01:00:00", "주제B")]
    merged, added = merge_ledgers(base, incoming)
    assert [m["selected_topic"] for m in merged] == ["주제A", "주제B"]
    assert added == 1


def test_exact_duplicates_collapse_but_variants_survive() -> None:
    # 완전 동일 레코드만 접는다 — 같은 주제의 "다른 시도"(다른 상태/시각)는 보존.
    shared = _r("2026-07-01T01:00:00", "주제A")
    variant = _r("2026-07-01T02:00:00", "주제A", status="blocked_by_quality_gate")
    merged, added = merge_ledgers([shared], [dict(shared), variant])
    assert len(merged) == 2
    assert added == 1


def test_main_gained_records_after_branch_point_not_lost() -> None:
    """감사에서 지적한 유실 시나리오: 브랜치가 갈라진 뒤 main이 얻은 기록.

    (과거 방식이 '런의 파일로 main을 덮어쓰기'였다면 main의 새 기록이 사라진다 —
    합집합 병합은 양쪽을 모두 보존해야 한다.)
    """
    branch_point = _r("2026-07-01T01:00:00", "공통")
    main_gained = _r("2026-07-03T01:00:00", "main에서 스케줄 발행")
    branch_gained = _r("2026-07-02T01:00:00", "브랜치에서 리허설 발행")
    merged, _ = merge_ledgers(
        [branch_point, main_gained], [branch_point, branch_gained]
    )
    topics = [m["selected_topic"] for m in merged]
    assert topics == ["공통", "브랜치에서 리허설 발행", "main에서 스케줄 발행"]  # 시간순


def test_chronological_order_across_sources() -> None:
    merged, _ = merge_ledgers(
        [_r("2026-07-05T00:00:00", "늦은것")],
        [_r("2026-07-01T00:00:00", "이른것"), {"date": "2026-07-03", "selected_topic": "date만"}],
    )
    assert [m["selected_topic"] for m in merged] == ["이른것", "date만", "늦은것"]


def test_timestamp_fallback_order() -> None:
    assert record_timestamp({"run_at": "2026-07-08T01:00:00"}) == "2026-07-08T01:00:00"
    assert record_timestamp({"published_at": "2026-07-08T02:00:00"}) == "2026-07-08T02:00:00"
    assert record_timestamp({"date": "2026-07-08"}) == "2026-07-08"
    assert record_timestamp({}) == ""


def test_load_records_tolerates_missing_and_corrupt(tmp_path) -> None:
    assert load_records(tmp_path / "없는파일.json") == []
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{배열이 아님", encoding="utf-8")
    assert load_records(corrupt) == []
    not_list = tmp_path / "dict.json"
    not_list.write_text(json.dumps({"records": []}), encoding="utf-8")
    assert load_records(not_list) == []


def test_cli_end_to_end(tmp_path) -> None:
    """스크립트를 실제 CLI로 실행 — 워크플로우가 쓰는 그대로."""
    import subprocess

    base = tmp_path / "base.json"
    incoming = tmp_path / "incoming.json"
    out = tmp_path / "out.json"
    base.write_text(json.dumps([_r("2026-07-01T00:00:00", "A")]), encoding="utf-8")
    incoming.write_text(
        json.dumps([_r("2026-07-01T00:00:00", "A"), _r("2026-07-02T00:00:00", "B")]),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "merge_publish_history.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--base", str(base), "--incoming", str(incoming), "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert "new from incoming=1" in proc.stdout
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert [m["selected_topic"] for m in merged] == ["A", "B"]
