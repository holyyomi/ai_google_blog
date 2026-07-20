from __future__ import annotations

import json
import time
from urllib import error

import pytest

from blogspot_automation.services import community_topic_service as cts
from blogspot_automation.services.community_topic_service import (
    CommunityTopic,
    CommunityTopicSignal,
    collect_community_topics,
    score_topic_boost,
)


NOW = time.time()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CommunityTopicSignal.reset_cache()
    monkeypatch.delenv("ENABLE_COMMUNITY_TOPIC_SIGNAL", raising=False)
    monkeypatch.delenv("COMMUNITY_REDDIT_SUBS", raising=False)
    yield
    CommunityTopicSignal.reset_cache()


# ---------------------------------------------------------------------------
# 테스트용 payload 헬퍼
# ---------------------------------------------------------------------------


def _reddit_post(
    title: str,
    *,
    score: int = 100,
    comments: int = 10,
    age_hours: float = 1.0,
    stickied: bool = False,
    permalink: str = "/r/ChatGPT/comments/abc123/some_post/",
) -> dict:
    return {
        "title": title,
        "permalink": permalink,
        "score": score,
        "num_comments": comments,
        "created_utc": NOW - age_hours * 3600,
        "stickied": stickied,
    }


def _reddit_payload(posts: list[dict]) -> dict:
    return {"data": {"children": [{"kind": "t3", "data": p} for p in posts]}}


def _hn_hit(
    title: str,
    *,
    object_id: str = "1001",
    points: int = 120,
    comments: int = 30,
    age_hours: float = 2.0,
    url: str | None = "https://example.com/story",
) -> dict:
    return {
        "objectID": object_id,
        "title": title,
        "url": url,
        "points": points,
        "num_comments": comments,
        "created_at_i": int(NOW - age_hours * 3600),
    }


def _patch_http(monkeypatch, *, reddit: dict[str, dict] | None = None, hn: dict | None = None):
    """_http_get_json을 URL 기반 가짜 응답으로 치환한다 (실제 네트워크 없음)."""

    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        if "reddit.com" in url:
            for sub, payload in (reddit or {}).items():
                if f"/r/{sub}/" in url:
                    return payload
            return _reddit_payload([])
        if "hn.algolia.com" in url:
            return hn if hn is not None else {"hits": []}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(cts, "_http_get_json", fake_get)
    return calls


# ---------------------------------------------------------------------------
# Reddit 파싱
# ---------------------------------------------------------------------------


def test_parses_reddit_json_fields(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    post = _reddit_post("ChatGPT just solved my week-long debugging problem", score=300, comments=50)
    _patch_http(monkeypatch, reddit={"ChatGPT": _reddit_payload([post])})

    topics = collect_community_topics()

    assert len(topics) == 1
    topic = topics[0]
    assert topic.title == "ChatGPT just solved my week-long debugging problem"
    assert topic.url == "https://www.reddit.com/r/ChatGPT/comments/abc123/some_post/"
    assert topic.source == "reddit:ChatGPT"
    assert topic.mention_score == 300 + 2 * 50
    assert topic.comments == 50
    assert topic.created_utc == pytest.approx(post["created_utc"])


def test_parses_reddit_via_urlopen(monkeypatch):
    """모듈의 실제 fetch 경로(_http_get_json)까지 urlopen mock으로 검증."""
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "OpenAI")
    payload = _reddit_payload(
        [_reddit_post("OpenAI announces new reasoning model for developers", permalink="/r/OpenAI/comments/xyz/post/")]
    )

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        assert timeout == 10
        assert req.get_header("User-agent", "").startswith("blogspot-automation/1.0")
        if "reddit.com" in req.full_url:
            return _FakeResponse(json.dumps(payload).encode("utf-8"))
        return _FakeResponse(json.dumps({"hits": []}).encode("utf-8"))

    monkeypatch.setattr(cts.request, "urlopen", fake_urlopen)

    topics = collect_community_topics()
    assert len(topics) == 1
    assert topics[0].source == "reddit:OpenAI"
    assert topics[0].url == "https://www.reddit.com/r/OpenAI/comments/xyz/post/"


