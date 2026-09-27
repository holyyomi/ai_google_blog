"""없는 명령어·출처에 없는 모델 버전 검사(2026-09-27) 회귀 방지.

기준 사례: 2026-09-26 라이브 글이 gemini-cli 공식 문서를 인용하면서
`gemini quota`·`gemini auth status`(문서에 없음, 실제는 /auth)와
"Gemini 1.5 Flash"를 현재 모델처럼 썼다.
"""
from blogspot_automation.services.source_grounding_service import audit_grounding

FACTS = (
    "Gemini CLI quota: 250 requests/day with an API key. Use /auth to switch sign-in. "
    "Run ollama show llama3 to see parameters. Claude Opus 5.5 (claude-opus-5-5) launched. "
    "Models: gemini-2.5-pro and Gemini 3 Pro."
)


def _audit(body: str):
    return audit_grounding(f"<article><p>{body}</p></article>", FACTS)


def test_invented_cli_subcommands_are_flagged():
    r = _audit("Run <code>gemini quota</code> or <code>gemini auth status</code>.")
    assert r.ungrounded_commands == ["gemini quota", "gemini auth status"]
    assert "command: gemini quota" in r.hard_violations


def test_documented_commands_pass():
    r = _audit("Type <code>/auth</code>, then <code>ollama show modelname</code>.")
    assert r.ungrounded_commands == []


def test_files_paths_and_generic_tools_are_not_commands():
    r = _audit("Edit <code>AGENTS.md</code> and <code>.claude/settings.json</code>, run <code>pnpm install</code>.")
    assert r.ungrounded_commands == []


def test_model_versions_must_be_in_facts():
    r = _audit("Works with Gemini 1.5 Flash, Gemini 2.5 Pro, Gemini 3 and Claude Opus 5.5.")
    assert r.ungrounded_models == ["Gemini 1.5"]
    assert "model: Gemini 1.5" in r.hard_violations


def test_version_prefix_is_not_a_match():
    # 팩트에 5.5 만 있을 때 "Claude Opus 5" 는 다른 모델이다.
    r = _audit("Claude Opus 5 is older.")
    assert r.ungrounded_models == ["Claude Opus 5"]


def test_basic_shell_utilities_are_not_flagged():
    r = _audit("Check write access: <code>touch test.tmp && rm test.tmp</code>.")
    assert r.ungrounded_commands == []
