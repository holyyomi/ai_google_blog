from __future__ import annotations

import html
import logging
import os
import re
import threading
from typing import Any, Callable

from blogspot_automation.services import autocomplete_client

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; blogspot-automation/1.0)"
_FALSE_VALUES = {"0", "false", "no", "off"}
_FAILURE_THRESHOLD = 2

_QUESTION_PREFIXES = ("how ", "what ", "why ", "is ", "does ", "can ")
_QUESTION_TERMS = (
    "pricing",
    "cost",
    "free",
    "install",
    "setup",
    "vs",
    "settings",
    "risks",
)

_PRODUCT_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"\bclaude\s+code\b", re.IGNORECASE), lambda m: "claude code"),
    (re.compile(r"\bmicrosoft\s+copilot\b", re.IGNORECASE), lambda m: "microsoft copilot"),
    (re.compile(r"\bgithub\s+copilot\b", re.IGNORECASE), lambda m: "github copilot"),
    (re.compile(r"\bgemini\s+agent\s+mode\b", re.IGNORECASE), lambda m: "gemini agent mode"),
    (
        re.compile(r"\bgemini\s+robotics\s+\d+(?:\.\d+)?\b", re.IGNORECASE),
        lambda m: _clean_seed(m.group(0)).lower(),
    ),
    (
        re.compile(r"\bgpt[-\s]?\d+(?:\.\d+)?\b", re.IGNORECASE),
        lambda m: re.sub(r"\s+", "-", m.group(0).lower()),
    ),
    (re.compile(r"\bchatgpt\b", re.IGNORECASE), lambda m: "chatgpt"),
    (re.compile(r"\bopenai\b", re.IGNORECASE), lambda m: "openai"),
    (re.compile(r"\bclaude\b", re.IGNORECASE), lambda m: "claude"),
    (re.compile(r"\banthropic\b", re.IGNORECASE), lambda m: "anthropic"),
    (re.compile(r"\bgemini\b", re.IGNORECASE), lambda m: "gemini"),
    (re.compile(r"\bgrok\b", re.IGNORECASE), lambda m: "grok"),
    (re.compile(r"\bperplexity\b", re.IGNORECASE), lambda m: "perplexity"),
    (re.compile(r"\bcopilot\b", re.IGNORECASE), lambda m: "copilot"),
    (re.compile(r"\bcursor\b", re.IGNORECASE), lambda m: "cursor"),
    (re.compile(r"\bdeepseek\b", re.IGNORECASE), lambda m: "deepseek"),
    (re.compile(r"\bmidjourney\b", re.IGNORECASE), lambda m: "midjourney"),
    (re.compile(r"\brunway\b", re.IGNORECASE), lambda m: "runway"),
    (re.compile(r"\bsora\b", re.IGNORECASE), lambda m: "sora"),
    (re.compile(r"\bllama\b", re.IGNORECASE), lambda m: "llama"),
    (re.compile(r"\bmistral\b", re.IGNORECASE), lambda m: "mistral"),
    (re.compile(r"\bqwen\b", re.IGNORECASE), lambda m: "qwen"),
)

