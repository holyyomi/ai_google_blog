"""수집한 팩트에 없는 주장을 잡아내는 검사 (2026-09-02 도입, **관찰 모드**).

왜 만들었나 — 2026-09-01 사고의 진짜 원인이 여기 있었다. 그날 글은 OpenAI의
Free Tier FAQ를 근거로 걸어놓고 그 문서와 **정반대**를 썼다. 문서는 "Free users
have unlimited everyday text chats"라고 말하는데, 글은 "daily limits that are not
disclosed"라고 단정했다. 아무도 그 숫자를 준 적이 없으니 모델이 "그럼 비공개인
모양"이라고 추론해 채운 것이다.

기존 게이트 24종은 전부 **글 안에서만** 판정한다 — 헤지가 몇 개인지, 표에 빈
칸이 있는지, 제목과 본문이 맞는지. 그래서 "출처와 반대로 쓴 글"은 하나도 못
잡는다. 자기 자신과는 완벽하게 일관되기 때문이다. 이 검사만이 유일하게
**본문과 수집 팩트를 대조**한다.

검사는 두 가지다:

1. **근거 없는 부재 주장** (사고를 직접 재현하는 검사). 글이 "공개하지 않는다",
   "명시된 바 없다" 같은 단정을 하는데, 수집한 팩트에는 그렇게 볼 근거가 되는
   표현이 하나도 없는 경우. 벤더가 무엇을 공개하지 **않는지**는 출처 없이는 알 수
   없는 사실이라, 근거가 없으면 그건 관찰이 아니라 추론이다.

2. **근거 없는 숫자**. 가격·한도·용량 숫자가 팩트 어디에도 없는 경우. 연도,
   버전, 목록 세기용 한 자리 숫자는 오탐이 많아 제외한다.

**2026-09-27 차단으로 승격(grounding_gate_mode). 아래는 도입 당시 기록.** 당시엔 경고만 냈다. 검증 안 된 차단 게이트가 발행을 멈추는 위험이 이 검사가
막으려는 문제보다 크다는 걸 answer-block 게이트에서 이미 한 번 배웠다
(2026-09-01, CLAUDE.md 참고). 실제 발행 몇 회에서 오탐률을 재고 나서
`SOURCE_GROUNDING_GATE=block`으로 승격한다.
"""

from __future__ import annotations

import logging
import os
import re
from html import unescape

logger = logging.getLogger(__name__)

__all__ = ["GroundingReport", "audit_grounding", "grounding_gate_mode"]


def grounding_gate_mode() -> str:
    """SOURCE_GROUNDING_GATE: observe | block (기본 block, 2026-09-27 승격).

    block 은 "바로 버린다"가 아니다. 걸리면 먼저 LLM 이 해당 문장만 고쳐 쓰고
    (llm_content_service), 그 뒤에도 하드 위반이 남을 때만 차단한다. 관찰 12일
    실측에서 초안 37개 중 27개가 경고를 받았다 — 재작성 없이 막으면 발행이 멈춘다.
    """
    mode = (os.getenv("SOURCE_GROUNDING_GATE", "block") or "").strip().lower()
    return mode if mode in {"observe", "block"} else "block"


# ── 1) 부재 주장 ──────────────────────────────────────────────────────────────
# 글이 "출처가 이렇게 말한다"가 아니라 "출처에 없다"를 단정하는 표현.
_ABSENCE_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:are|is|was|were)\s+not\s+(?:publicly\s+)?disclosed\b", re.I),
    re.compile(r"\bundisclosed\b", re.I),
    re.compile(r"\bnot\s+publicly\s+(?:available|documented|stated|published)\b", re.I),
    re.compile(r"\bdoes\s+not\s+(?:publish|disclose|specify|state|document)\b", re.I),
    re.compile(r"\bdo(?:es)?n[’']?t\s+(?:publish|disclose|specify|state|document)\b", re.I),
    re.compile(
        r"\bno\s+(?:official|published|public|documented)\s+"
        r"(?:daily\s+)?(?:limit|quota|cap|number|figure|rate|price)s?\b",
        re.I,
    ),
    re.compile(r"\bnot\s+(?:specified|documented|stated)\s+(?:anywhere|publicly|officially)\b", re.I),
)
_NO_FIXED_CLAIM_RE = re.compile(
    r"\bno\s+fixed\s+(?:daily\s+)?(?:limit|quota|cap|number|figure|rate|price)s?\b", re.I
)
_ABSENCE_CLAIM_PATTERNS = _ABSENCE_CLAIM_PATTERNS + (_NO_FIXED_CLAIM_RE,)

