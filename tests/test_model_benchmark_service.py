from __future__ import annotations

import json

import pytest

from blogspot_automation.services import model_benchmark_service as mbs
from blogspot_automation.services.model_benchmark_service import (
    BENCHMARK_PROMPT_VERSION,
    BenchmarkResult,
    BenchmarkRun,
    ModelBenchmarkService,
    render_benchmark_table_html,
)


@pytest.fixture(autouse=True)
def _benchmark_env(monkeypatch):
    monkeypatch.setenv("ENABLE_MODEL_BENCHMARK", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_BENCHMARK_MAX_MODELS", raising=False)
    monkeypatch.delenv("MODEL_BENCHMARK_MAX_AGE_DAYS", raising=False)


def _ok_response(text: str, *, completion_tokens: int = 120) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"completion_tokens": completion_tokens},
    }


# 20단어 미만은 "답변 불충분"으로 처리되므로 픽스처도 실제 답변 길이여야 한다.
_THREE_PARAGRAPHS = (
    "A rate limit is a cap on how many requests you may send in a given window of time.\n\n"
    "Providers use it so that one heavy user cannot slow the service down for everyone else.\n\n"
    "When you cross the cap the service replies with an error instead of an answer for a while."
)


def test_targets_come_from_the_real_provider_list(monkeypatch):
    """모델 목록을 여기 따로 적으면 본문 생성 모델을 바꿔도 표는 옛 모델을 가리킨다."""
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/some-new-model:free")
    targets = ModelBenchmarkService.targets()

    assert targets, "무료 provider가 하나도 안 잡혔다"
    assert all(target["free"] for target in targets)
    assert "vendor/some-new-model:free" in [target["resolved_model"] for target in targets]
    # 유료 provider는 절대 측정 대상이 아니다(무료 전용 정책).
    assert all("openai_api_fallback" != target.get("name") for target in targets)


def test_paid_provider_excluded_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "paid-key")
    names = [target.get("name") for target in ModelBenchmarkService.targets()]
    assert "openai_api_fallback" not in names


def test_measure_records_latency_words_and_format(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_post(*, endpoint, headers, payload, timeout):
        calls.append({"endpoint": endpoint, "payload": payload, "timeout": timeout})
        return _ok_response(_THREE_PARAGRAPHS), 12.34

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion", fake_post
    )
    monkeypatch.setenv("MODEL_BENCHMARK_MAX_MODELS", "2")

    run = ModelBenchmarkService(result_dir=tmp_path).measure()

    assert run is not None
    assert len(run.results) == 2
    first = run.results[0]
    assert first.ok is True
    assert first.seconds == 12.3
    assert first.words == 53
    assert first.followed_format is True
    assert calls[0]["endpoint"].endswith("/chat/completions")
    assert calls[0]["payload"]["messages"][1]["content"] == mbs.BENCHMARK_PROMPT


def test_failure_is_recorded_not_hidden(monkeypatch, tmp_path):
    """실패한 모델을 표에서 빼면 '무료 모델은 다 잘 된다'는 거짓말이 된다."""

    def fake_post(*, endpoint, headers, payload, timeout):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion", fake_post
    )
    run = ModelBenchmarkService(result_dir=tmp_path).measure()

    assert run is not None
    assert all(result.ok is False for result in run.results)
    assert run.has_any_success is False
    assert run.results[0].error


def test_all_failed_run_is_not_saved_and_yields_no_table(monkeypatch, tmp_path):
    def fake_post(*, endpoint, headers, payload, timeout):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion", fake_post
    )
    service = ModelBenchmarkService(result_dir=tmp_path)

    assert service.measure_or_reuse() is None
    assert list(tmp_path.glob("*.json")) == [], "측정 전멸인데 파일이 저장됐다"


def test_empty_response_counts_as_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: (_ok_response("   "), 3.0),
    )
    run = ModelBenchmarkService(result_dir=tmp_path).measure()
    assert run.results[0].ok is False
    assert run.results[0].error == "empty response"


def test_cut_off_answer_is_not_reported_as_a_fast_answer(monkeypatch, tmp_path):
    """실측(2026-08-26): 토큰은 377을 쓰고 본문은 3단어로 잘려 온 응답이 있었다.

    그걸 ok=True로 실으면 표가 "2.4초에 3단어"라는 거짓 인상을 준다.
    """
    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: (_ok_response("An API rate limit", completion_tokens=377), 2.4),
    )
    result = ModelBenchmarkService(result_dir=tmp_path).measure().results[0]

    assert result.ok is False
    assert "cut off" in result.error
    assert result.completion_tokens == 377


def test_routed_model_is_recorded_when_the_endpoint_reroutes(monkeypatch, tmp_path):
    """openrouter/free는 호출마다 실제 모델이 달라진다 — 무엇을 쟀는지 남겨야 한다."""
    response = _ok_response(_THREE_PARAGRAPHS)
    response["model"] = "minimax/minimax-m3:free"
    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: (response, 5.0),
    )
    monkeypatch.setenv("MODEL_BENCHMARK_MAX_MODELS", "1")
    result = ModelBenchmarkService(result_dir=tmp_path).measure().results[0]

    assert result.routed_model == "minimax/minimax-m3:free"
    assert "routed to minimax/minimax-m3:free" in result.display_model
    assert result.display_model in render_benchmark_table_html(
        BenchmarkRun("2026-08-26", BENCHMARK_PROMPT_VERSION, (result,))
    )