_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsystem\s+prompts?\s+leak(?:ed|s)?\b|\bleaked\s+system\s+prompts?\b", re.IGNORECASE), "system prompt leak"),
    # 2026-08-25 실측: "Claude System Prompts:"(복수)가 \bprompt\b에 안 걸려
    # 기본 의도(pricing)로 떨어졌다. 헤드라인은 복수형을 흔히 쓴다.
    (re.compile(r"\bsystem\s+prompts?\b", re.IGNORECASE), "system prompt"),
    # 사건형 어휘 → 사람들이 실제로 치는 의도어로 번역한다. 헤드라인은 "flaw",
    # "exfiltrate", "outage" 같은 기사 어휘를 쓰지만 검색창에는 "security", "down"을
    # 친다(2026-08-25 자동완성 실측).
    (re.compile(r"\bflaws?\b|\bvulnerabilit(?:y|ies)\b|\bexploits?\b|\bexfiltrat\w*\b|\bbreach\w*\b|\bhack\w*\b", re.IGNORECASE), "security"),
    (re.compile(r"\boutage\b|\bshut\s?down\b|\bshutting\s+down\b|\bdowntime\b", re.IGNORECASE), "down"),
    (re.compile(r"\brelease\s+date\b", re.IGNORECASE), "release date"),
    (re.compile(r"\bagent\s+mode\b", re.IGNORECASE), "agent mode"),
    (re.compile(r"\bsecurity\s+risks?\b|\brisks?\s+security\b", re.IGNORECASE), "security risks"),
    (re.compile(r"\bsecurity\b", re.IGNORECASE), "security"),
    (re.compile(r"\bpricing\b|\bprice\b|\bprices\b", re.IGNORECASE), "pricing"),
    (re.compile(r"\bcost\b|\bcosts\b", re.IGNORECASE), "cost"),
    (re.compile(r"\bapi\b", re.IGNORECASE), "api"),
    (re.compile(r"\binstall(?:ation)?\b", re.IGNORECASE), "install"),
    (re.compile(r"\bsetup\b|\bset\s+up\b", re.IGNORECASE), "setup"),
    (re.compile(r"\bsettings?\b", re.IGNORECASE), "settings"),
    (re.compile(r"\bskills?\b", re.IGNORECASE), "skills"),
    (re.compile(r"\bfree\b", re.IGNORECASE), "free"),
    (re.compile(r"\bvs\.?\b|\bversus\b", re.IGNORECASE), "vs"),
    (re.compile(r"\brisks?\b", re.IGNORECASE), "risks"),
)

_PER_SEED_LIMIT = 4

# 자동완성은 국가별 롱테일을 잔뜩 물고 온다("gemini pricing india"). 이 블로그는
# US-first 영어권 타깃이라 지역 한정 검색어는 제목·FAQ 재료로 쓸모가 없다.
_GEO_NOISE = re.compile(
    r"\b(india|korea|canada|australia|uk|usa|philippines|indonesia|malaysia|"
    r"singapore|nigeria|pakistan|brazil|mexico|japan|china|germany|france)\b",
    re.IGNORECASE,
)

_REALTIME_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bserver\s+status\b", re.IGNORECASE), "server status"),
    (re.compile(r"\bright\s+now\b", re.IGNORECASE), "right now"),
    (re.compile(r"\bis\s+[\w .+-]{1,60}\s+down\b", re.IGNORECASE), "is ... down"),
    (re.compile(r"\bstatus\b", re.IGNORECASE), "status"),
    (re.compile(r"\bdown\b", re.IGNORECASE), "down"),
    (re.compile(r"\boutage\b", re.IGNORECASE), "outage"),
    (re.compile(r"\bdowntime\b", re.IGNORECASE), "downtime"),
    (re.compile(r"\buptime\b", re.IGNORECASE), "uptime"),
    (re.compile(r"\bdetector\b", re.IGNORECASE), "detector"),
    (re.compile(r"\btracker\b", re.IGNORECASE), "tracker"),
    (re.compile(r"\bnow\b", re.IGNORECASE), "now"),
    (re.compile(r"\btoday\b", re.IGNORECASE), "today"),
)

_NAVIGATIONAL_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blog\s+in\b", re.IGNORECASE), "log in"),
    (re.compile(r"\bsign\s+in\b", re.IGNORECASE), "sign in"),
    (re.compile(r"\bsign\s+up\b", re.IGNORECASE), "sign up"),
    (re.compile(r"\bofficial\s+site\b", re.IGNORECASE), "official site"),
    (re.compile(r"\bhome\s+page\b", re.IGNORECASE), "home page"),
    (re.compile(r"\blogin\b", re.IGNORECASE), "login"),
    (re.compile(r"\bapp\b", re.IGNORECASE), "app"),
    (re.compile(r"\bdownload\b", re.IGNORECASE), "download"),
    (re.compile(r"\bdashboard\b", re.IGNORECASE), "dashboard"),
    (re.compile(r"\bconsole\b", re.IGNORECASE), "console"),
)