# 팩트 쪽에 이런 표현이 하나라도 있으면, 위 부재 주장은 출처에서 온 것으로 본다.
_ABSENCE_SUPPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bundisclosed\b", re.I),
    re.compile(r"\bnot\s+(?:publicly\s+)?(?:disclosed|specified|documented|published|stated)\b", re.I),
    re.compile(r"\bdoes\s+not\s+(?:publish|disclose|specify|state|document)\b", re.I),
    re.compile(r"\bno\s+(?:official|published|public)\b", re.I),
    re.compile(r"\bunspecified\b", re.I),
    re.compile(r"\bhas\s+not\s+(?:said|announced|confirmed|published)\b", re.I),
    re.compile(r"\bdeclined\s+to\s+(?:say|comment|disclose)\b", re.I),
    re.compile(r"\bwe\s+do\s+not\s+share\b", re.I),
)

# ── 2) 숫자 ───────────────────────────────────────────────────────────────────
# 숫자를 통째로 대조하면 오탐이 쏟아진다. 근거가 있어야 마땅한 종류만 본다:
# 돈, 저장/전송 용량, 토큰·요청·메시지 한도, 백분율.
_NUMERIC_CLAIM_RE = re.compile(
    r"(?:"
    r"\$\s?\d[\d,]*(?:\.\d+)?"                                   # $20, $1,500.50
    r"|\d[\d,]*(?:\.\d+)?\s?(?:%|percent)"                       # 40%, 40 percent
    r"|\d[\d,]*(?:\.\d+)?\s?(?:GB|MB|TB|KB)\b"                   # 500 MB
    r"|\d[\d,]*(?:\.\d+)?\s?(?:k|K|M|B)?\s?"
    r"(?:tokens?|requests?|messages?|queries|calls?|credits?)\b"  # 1M tokens
    r")",
    re.I,
)

# 글의 구조상 항상 등장하는 숫자 — 출처에 없어도 거짓이 아니다.
_NUMERIC_SAFE_RE = re.compile(r"^(?:19|20)\d{2}$")


def _visible_text(html: str) -> str:
    """본문에서 사람이 읽는 텍스트만 남긴다.

    JSON-LD(<script>)와 스타일은 통째로 버린다 — 구조화 데이터는 본문 문장을
    복사한 것이라 같은 주장을 두 번 세게 된다.
    """
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_number(token: str) -> str:
    """'$1,500.00' → '1500', '500 MB' → '500mb' 형태로 비교 가능하게 만든다."""
    token = token.strip().lower().replace("$", "").replace(",", "").replace(" ", "")
    token = re.sub(r"\.0+$", "", token)
    return token


def _facts_number_pool(facts: str) -> set[str]:
    """팩트에 등장하는 모든 숫자를 정규화해 모아둔다.

    단위까지 붙여 대조하면 팩트가 '500MB', 글이 '500 MB'처럼 표기만 달라도
    오탐이 난다. 그래서 단위 붙은 형태와 맨 숫자 양쪽을 모두 넣는다.
    """
    pool: set[str] = set()
    for match in re.finditer(r"\d[\d,]*(?:\.\d+)?\s?[a-zA-Z%]*", facts or ""):
        raw = _normalize_number(match.group(0))
        if not raw:
            continue
        pool.add(raw)
        bare = re.match(r"^\d+(?:\.\d+)?", raw)
        if bare:
            pool.add(bare.group(0))
    return pool


def _quote_around(text: str, start: int, end: int, *, window: int = 60) -> str:
    """지적한 표현을 앞뒤 문맥과 함께 돌려준다 — 로그만 보고 판정할 수 있게."""
    left = max(0, start - window)
    right = min(len(text), end + window)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right].strip()}{suffix}"


class GroundingReport:
    """검사 결과. 차단 여부는 호출부(llm_content_service)가 재작성 후 판정한다."""

    def __init__(
        self,
        *,
        checked: bool,
        ungrounded_absence: list[str],
        ungrounded_numbers: list[str],
        facts_chars: int,
        ungrounded_commands: list[str] | None = None,
        ungrounded_models: list[str] | None = None,
    ) -> None:
        self.checked = checked
        self.ungrounded_absence = ungrounded_absence
        self.ungrounded_numbers = ungrounded_numbers
        self.ungrounded_commands = list(ungrounded_commands or [])
        self.ungrounded_models = list(ungrounded_models or [])
        self.facts_chars = facts_chars

    @property
    def clean(self) -> bool:
        return not (
            self.ungrounded_absence
            or self.ungrounded_numbers
            or self.ungrounded_commands
            or self.ungrounded_models
        )

    @property
    def hard_violations(self) -> list[str]:
        """차단 대상: 부재 단정 전부 + 출처에 없는 달러 금액.

        퍼센트·요청 수·용량은 "한 세션에 30 requests라고 치면" 같은 가정 예시가
        섞여 있어(관찰 12일 실측) 재작성만 시키고 차단 사유로 쓰지 않는다.
        가격은 독자가 돈을 결정하는 숫자라 출처 없이 나가면 안 된다.
        """
        # 2026-09-27 추가: 없는 명령어·출처에 없는 모델 버전도 차단 대상이다.
        # 독자가 그대로 쳐 보고 실패하거나, 옛 모델을 현재 것으로 믿게 된다.
        dollars = [n for n in self.ungrounded_numbers if n.lstrip().startswith("$")]
        return (
            list(self.ungrounded_absence)
            + dollars
            + [f"command: {c}" for c in self.ungrounded_commands]
            + [f"model: {m}" for m in self.ungrounded_models]
        )

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "facts_chars": self.facts_chars,
            "ungrounded_absence_claims": self.ungrounded_absence,
            "ungrounded_numbers": self.ungrounded_numbers,
            "ungrounded_commands": self.ungrounded_commands,
            "ungrounded_models": self.ungrounded_models,
            "clean": self.clean,
            "hard_violations": self.hard_violations,
        }