def test_skips_stickied_and_short_titles(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    posts = [
        _reddit_post("ChatGPT weekly megathread pinned announcement", stickied=True),
        _reddit_post("GPT meme lol"),  # 20자 미만
        _reddit_post("ChatGPT memory feature quietly rolled out to free tier"),
    ]
    _patch_http(monkeypatch, reddit={"ChatGPT": _reddit_payload(posts)})

    topics = collect_community_topics()
    titles = [t.title for t in topics]
    assert titles == ["ChatGPT memory feature quietly rolled out to free tier"]


def test_filters_posts_older_than_48h(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    posts = [
        _reddit_post("ChatGPT price change discussion from last week", age_hours=72),
        _reddit_post("ChatGPT price change discussion happening right now", age_hours=3),
    ]
    _patch_http(monkeypatch, reddit={"ChatGPT": _reddit_payload(posts)})

    topics = collect_community_topics()
    assert len(topics) == 1
    assert "right now" in topics[0].title


# ---------------------------------------------------------------------------
# Hacker News 파싱
# ---------------------------------------------------------------------------


def test_parses_hn_json_and_dedupes_object_ids(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    # 6개 쿼리 모두 같은 payload를 돌려받아도 objectID로 1회만 수집돼야 한다.
    hn_payload = {
        "hits": [
            _hn_hit("Claude quietly became the best coding LLM", object_id="42", points=250, comments=80),
            _hn_hit("Gemini 3 API pricing analysis for startups", object_id="43", points=90, comments=15, url=None),
        ]
    }
    _patch_http(monkeypatch, reddit={}, hn=hn_payload)

    topics = collect_community_topics()

    assert len(topics) == 2
    by_id = {t.title: t for t in topics}
    claude = by_id["Claude quietly became the best coding LLM"]
    assert claude.source == "hackernews"
    assert claude.mention_score == 250 + 2 * 80
    assert claude.comments == 80
    gemini = by_id["Gemini 3 API pricing analysis for startups"]
    # url 없는 스토리는 HN 아이템 링크로 폴백.
    assert gemini.url == "https://news.ycombinator.com/item?id=43"


def test_hn_request_uses_48h_and_points_filters(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    calls = _patch_http(monkeypatch, reddit={}, hn={"hits": []})

    collect_community_topics()

    hn_calls = [c for c in calls if "hn.algolia.com" in c]
    assert len(hn_calls) == 6  # 쿼리 6종
    for call in hn_calls:
        assert "tags=story" in call
        assert "points%3E40" in call
        assert "created_at_i%3E" in call


# ---------------------------------------------------------------------------
# 병합/중복/관련성
# ---------------------------------------------------------------------------


def test_dedupes_similar_titles_keeping_higher_score(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    posts = [
        _reddit_post("OpenAI launches GPT-6 model with agents", score=100, comments=10),
    ]
    hn_payload = {
        "hits": [
            _hn_hit("OpenAI Launches GPT-6 Model with Agents!", object_id="77", points=400, comments=100),
            _hn_hit("Mistral releases open weights for new small LLM", object_id="78", points=50, comments=5),
        ]
    }
    _patch_http(monkeypatch, reddit={"ChatGPT": _reddit_payload(posts)}, hn=hn_payload)

    topics = collect_community_topics()
    titles = [t.title for t in topics]
    assert "OpenAI Launches GPT-6 Model with Agents!" in titles  # 높은 점수(600) 유지
    assert "OpenAI launches GPT-6 model with agents" not in titles  # 낮은 점수(120) 제거
    assert "Mistral releases open weights for new small LLM" in titles
    # mention_score 내림차순 정렬 확인
    scores = [t.mention_score for t in topics]
    assert scores == sorted(scores, reverse=True)


def test_ai_relevance_filter_drops_offtopic(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "artificial")
    posts = [
        _reddit_post("My sourdough bread recipe finally worked this weekend"),
        _reddit_post("Anthropic ships Claude agent mode for spreadsheets"),
    ]
    _patch_http(monkeypatch, reddit={"artificial": _reddit_payload(posts)})

    topics = collect_community_topics()
    titles = [t.title for t in topics]
    assert titles == ["Anthropic ships Claude agent mode for spreadsheets"]


def test_max_items_cap(monkeypatch):
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "ChatGPT")
    # dedup에 걸리지 않도록 서로 다른 제목 5개 (모두 20자 이상, AI 관련).
    posts = [
        _reddit_post("ChatGPT projects feature quietly got folders", score=500),
        _reddit_post("Claude code review beats junior devs at bug hunts", score=400),
        _reddit_post("Gemini live camera mode is wild for cooking help", score=300),
        _reddit_post("LocalLLaMA benchmark shows small models closing gap", score=200),
        _reddit_post("Perplexity finance dashboards replaced my broker app", score=100),
    ]
    _patch_http(monkeypatch, reddit={"ChatGPT": _reddit_payload(posts)})

    topics = collect_community_topics(max_items=3)
    assert len(topics) == 3


# ---------------------------------------------------------------------------
# score_topic_boost
# ---------------------------------------------------------------------------


def _seed_topics(monkeypatch, topics: list[CommunityTopic]):
    monkeypatch.setattr(cts, "collect_community_topics", lambda max_items=30: list(topics))


def _topic(title: str, mention_score: int) -> CommunityTopic:
    return CommunityTopic(
        title=title,
        url="https://example.com",
        source="hackernews",
        mention_score=mention_score,
        comments=0,
        created_utc=NOW,
    )


def test_score_topic_boost_tiers(monkeypatch):
    _seed_topics(monkeypatch, [_topic("Deepseek releases frontier weights", 100)])
    boost, matched = score_topic_boost("Why Deepseek matters for open source")
    assert boost == 5
    assert "deepseek" in matched

    CommunityTopicSignal.reset_cache()
    _seed_topics(monkeypatch, [_topic("Deepseek releases frontier weights", 250)])
    boost, _ = score_topic_boost("Why Deepseek matters for open source")
    assert boost == 8

    CommunityTopicSignal.reset_cache()
    _seed_topics(monkeypatch, [_topic("Deepseek releases frontier weights", 900)])
    boost, _ = score_topic_boost("Why Deepseek matters for open source")
    assert boost == 12


def test_score_topic_boost_caps_at_max_boost(monkeypatch):
    _seed_topics(
        monkeypatch,
        [
            _topic("Gemini agents outperform expectations", 900),
            _topic("Gemini pricing shakes the market", 900),
        ],
    )
    boost, matched = score_topic_boost("Gemini pricing and agents deep dive")
    assert boost == 15
    assert matched

    CommunityTopicSignal.reset_cache()
    boost, _ = score_topic_boost("Gemini pricing and agents deep dive", max_boost=10)
    assert boost == 10


def test_score_topic_boost_no_match(monkeypatch):
    _seed_topics(monkeypatch, [_topic("Claude excels at long context tasks", 900)])
    boost, matched = score_topic_boost("Sourdough weekend baking guide")
    assert boost == 0
    assert matched == []


def test_score_topic_boost_ignores_stopword_only_overlap(monkeypatch):
    _seed_topics(monkeypatch, [_topic("What people think about this year", 900)])
    boost, _ = score_topic_boost("What people think about that stuff")
    assert boost == 0


def test_score_topic_boost_uses_cache(monkeypatch):
    call_count = {"n": 0}

    def fake_collect(max_items: int = 30):
        call_count["n"] += 1
        return [_topic("Claude agent workflows explained", 100)]

    monkeypatch.setattr(cts, "collect_community_topics", fake_collect)
    score_topic_boost("Claude agent workflows guide")
    score_topic_boost("Claude agent workflows guide")
    assert call_count["n"] == 1  # TTL 내 재호출은 캐시 사용


# ---------------------------------------------------------------------------
# 킬스위치 / 네트워크 실패
# ---------------------------------------------------------------------------


def test_kill_switch_disables_signal(monkeypatch):
    monkeypatch.setenv("ENABLE_COMMUNITY_TOPIC_SIGNAL", "false")

    def explode(url):
        raise AssertionError("network must not be touched when disabled")

    monkeypatch.setattr(cts, "_http_get_json", explode)

    assert collect_community_topics() == []
    boost, matched = score_topic_boost("ChatGPT agents everywhere")
    assert boost == 0
    assert matched == []


def test_http_failure_returns_empty(monkeypatch):
    def failing_urlopen(req, timeout=None):
        raise error.URLError("connection refused")

    monkeypatch.setattr(cts.request, "urlopen", failing_urlopen)

    assert collect_community_topics() == []
    boost, matched = score_topic_boost("ChatGPT agents everywhere")
    assert boost == 0
    assert matched == []


def test_malformed_json_returns_empty(monkeypatch):
    class _FakeResponse:
        def read(self):
            return b"<html>rate limited</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(cts.request, "urlopen", lambda req, timeout=None: _FakeResponse())
    assert collect_community_topics() == []