_INFORMATIONAL_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhow\s+to\b", re.IGNORECASE), "how to"),
    (re.compile(r"\bwhat\s+is\b", re.IGNORECASE), "what is"),
    (re.compile(r"\bnot\s+working\b", re.IGNORECASE), "not working"),
    (re.compile(r"\bversus\b", re.IGNORECASE), "versus"),
    (re.compile(r"\bwhy\b", re.IGNORECASE), "why"),
    (re.compile(r"\bguide\b", re.IGNORECASE), "guide"),
    (re.compile(r"\btutorial\b", re.IGNORECASE), "tutorial"),
    (re.compile(r"\bexamples?\b", re.IGNORECASE), "example"),
    (re.compile(r"\bvs\.?\b", re.IGNORECASE), "vs"),
    (re.compile(r"\bcompare\b|\bcomparison\b|\bcompared\b", re.IGNORECASE), "compare"),
    (re.compile(r"\bpricing\b", re.IGNORECASE), "pricing"),
    (re.compile(r"\bprices?\b", re.IGNORECASE), "price"),
    (re.compile(r"\bcosts?\b", re.IGNORECASE), "cost"),
    (re.compile(r"\bfree\b", re.IGNORECASE), "free"),
    (re.compile(r"\blimits?\b", re.IGNORECASE), "limits"),
    (re.compile(r"\balternatives?\b", re.IGNORECASE), "alternatives"),
    (re.compile(r"\bbest\b", re.IGNORECASE), "best"),
    (re.compile(r"\berrors?\b", re.IGNORECASE), "error"),
    (re.compile(r"\bfix(?:es)?\b", re.IGNORECASE), "fix"),
    (re.compile(r"\bsetup\b|\bset\s+up\b", re.IGNORECASE), "setup"),
    (re.compile(r"\binstall(?:ation)?\b", re.IGNORECASE), "install"),
    (re.compile(r"\breviews?\b", re.IGNORECASE), "review"),
    (re.compile(r"\bworth\s+it\b", re.IGNORECASE), "worth it"),
    (re.compile(r"\bskills?\b", re.IGNORECASE), "skills"),
)

_TRANSACTIONAL_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbuy\b|\bpurchase\b|\bsubscribe\b|\bupgrade\b", re.IGNORECASE), "buy"),
    (re.compile(r"\bcoupons?\b|\bpromo\s+codes?\b|\bdiscount\s+codes?\b", re.IGNORECASE), "coupon"),
)

_UNANSWERABLE_INTENTS = {"navigational", "realtime"}

_lock = threading.Lock()
_suggestion_cache: dict[tuple[str, str], tuple[bool, tuple[str, ...]]] = {}
_consecutive_failures = 0
_circuit_open = False


def classify_intent(phrase: str) -> str:
    """검색어가 블로그 글로 만족시킬 수 있는 의도인지 보수적으로 분류한다."""
    intent, _reason = _classify_intent_with_reason(phrase)
    return intent


def _classify_intent_with_reason(phrase: str) -> tuple[str, str]:
    text = _clean_phrase(phrase).casefold()
    if not text:
        return "unknown", "unknown:empty"

    realtime_signal = _first_intent_signal(text, _REALTIME_INTENT_PATTERNS)
    if realtime_signal:
        # status/down/now 계열은 독자가 실시간 페이지를 원하므로 정보성 단어가 섞여도 제외한다.
        return "realtime", f"realtime:{realtime_signal}"

    navigational_signal = _first_intent_signal(text, _NAVIGATIONAL_INTENT_PATTERNS)
    informational_signal = _first_intent_signal(text, _INFORMATIONAL_INTENT_PATTERNS)
    if navigational_signal and not informational_signal:
        return "navigational", f"navigational:{navigational_signal}"
    if navigational_signal and informational_signal:
        # 로그인/앱/콘솔에 해결형 단어가 섞이면 의도가 갈린다. 좋은 검색어로 오인하지 않게 중립 처리한다.
        return "unknown", f"unknown:mixed_navigational:{navigational_signal}+{informational_signal}"
    if informational_signal:
        return "informational", f"informational:{informational_signal}"

    transactional_signal = _first_intent_signal(text, _TRANSACTIONAL_INTENT_PATTERNS)
    if transactional_signal:
        return "transactional", f"transactional:{transactional_signal}"
    return "unknown", "unknown:no_signal"


def _first_intent_signal(
    text: str,
    patterns: tuple[tuple[re.Pattern[str], str], ...],
) -> str:
    for pattern, signal in patterns:
        if pattern.search(text):
            return signal
    return ""