def audit_grounding(content_html: str, facts: str, *, max_items: int = 8) -> GroundingReport:
    """본문의 주장을 수집 팩트와 대조한다.

    팩트가 비었으면 검사하지 않는다(`checked=False`) — 대조할 기준이 없는데
    전부 '근거 없음'으로 찍으면 신호가 아니라 잡음이다. 그 경우는 이미 다른
    게이트(facts_headline_only_no_source_body)가 담당한다.
    """
    facts = (facts or "").strip()
    if not facts:
        return GroundingReport(
            checked=False, ungrounded_absence=[], ungrounded_numbers=[], facts_chars=0
        )

    text = _visible_text(content_html)

    absence_supported = any(p.search(facts) for p in _ABSENCE_SUPPORT_PATTERNS)
    ungrounded_absence: list[str] = []
    if not absence_supported:
        seen: set[str] = set()
        # 2026-09-27 리허설 오탐: 공식 쿼터 표가 "Varies"라고 적은 것을 본문이
        # "no fixed number"로 옮겼다 — 출처 그대로다. "no fixed …" 단정만 "varies"를
        # 근거로 인정한다(전역 support 로 넣으면 "pricing varies by region" 하나로
        # 부재 검사 전체가 꺼진다).
        facts_say_varies = bool(re.search(r"\bvar(?:y|ies)\b", facts, flags=re.I))
        for pattern in _ABSENCE_CLAIM_PATTERNS:
            if facts_say_varies and pattern is _NO_FIXED_CLAIM_RE:
                continue
            for match in pattern.finditer(text):
                phrase = match.group(0).strip().lower()
                if phrase in seen:
                    continue
                seen.add(phrase)
                ungrounded_absence.append(_quote_around(text, match.start(), match.end()))
                if len(ungrounded_absence) >= max_items:
                    break
            if len(ungrounded_absence) >= max_items:
                break

    pool = _facts_number_pool(facts)
    ungrounded_numbers: list[str] = []
    seen_numbers: set[str] = set()
    for match in _NUMERIC_CLAIM_RE.finditer(text):
        token = match.group(0).strip()
        norm = _normalize_number(token)
        bare = re.match(r"^\d+(?:\.\d+)?", norm)
        bare_value = bare.group(0) if bare else ""
        if not bare_value or _NUMERIC_SAFE_RE.match(bare_value):
            continue
        if norm in pool or bare_value in pool:
            continue
        if norm in seen_numbers:
            continue
        seen_numbers.add(norm)
        ungrounded_numbers.append(token)
        if len(ungrounded_numbers) >= max_items:
            break

    ungrounded_commands = _ungrounded_commands(content_html, facts)[:max_items]
    ungrounded_models = _ungrounded_models(text, facts)[:max_items]

    report = GroundingReport(
        checked=True,
        ungrounded_absence=ungrounded_absence,
        ungrounded_numbers=ungrounded_numbers,
        facts_chars=len(facts),
        ungrounded_commands=ungrounded_commands,
        ungrounded_models=ungrounded_models,
    )
    if not report.clean:
        logger.warning(
            "SourceGrounding(관찰): 팩트에 근거 없는 주장 — 부재주장 %d건 %s / 숫자 %d건 %s"
            " / 명령어 %d건 %s / 모델 %d건 %s",
            len(ungrounded_absence), ungrounded_absence[:3],
            len(ungrounded_numbers), ungrounded_numbers[:5],
            len(ungrounded_commands), ungrounded_commands[:5],
            len(ungrounded_models), ungrounded_models[:5],
        )
    return report