def test_recent_result_is_reused_instead_of_remeasuring(monkeypatch, tmp_path):
    from datetime import date

    payload = BenchmarkRun(
        measured_on=date.today().isoformat(),
        prompt_version=BENCHMARK_PROMPT_VERSION,
        results=(
            BenchmarkResult("m", "m", True, 4.0, 100, 120, True, ""),
        ),
    ).to_dict()
    (tmp_path / f"{date.today().isoformat()}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    def explode(**kwargs):
        raise AssertionError("캐시가 있는데 다시 측정했다 — 실행 시간이 그만큼 늘어난다")

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion", explode
    )
    run = ModelBenchmarkService(result_dir=tmp_path).measure_or_reuse()
    assert run is not None
    assert run.results[0].model == "m"


def test_stale_result_is_not_reused(monkeypatch, tmp_path):
    payload = BenchmarkRun(
        measured_on="2020-01-01",
        prompt_version=BENCHMARK_PROMPT_VERSION,
        results=(BenchmarkResult("old", "old", True, 4.0, 100, 120, True, ""),),
    ).to_dict()
    (tmp_path / "2020-01-01.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: (_ok_response(_THREE_PARAGRAPHS), 1.0),
    )
    run = ModelBenchmarkService(result_dir=tmp_path).measure_or_reuse()
    assert run is not None
    assert run.measured_on != "2020-01-01"


def test_result_from_a_different_prompt_version_is_not_reused(tmp_path):
    payload = {
        "measured_on": "2999-01-01",
        "prompt_version": "v0-old",
        "results": [BenchmarkResult("old", "old", True, 4.0, 100, 120, True, "").to_dict()],
    }
    (tmp_path / "2999-01-01.json").write_text(json.dumps(payload), encoding="utf-8")

    assert ModelBenchmarkService(result_dir=tmp_path).latest_run() is None


def test_disabled_flag_skips_measurement(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_MODEL_BENCHMARK", "false")
    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: (_ok_response(_THREE_PARAGRAPHS), 1.0),
    )
    assert ModelBenchmarkService(result_dir=tmp_path).measure_or_reuse() is None


def test_no_targets_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ModelBenchmarkService.targets() == []


def test_format_check_rejects_headings_lists_and_wrong_paragraph_count():
    check = mbs._followed_three_paragraph_format
    assert check(_THREE_PARAGRAPHS) is True
    assert check("## Heading\n\na\n\nb") is False
    assert check("- one\n\n- two\n\n- three") is False
    assert check("**bold**\n\nb\n\nc") is False
    assert check("only one paragraph") is False


def test_rendered_table_states_measurement_conditions_and_keeps_failures():
    run = BenchmarkRun(
        measured_on="2026-08-26",
        prompt_version=BENCHMARK_PROMPT_VERSION,
        results=(
            BenchmarkResult("vendor/fast:free", "primary", True, 4.2, 210, 260, True, ""),
            BenchmarkResult("vendor/dead:free", "secondary", False, 0.0, 0, 0, False, "HTTP 404"),
        ),
    )
    html = render_benchmark_table_html(run)

    assert "<table" in html
    assert "vendor/fast:free" in html
    # 실패한 모델과 그 사유가 표에 남아야 한다.
    assert "vendor/dead:free" in html
    assert "HTTP 404" in html
    # 과장 금지: 1회 측정을 벤치마크라고 부르지 않는다.
    assert "2026-08-26" in html
    assert "One request is not a benchmark" in html


def test_empty_run_renders_nothing():
    run = BenchmarkRun(measured_on="2026-08-26", prompt_version=BENCHMARK_PROMPT_VERSION, results=())
    assert render_benchmark_table_html(run) == ""


def test_llm_provider_survives_explicit_null_content(monkeypatch):
    """2026-08-26 GHA 실측: content 키는 있는데 값이 null인 응답에 보정 호출이 죽었다.

    .get("content", "")의 기본값은 키가 없을 때만 쓰인다 — 명시적 null은 그대로 통과한다.
    """
    from blogspot_automation.services.llm_content_service import LlmContentService

    monkeypatch.setattr(
        "blogspot_automation.services.llm_content_service.post_chat_completion",
        lambda **kwargs: ({"choices": [{"message": {"content": None}}]}, 1.0),
    )
    service = LlmContentService()
    provider = {
        "name": "t", "provider_type": "openai_compatible", "base_url": None,
        "base_url_env": "OPENROUTER_BASE_URL",
        "default_base_url": "https://openrouter.ai/api/v1",
        "model": "vendor/m:free", "max_tokens": 100,
    }

    assert service._call_openai_compatible_provider(provider, "key", "prompt") == ""