def _classify_demand_phrases(phrases: list[str]) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]]]:
    answerable: list[str] = []
    excluded: list[dict[str, str]] = []
    classified: list[dict[str, str]] = []
    for phrase in phrases:
        intent, reason = _classify_intent_with_reason(phrase)
        row = {"phrase": phrase, "intent": intent, "reason": reason}
        classified.append(row)
        if intent == "informational":
            answerable.append(phrase)
        elif intent in _UNANSWERABLE_INTENTS:
            excluded.append(row)
    return answerable, excluded, classified


def extract_seeds(topic: str, raw: dict | None = None, *, limit: int = 3) -> list[str]:
    """기사형 헤드라인에서 autocomplete에 넣을 짧은 제품/의도 시드를 뽑는다."""
    max_items = max(0, int(limit or 0))
    if max_items <= 0:
        return []

    values = _candidate_text_values(topic, raw)
    seeds: list[str] = []
    seen: set[str] = set()

    def add_seed(value: str) -> None:
        seed = _clean_seed(value).lower()
        if not seed:
            return
        key = seed.casefold()
        if key in seen:
            return
        seen.add(key)
        seeds.append(seed)

    for text in values:
        products = _product_mentions(text)
        intents = _intent_mentions(text)
        for product in products:
            for intent in intents:
                add_seed(_join_product_intent(product, intent))
                if len(seeds) >= max_items:
                    return seeds[:max_items]
            add_seed(product)
            if len(seeds) >= max_items:
                return seeds[:max_items]

    if not seeds:
        fallback = _fallback_seed(topic)
        if fallback:
            add_seed(fallback)
    return seeds[:max_items]


def fetch_suggestions(seed: str, *, lang: str = "en", timeout: float = 6.0) -> list[str]:
    """Google suggestqueries 결과를 가져온다. 실패는 예외 대신 빈 리스트로 폴백한다."""
    suggestions, _measured = _fetch_suggestions_result(seed, lang=lang, timeout=timeout)
    return suggestions


def collect_demand_phrases(
    topic: str,
    *,
    raw: dict | None = None,
    lang: str | None = None,
    limit: int = 12,
) -> dict:
    try:
        return _collect_demand_phrases(topic, raw=raw, lang=lang, limit=limit)
    except Exception as exc:  # noqa: BLE001 - 이 기능 때문에 발행이 멈추면 안 된다.
        logger.warning("search_demand_service: collection failed (fallback): %s", exc)
        try:
            seeds = extract_seeds(topic, raw=raw)
        except Exception:  # noqa: BLE001
            seeds = []
        return {
            "measured": False,
            "seeds": seeds,
            "phrases": [],
            "questions": [],
            "failures": 1,
        }


def _collect_demand_phrases(
    topic: str,
    *,
    raw: dict | None = None,
    lang: str | None = None,
    limit: int = 12,
) -> dict:
    seeds = extract_seeds(topic, raw=raw)
    result = {
        "measured": False,
        "seeds": seeds,
        "phrases": [],
        "questions": [],
        "answerable": [],
        "excluded": [],
        "failures": 0,
    }
    if not _enabled():
        return result

    request_budget = _env_int("SEARCH_DEMAND_MAX_REQUESTS", 4)
    if request_budget <= 0 or not seeds:
        return result

    timeout = _env_float("SEARCH_DEMAND_TIMEOUT", 6.0)
    language = _clean_lang(lang or "en")
    phrases: list[str] = []
    questions: list[str] = []
    phrase_seen: set[str] = set()
    question_seen: set[str] = set()
    measured = False
    failures = 0
    seed_keys = {_clean_seed(seed).casefold() for seed in seeds}

    for seed in seeds[:request_budget]:
        if _is_circuit_open():
            break
        taken_from_seed = 0
        suggestions, ok = _fetch_suggestions_result(seed, lang=language, timeout=timeout)
        if ok:
            measured = True
        else:
            failures += 1
        for suggestion in suggestions:
            phrase = _clean_phrase(suggestion)
            if phrase.casefold() in seed_keys:
                continue
            if not _is_longtail(phrase, seed):
                continue
            if _GEO_NOISE.search(phrase):
                continue
            key = phrase.casefold()
            if key in phrase_seen:
                continue
            phrase_seen.add(key)
            phrases.append(phrase)
            taken_from_seed += 1
            if _looks_like_question_demand(phrase) and key not in question_seen:
                question_seen.add(key)
                questions.append(phrase)
            # 시드당 상한 — 없으면 첫 시드가 limit을 다 먹어 검색어가 한 축으로
            # 도배된다(2026-08-25 실측: 6개가 전부 "... pricing ..."이었다).
            if taken_from_seed >= _PER_SEED_LIMIT or len(phrases) >= max(0, limit):
                break
        if len(phrases) >= max(0, limit):
            break

    result["measured"] = measured
    result["phrases"] = phrases[: max(0, limit)]
    result["questions"] = questions[: max(0, limit)]
    result["failures"] = failures
    # 검색량이 있다고 다 쓸 수 있는 게 아니다. 2026-08-25 실측: "claude status"는
    # 자동완성에 잡히지만 그걸 치는 사람은 실시간 상태 페이지를 원한다 — 블로그 글로는
    # 구조적으로 만족시킬 수 없고, 실제로 그 제목으로 발행해 놓고 보니 답이 없었다.
    # 같은 목록에 "claude api costs"처럼 답할 수 있는 게 있었는데도 못 답하는 걸 골랐다.
    answerable, excluded, _classified = _classify_demand_phrases(result["phrases"])
    result["answerable"] = answerable
    result["excluded"] = excluded
    return result