# ── 3) 명령어 (2026-09-27) ────────────────────────────────────────────────────
# 2026-09-26 라이브 글에 `gemini quota`, `gemini auth status` 가 나갔다. 초안 41개
# 실측에서 <code> 가 있는 글은 13개였고, `claude init`·`claude log --level debug`
# 처럼 출처 없이 지어낸 것으로 보이는 명령과 `ollama show` 같은 실제 명령이 섞여
# 있었다. 명령은 전부 <code> 안에 있었으므로 <code> 만 본다.
#
# 판정 단위는 "도구 + 첫 하위명령"(gemini quota, claude log). 플래그 값까지 요구하면
# 출처가 같은 명령을 다른 플래그로 보여줄 때 오탐이 난다. 하위명령 없이 플래그만
# 있으면(claude --version) 도구 이름만 확인한다.
_GENERIC_CLI_TOOLS: frozenset[str] = frozenset(
    {
        "pip", "pip3", "npm", "pnpm", "yarn", "npx", "git", "cd", "ls", "curl",
        "wget", "python", "python3", "node", "brew", "docker", "export", "echo",
        "cat", "mkdir", "uv", "uvx", "conda", "sudo", "apt", "apt-get", "set",
        # 2026-09-27 리허설 오탐: `touch test.tmp && rm test.tmp` 가 걸렸다.
        # 기본 유닉스 명령은 출처에 적혀 있을 이유가 없다.
        "touch", "rm", "cp", "mv", "chmod", "chown", "grep", "find", "head", "tail",
        "less", "ln", "pwd", "which", "whoami", "env", "tar", "unzip", "ssh", "scp",
        "code", "open", "start", "powershell", "bash", "sh", "zsh", "source",
    }
)
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\s+\S+)+$")
_SLASH_COMMAND_RE = re.compile(r"^/[a-z][a-z0-9-]*$")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _ungrounded_commands(content_html: str, facts: str) -> list[str]:
    facts_flat = _flat(facts)
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"<code\b[^>]*>(.*?)</code>", content_html or "", flags=re.S | re.I):
        code = _flat(unescape(re.sub(r"<[^>]+>", "", raw))).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        if _SLASH_COMMAND_RE.match(code):
            key = code
        elif _COMMAND_RE.match(code):
            tokens = code.split()
            if tokens[0] in _GENERIC_CLI_TOOLS:
                continue
            sub = next((t for t in tokens[1:] if not t.startswith("-")), "")
            # 하위명령 자리가 파일·경로·값이면(modelname, ./x) 도구 이름만 본다.
            if sub and re.fullmatch(r"[a-z][a-z0-9-]*", sub) and sub != "modelname":
                key = f"{tokens[0]} {sub}"
            else:
                key = tokens[0]
        else:
            continue  # 파일명·경로·설정 키는 명령이 아니다
        if not re.search(rf"(?<![a-z0-9/-]){re.escape(key)}(?![a-z0-9-])", facts_flat):
            out.append(code)
    return out


# ── 4) 모델 버전 (2026-09-27) ─────────────────────────────────────────────────
# 2026-09 글에 "Gemini 1.5 Flash, 1.5 Pro, or 2.0" 이 현재 모델처럼 나갔다. 모델
# 목록을 코드에 적어 두면 다음 달에 낡는다. 대신 "회사명+버전"이 팩트에 있는지만
# 본다 — 팩트는 그날 수집한 것이라 항상 현재 기준이다.
_MODEL_RE = re.compile(
    r"\b(gpt|gemini|claude|llama|grok|deepseek|mistral|qwen)"
    r"[- ]?(?:(?:opus|sonnet|haiku|pro|flash|ultra|nano|mini|v)[- ]?)?"
    r"(\d+(?:\.\d+)?)\b",
    re.I,
)


def _ungrounded_models(text: str, facts: str) -> list[str]:
    facts_flat = _flat(facts).replace("-", " ")
    out: list[str] = []
    seen: set[str] = set()
    for match in _MODEL_RE.finditer(text or ""):
        family, version = match.group(1).lower(), match.group(2)
        key = f"{family} {version}"
        if key in seen:
            continue
        seen.add(key)
        # "Claude Opus 5.5" 는 팩트에 "Claude Opus 5.5" 든 "claude-opus-5-5" 든
        # 회사명 뒤 두 단어 안에 같은 버전이 있으면 근거로 본다.
        version_re = re.escape(version).replace(r"\.", r"[. ]")
        # (?!\s\d): 모델 ID "claude-opus-5-5" 를 펼친 "claude opus 5 5" 가
        # "Claude Opus 5" 의 근거로 잡히지 않게 한다.
        pattern = rf"\b{family}\s?(?:[a-z]+\s){{0,2}}{version_re}(?![\d.]|\s\d)"
        if not re.search(pattern, facts_flat):
            out.append(match.group(0))
    return out
