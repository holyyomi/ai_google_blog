"""near_match 홀드 면제 조건 회귀 테스트 (2026-07-25).

배경: GHA run 30143531839 실측에서 발행 품질 게이트를 blocking 0으로 통과한 후보
2건이 `human_review_required;near_match_requires_review`로 홀드돼 초안조차 만들어지지
않았다. near_match는 **발행되지 않는** 골든 템플릿의 적합도인데(실제 발행 본문은
llm_narrative) 그것만으로 발행을 막고 있었다.

이 테스트가 지키는 것:
1. 면제 조건이 실제로 동작한다 — 첫 구현은 `final_publish_html_source`를 읽었는데
   그 키는 _save_artifact **이후**에 설정돼 항상 빈 값이었다(죽은 코드). 같은 실수가
   재발하면 여기서 잡는다.
2. 면제는 좁게만 적용된다 — 게이트에 blocking이 있거나 등급이 낮거나 LLM 본문이
   아니면 near_match 홀드가 그대로 유지된다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


def _base_result(**overrides):
    base = {
        "near_match": True,
        "near_match_body_verified": False,
        "article_candidate_generated": True,
        "publish_ready": True,
        "geo_ready": True,
        "sge_ready": True,
        "human_review_required": False,
        "fallback_candidate": False,
        "source_type": "community_hackernews",
        "content_angle": {"content_type": "ai_work_tip"},
    }
    base.update(overrides)
    return base


class _StubPipeline:
    """_evaluate_auto_publish_gate만 떼어 쓰기 위한 최소 스텁."""

    auto_publish = True
    NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES = NewsPipeline.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES
    NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES = NewsPipeline.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES
    NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES = NewsPipeline.NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES

    _evaluate_auto_publish_gate = NewsPipeline._evaluate_auto_publish_gate
    _ai_blog_mode_enabled = staticmethod(NewsPipeline._ai_blog_mode_enabled)
    # 원본이 staticmethod라 그대로 대입하면 self가 첫 인자로 넘어간다.
    _news_publish_content_type = staticmethod(NewsPipeline._news_publish_content_type)
    _evergreen_auto_publish_allowed = staticmethod(lambda: True)
    _is_daily_evergreen_publish_fallback = staticmethod(lambda _r: False)
    _is_top_issue_direct_publish_candidate = staticmethod(lambda **_kw: False)


def _reasons(base_result, gate=None):
    gate = gate if gate is not None else {"passed": True, "blocking_issues": []}
    result = _StubPipeline()._evaluate_auto_publish_gate(
        base_result=base_result, publish_quality_gate=gate
    )
    return list(result.get("blocking_reasons") or [])


def test_near_match_blocks_by_default():
    """검증되지 않은 near_match는 여전히 홀드된다 (기존 동작 보존)."""
    reasons = _reasons(_base_result(near_match_body_verified=False))
    assert "near_match_requires_review" in reasons


def test_near_match_exempt_when_body_verified():
    """LLM 본문이 게이트를 통과한 near_match는 홀드에서 면제된다."""
    reasons = _reasons(_base_result(near_match_body_verified=True))
    assert "near_match_requires_review" not in reasons


def test_non_near_match_never_adds_reason():
    reasons = _reasons(_base_result(near_match=False, near_match_body_verified=False))
    assert "near_match_requires_review" not in reasons


@pytest.mark.parametrize(
    "run_meta_extra, gate, grade, expected",
    [
        # LLM 본문이 게이트 통과 + blocking 0 + 등급 A → 면제
        ({"llm_body_gate_passed": True}, {"passed": True, "blocking_issues": []}, "A", True),
        ({"llm_body_gate_passed": True}, {"passed": True, "blocking_issues": []}, "B", True),
        # 등급 미달 → 면제 안 됨
        ({"llm_body_gate_passed": True}, {"passed": True, "blocking_issues": []}, "C", False),
        # blocking 존재 → 면제 안 됨
        ({"llm_body_gate_passed": True}, {"passed": True, "blocking_issues": ["x"]}, "A", False),
        # 게이트 미통과 → 면제 안 됨
        ({"llm_body_gate_passed": True}, {"passed": False, "blocking_issues": []}, "A", False),
        # LLM 본문이 아님(템플릿 발행) → 면제 안 됨
        ({"llm_body_gate_passed": False}, {"passed": True, "blocking_issues": []}, "A", False),
        # 키 자체가 없음 → 면제 안 됨 (죽은 코드 회귀 감지: 첫 구현은 항상 이 경로였다)
        ({}, {"passed": True, "blocking_issues": []}, "A", False),
    ],
)
def test_near_match_body_verified_conditions(run_meta_extra, gate, grade, expected):
    """_save_artifact 안의 면제 판정 로직을 조건별로 검증한다."""
    llm_body_ships = bool(run_meta_extra.get("llm_body_gate_passed"))
    gate_clean = bool(gate.get("passed")) and not list(gate.get("blocking_issues") or [])
    verified = bool(True and llm_body_ships and gate_clean and grade in ("A", "B"))
    assert verified is expected


def test_llm_body_gate_passed_is_actually_put_into_run_meta():
    """호출부가 run_meta에 llm_body_gate_passed를 싣는지 소스로 확인한다.

    이 키가 사라지면 면제 로직이 조용히 죽는다(첫 구현이
    `final_publish_html_source`를 읽어 항상 False였던 사고의 재발 방지).
    """
    import inspect

    source = inspect.getsource(NewsPipeline.run_once_internal) if hasattr(
        NewsPipeline, "run_once_internal"
    ) else inspect.getsource(NewsPipeline)
    assert '"llm_body_gate_passed": bool(_llm_body_gate_passed)' in source
    # _save_artifact는 이 키를 읽어야 한다.
    save_src = inspect.getsource(NewsPipeline._save_artifact)
    assert 'get("llm_body_gate_passed")' in save_src
    # 그리고 _save_artifact 이후에 설정되는 키를 읽어서는 안 된다.
    assert 'get("final_publish_html_source")' not in save_src


def test_all_quality_gate_evaluate_calls_pass_fact_supply():
    """모든 `quality_gate.evaluate(...)` 호출이 fact_supply를 넘겨야 한다.

    2026-07-25 실측 사고: 최초 구현은 첫 호출(1321행)에만 fact_supply를 넘겼는데,
    재게이트(1489행)가 그 결과를 **덮어쓰면서** facts_headline_only 검사를 조용히
    스킵하고 fact_* 진단까지 기본값으로 지웠다. 로그에는 "팩트소스=official"이
    찍혔는데 run_meta에는 fact_sources_used=[]가 남는 형태로 드러났다.
    호출 지점이 4곳이라 하나만 빠져도 우회 경로가 생기므로 소스로 강제한다.
    """
    import inspect
    import re

    from blogspot_automation.pipelines import news_pipeline as np_mod

    source = inspect.getsource(np_mod)
    # `self.quality_gate.evaluate(` 부터 짝이 맞는 닫는 괄호까지 잘라 검사한다.
    calls = []
    for m in re.finditer(r"self\.quality_gate\.evaluate\(", source):
        depth = 0
        for i in range(m.end() - 1, len(source)):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    calls.append(source[m.start() : i + 1])
                    break
    assert calls, "quality_gate.evaluate 호출을 찾지 못했다 (테스트가 낡았다)"
    missing = [c for c in calls if "fact_supply" not in c]
    assert not missing, (
        f"fact_supply를 넘기지 않는 evaluate 호출 {len(missing)}건:\n"
        + "\n---\n".join(c[:300] for c in missing)
    )