def _fetch_suggestions_result(seed: str, *, lang: str, timeout: float) -> tuple[list[str], bool]:
    seed = _clean_seed(seed).lower()
    language = _clean_lang(lang)
    if not seed or not _enabled():
        return [], False

    cache_key = (language, seed.casefold())
    with _lock:
        cached = _suggestion_cache.get(cache_key)
        if cached is not None:
            return list(cached[1]), bool(cached[0])
        if _circuit_open:
            return [], False

    # 전송은 autocomplete_client 하나로 모았다(2026-08-25) — 캐시·회로차단기·
    # env 스위치 같은 이 모듈 고유의 정책만 여기 남는다.
    raw_items, ok = autocomplete_client.fetch_suggestions(
        seed, hl=language, timeout=timeout, user_agent=_USER_AGENT, limit=0
    )
    if not ok:
        _cache_fetch_result(cache_key, False, ())
        _note_failure(RuntimeError("autocomplete fetch failed"))
        return [], False
    suggestions = tuple(
        dict.fromkeys(_clean_phrase(str(item)) for item in raw_items if _clean_phrase(str(item)))
    )

    _cache_fetch_result(cache_key, True, suggestions)
    _note_success()
    return list(suggestions), True


def _cache_fetch_result(cache_key: tuple[str, str], ok: bool, suggestions: tuple[str, ...]) -> None:
    with _lock:
        _suggestion_cache[cache_key] = (ok, suggestions)


def _is_circuit_open() -> bool:
    with _lock:
        return _circuit_open


def _note_failure(exc: BaseException) -> None:
    global _circuit_open, _consecutive_failures
    with _lock:
        _consecutive_failures += 1
        if _consecutive_failures >= _FAILURE_THRESHOLD and not _circuit_open:
            _circuit_open = True
            logger.warning(
                "search_demand_service: autocomplete disabled for this run after %d consecutive failures (%s)",
                _consecutive_failures,
                exc,
            )


def _note_success() -> None:
    global _consecutive_failures
    with _lock:
        _consecutive_failures = 0


def _enabled() -> bool:
    return os.getenv("ENABLE_SEARCH_DEMAND", "true").strip().lower() not in _FALSE_VALUES


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _clean_lang(lang: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]", "", str(lang or "en")).strip()
    return value or "en"


