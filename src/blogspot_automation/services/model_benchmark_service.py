"""무료 모델을 우리가 직접 재서 표로 만든다 — 남이 못 쓰는 1차 자료.

배경(2026-08-26): GSC 실측에서 색인 0/32였고, 남은 원인 중 하나가 "이길 수 없는
카테고리"였다. 오늘 나온 AI 뉴스 요약은 TechCrunch가 먼저 쓰고 권위도 높다.
그런데 이 블로그는 2026년 7월부터 **무료 LLM API만으로** 매일 자동 발행되고
있다 — 무료 티어를 매일 때리면서 나오는 응답 시간·실패·모델 증발은 벤더
문서에도 뉴스에도 없는 자료다. 그걸 측정해서 본문에 넣는다.

정직성 규칙(전역 원칙 3·5):
- 1회 측정을 "벤치마크"라고 부르지 않는다. 표에 측정 조건과 날짜를 같이 싣는다.
- 실패한 모델을 표에서 빼지 않는다. 실패도 측정 결과다.
- 측정이 안 되면 표를 만들지 않는다. 빈칸을 추정치로 채우지 않는다.

비용 규칙:
- 무료 모델만 대상이다(paid provider는 제외).
- 매 발행마다 다시 재지 않는다. MODEL_BENCHMARK_MAX_AGE_DAYS(기본 7일) 안의
  측정치가 있으면 그걸 재사용한다 — 실행 시간의 97%가 이미 LLM 호출이다.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RESULT_DIR = Path("data/benchmarks")
_DEFAULT_TIMEOUT = 60
_DEFAULT_MAX_TOKENS = 700
_DEFAULT_MAX_MODELS = 4
_DEFAULT_MAX_AGE_DAYS = 7

# 고정 프롬프트. 바꾸면 과거 측정치와 비교할 수 없게 되므로 버전을 함께 올린다.
BENCHMARK_PROMPT_VERSION = "v1"
BENCHMARK_PROMPT = (
    "Explain what an API rate limit is to someone who has never hit one. "
    "Use exactly three short paragraphs and no headings, no lists, no bold."
)
_BENCHMARK_SYSTEM_PROMPT = "You are a technical writer. Follow formatting instructions exactly."


# 이 프롬프트에 20단어 미만으로 답한 건 "빠르게 답했다"가 아니라 답을 못 한 것이다.
# 실측(2026-08-26): openrouter/free가 completion_tokens 377을 쓰고도 content는 3단어로
# 잘려 돌아온 적이 있다. 그대로 표에 실으면 "2.4초에 3단어"라는 거짓 인상을 준다.
_MIN_USABLE_WORDS = 20


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    model: str
    label: str
    ok: bool
    seconds: float
    words: int
    completion_tokens: int
    followed_format: bool
    error: str
    # openrouter/free 같은 라우터는 호출마다 실제 모델이 달라진다(실측: 같은
    # 엔드포인트가 minimax-m3로 라우팅됨). 무엇을 쟀는지 남기지 않으면 표가
    # 다음 주에 다른 모델 얘기를 하게 된다.
    routed_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def display_model(self) -> str:
        if self.routed_model and self.routed_model != self.model:
            return f"{self.model} (routed to {self.routed_model})"
        return self.model

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkResult":
        return cls(
            model=str(payload.get("model") or ""),
            label=str(payload.get("label") or ""),
            ok=bool(payload.get("ok")),
            seconds=float(payload.get("seconds") or 0.0),
            words=int(payload.get("words") or 0),
            completion_tokens=int(payload.get("completion_tokens") or 0),
            followed_format=bool(payload.get("followed_format")),
            error=str(payload.get("error") or ""),
            routed_model=str(payload.get("routed_model") or ""),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    measured_on: str
    prompt_version: str
    results: tuple[BenchmarkResult, ...]

    @property
    def has_any_success(self) -> bool:
        return any(result.ok for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured_on": self.measured_on,
            "prompt_version": self.prompt_version,
            "prompt": BENCHMARK_PROMPT,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkRun | None":
        if not isinstance(payload, dict):
            return None
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return None
        return cls(
            measured_on=str(payload.get("measured_on") or ""),
            prompt_version=str(payload.get("prompt_version") or ""),
            results=tuple(
                BenchmarkResult.from_dict(item) for item in results if isinstance(item, dict)
            ),
        )


class ModelBenchmarkService:
    def __init__(self, *, result_dir: str | Path | None = None) -> None:
        self.result_dir = Path(result_dir or _DEFAULT_RESULT_DIR)

    # ------------------------------------------------------------------ config

    @staticmethod
    def enabled() -> bool:
        return str(os.getenv("ENABLE_MODEL_BENCHMARK", "true")).strip().lower() in {
            "1", "true", "yes", "on",
        }

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = (os.getenv(name, "") or "").strip()
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    @staticmethod
    def targets() -> list[dict[str, Any]]:
        """측정 대상 = 우리가 실제로 본문 생성에 쓰는 무료 OpenAI 호환 provider.

        provider 목록을 여기서 따로 정의하지 않고 llm_content_service에서 가져온다
        — 두 곳에 적으면 모델을 바꿨을 때 표만 옛 모델을 가리키게 된다.
        """
        from blogspot_automation.services.llm_content_service import (
            free_openai_compatible_providers,
        )

        targets: list[dict[str, Any]] = []
        for provider in free_openai_compatible_providers():
            api_key = os.getenv(str(provider.get("api_key_env") or ""), "").strip()
            if not api_key:
                continue
            model = provider.get("model")
            model_env = str(provider.get("model_env") or "").strip()
            if model_env:
                model = os.getenv(model_env, "").strip() or model
            if not model:
                continue
            targets.append({**provider, "resolved_model": str(model), "resolved_api_key": api_key})
        return targets

    # --------------------------------------------------------------- measuring

    def latest_run(self, *, max_age_days: int | None = None) -> BenchmarkRun | None:
        """최근 측정치. 없거나 너무 오래됐으면 None."""
        if max_age_days is None:
            max_age_days = self._env_int("MODEL_BENCHMARK_MAX_AGE_DAYS", _DEFAULT_MAX_AGE_DAYS)
        if not self.result_dir.exists():
            return None
        cutoff = (date.today() - timedelta(days=max(0, max_age_days))).isoformat()
        for path in sorted(self.result_dir.glob("*.json"), reverse=True):
            if path.stem < cutoff:
                break
            try:
                run = BenchmarkRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                logger.warning("benchmark result load failed (%s): %s", path.name, exc)
                continue
            if run is not None and run.prompt_version == BENCHMARK_PROMPT_VERSION:
                return run
        return None

    def measure_or_reuse(self) -> BenchmarkRun | None:
        """오늘 쓸 측정치를 돌려준다. 최근 것이 있으면 재측정하지 않는다."""
        if not self.enabled():
            return None
        cached = self.latest_run()
        if cached is not None:
            logger.info("model_benchmark: %s 측정치 재사용", cached.measured_on)
            return cached
        run = self.measure()
        if run is None or not run.has_any_success:
            # 전멸한 측정은 저장하지 않는다 — 다음 실행에서 재시도하게 둔다.
            logger.warning("model_benchmark: 측정 성공 0건, 표를 만들지 않는다")
            return None
        self.save(run)
        return run

    def measure(self) -> BenchmarkRun | None:
        targets = self.targets()
        if not targets:
            logger.info("model_benchmark: 측정 대상 없음(무료 provider 키 미설정)")
            return None
        max_models = self._env_int("MODEL_BENCHMARK_MAX_MODELS", _DEFAULT_MAX_MODELS)
        if len(targets) > max_models:
            logger.info(
                "model_benchmark: 대상 %d개 중 상위 %d개만 측정(실행 시간 보호)",
                len(targets), max_models,
            )
            targets = targets[:max_models]
        results = [self._measure_one(target) for target in targets]
        return BenchmarkRun(
            measured_on=datetime.now(timezone.utc).date().isoformat(),
            prompt_version=BENCHMARK_PROMPT_VERSION,
            results=tuple(results),
        )

    def _measure_one(self, target: dict[str, Any]) -> BenchmarkResult:
        from blogspot_automation.services.llm_content_service import post_chat_completion

        model = str(target["resolved_model"])
        label = str(target.get("name") or model)
        endpoint = self._endpoint(target)
        timeout = self._env_int("MODEL_BENCHMARK_TIMEOUT", _DEFAULT_TIMEOUT)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _BENCHMARK_SYSTEM_PROMPT},
                {"role": "user", "content": BENCHMARK_PROMPT},
            ],
            "max_tokens": self._env_int("MODEL_BENCHMARK_MAX_TOKENS", _DEFAULT_MAX_TOKENS),
            "temperature": 0.7,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {target['resolved_api_key']}",
            **(target.get("extra_headers") or {}),
        }
        try:
            response, seconds = post_chat_completion(
                endpoint=endpoint, headers=headers, payload=payload, timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — 실패도 측정 결과다
            logger.info("model_benchmark: %s 실패 — %s", model, str(exc)[:120])
            return BenchmarkResult(
                model=model, label=label, ok=False, seconds=0.0, words=0,
                completion_tokens=0, followed_format=False, error=_short_error(exc),
            )

        choices = response.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "")
        usage = response.get("usage") or {}
        completion_tokens = int(usage.get("completion_tokens") or 0)
        routed_model = str(response.get("model") or "")
        words = len([token for token in re.split(r"\s+", content.strip()) if token])
        if words < _MIN_USABLE_WORDS:
            error = "empty response" if not content.strip() else f"cut off at {words} words"
            logger.info("model_benchmark: %s 답변 불충분 — %s", model, error)
            return BenchmarkResult(
                model=model, label=label, ok=False, seconds=round(seconds, 1), words=words,
                completion_tokens=completion_tokens, followed_format=False,
                error=error, routed_model=routed_model,
            )
        logger.info("model_benchmark: %s %.1fs %d words", model, seconds, words)
        return BenchmarkResult(
            model=model,
            label=label,
            ok=True,
            seconds=round(seconds, 1),
            words=words,
            completion_tokens=completion_tokens,
            followed_format=_followed_three_paragraph_format(content),
            error="",
            routed_model=routed_model,
        )

    @staticmethod
    def _endpoint(target: dict[str, Any]) -> str:
        base_url_env = str(target.get("base_url_env") or "OPENAI_BASE_URL").strip()
        default_base_url = str(target.get("default_base_url") or "https://api.openai.com/v1").strip()
        url = (os.getenv(base_url_env, "") or default_base_url).strip().rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return url + "/chat/completions"

    # ---------------------------------------------------------------- persist

    def save(self, run: BenchmarkRun) -> bool:
        try:
            self.result_dir.mkdir(parents=True, exist_ok=True)
            path = self.result_dir / f"{run.measured_on}.json"
            path.write_text(
                json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("benchmark result save failed: %s", exc)
            return False


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    status = getattr(exc, "code", None)
    if status:
        return f"HTTP {status}"
    return text[:60]


def _followed_three_paragraph_format(content: str) -> bool:
    """'짧은 문단 3개, 제목·목록·굵게 없이'를 실제로 지켰는지."""
    text = content.strip()
    if "#" in text or "**" in text:
        return False
    if re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", text):
        return False
    paragraphs = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    return len(paragraphs) == 3


def render_benchmark_table_html(run: BenchmarkRun) -> str:
    """측정 결과를 본문에 넣을 HTML 표로. 측정 조건을 표와 함께 싣는다."""
    if not run.results:
        return ""
    rows = []
    for result in run.results:
        if result.ok:
            answer = "yes" if result.followed_format else "yes, wrong format"
            seconds = f"{result.seconds:.1f}s"
            words = str(result.words)
        else:
            answer = f"no ({result.error})" if result.error else "no"
            seconds = "&mdash;"
            words = "&mdash;"
        rows.append(
            "<tr>"
            f"<td>{_escape(result.display_model)}</td>"
            f"<td>{answer}</td>"
            f"<td>{seconds}</td>"
            f"<td>{words}</td>"
            "</tr>"
        )
    return (
        '<div class="measured-table">'
        "<h2>What these free models did when we asked them the same thing</h2>"
        "<table><thead><tr>"
        "<th>Model</th><th>Answered</th><th>Time</th><th>Words</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "<p><em>How this was measured: one request per model on "
        f"{_escape(run.measured_on)}, from a single machine on the free tier, "
        "same prompt for every model ("
        f"&ldquo;{_escape(BENCHMARK_PROMPT)}&rdquo;). One request is not a benchmark &mdash; "
        "free-tier response times swing with load, and a model that failed here may "
        "answer fine an hour later. This is what one small daily job actually saw."
        "</em></p></div>"
    )


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