def _candidate_text_values(topic: str, raw: dict | None) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for nested in value.values():
                add(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                add(nested)
            return
        text = _clean_seed(str(value))
        if text:
            values.append(text)

    raw = raw if isinstance(raw, dict) else {}
    for key in (
        "search_demand_topic",
        "safe_title_keyword",
        "cleaned_title",
        "original_title",
        "source_title",
        "title",
        "entities",
        "reader_search_questions",
        "search_angle",
        "hook_angle",
    ):
        add(raw.get(key))
    add(topic)
    return list(dict.fromkeys(values))


def _product_mentions(text: str) -> list[str]:
    hits: list[tuple[int, int, int, str]] = []
    for pattern, normalizer in _PRODUCT_PATTERNS:
        for match in pattern.finditer(text or ""):
            product = _clean_seed(normalizer(match)).lower()
            if product:
                hits.append((_product_priority(product), match.start(), -len(match.group(0)), product))
    products: list[str] = []
    seen: set[str] = set()
    for _priority, _start, _negative_len, product in sorted(hits):
        key = product.casefold()
        if key in seen:
            continue
        if any(key != existing and key in existing for existing in seen):
            continue
        seen.add(key)
        products.append(product)
    return products


def _product_priority(product: str) -> int:
    if re.search(r"\d", product) or " " in product:
        return 0
    if product in {"openai", "anthropic"}:
        return 2
    return 1


# 헤드라인에 의도 단어가 하나도 없을 때 붙이는 기본 의도.
# 2026-08-25 실측: 맨 제품명 시드("gemini")는 자동완성이 브랜드 일반어만 돌려줘
# 질문형 수확이 0개였다. 반면 "gemini agent"·"copilot security"처럼 의도를 붙이면
# 9개씩 나왔다. 뉴스 헤드라인은 사건만 서술하고 의도어가 없는 경우가 흔해서,
# 그때는 검색 수요가 가장 두꺼운 두 축(가격·사용법)을 기본값으로 쓴다.
_DEFAULT_INTENTS: tuple[str, ...] = ("pricing", "how to use")


def _intent_mentions(text: str) -> list[str]:
    intents: list[str] = []
    seen: set[str] = set()
    for pattern, intent in _INTENT_PATTERNS:
        if pattern.search(text or "") and intent not in seen:
            seen.add(intent)
            intents.append(intent)
    if not intents:
        intents.extend(_DEFAULT_INTENTS)
    return intents


def _join_product_intent(product: str, intent: str) -> str:
    product = _clean_seed(product).lower()
    intent = _clean_seed(intent).lower()
    if not product:
        return intent
    if not intent or intent in product:
        return product
    return f"{product} {intent}"


def _fallback_seed(topic: str) -> str:
    text = _clean_seed(topic).lower()
    text = re.sub(r"\b20\d{2}\b", " ", text)
    tokens = [token for token in re.findall(r"[a-z0-9][a-z0-9.+-]*", text) if token not in {"ai", "news"}]
    return " ".join(tokens[:4])


def _clean_seed(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\[\]{}()<>|_/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n\"'.,;:!?")


def _clean_phrase(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n\"'.,;:!?")


def _is_longtail(phrase: str, seed: str) -> bool:
    phrase_key = _clean_phrase(phrase).casefold()
    seed_key = _clean_seed(seed).casefold()
    if not (phrase_key and seed_key and phrase_key != seed_key and len(phrase_key) > len(seed_key)):
        return False
    return _shares_seed_head(phrase_key, seed_key)


def _shares_seed_head(phrase_key: str, seed_key: str) -> bool:
    """제안이 시드의 '머리 토큰'을 실제로 담고 있는지 — 동음이의 오염 차단.

    2026-08-25 실측: 시드 "spacexai"에 자동완성이 "spacex stock price"(전혀 다른
    회사의 주가)를 돌려줬다. 길이만 보는 필터는 이걸 통과시킨다. 자동완성은 철자가
    비슷한 다른 엔티티로 곧잘 새기 때문에, 머리 토큰이 없는 제안은 이 주제의 수요가
    아니라고 본다. 접두 일치(gpt-5 → gpt-5.6)는 인정한다 — 모델명이 버전으로
    갈라지는 경우까지 버리면 진짜 수요를 잃는다.
    """
    head = _alnum_only(seed_key.split(" ")[0])
    if not head:
        return False
    return head in _alnum_only(phrase_key)


def _alnum_only(value: str) -> str:
    """비교 전 표기 흔들림 제거: "gpt-5.6"/"gpt 5.6" → "gpt56".

    자동완성은 같은 모델명을 하이픈/공백/점을 섞어 돌려준다. 토큰 단위로 비교하면
    표기가 다르다는 이유로 진짜 수요를 버리게 되므로, 영숫자만 남겨 맞춘다.
    """
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _looks_like_question_demand(phrase: str) -> bool:
    lowered = f" {_clean_phrase(phrase).casefold()} "
    stripped = lowered.strip()
    if stripped.startswith(_QUESTION_PREFIXES):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _QUESTION_TERMS)


def _reset_for_tests() -> None:
    global _circuit_open, _consecutive_failures
    with _lock:
        _suggestion_cache.clear()
        _consecutive_failures = 0
        _circuit_open = False
