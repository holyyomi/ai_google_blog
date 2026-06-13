from __future__ import annotations

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


def test_advisory_issues_do_not_trigger_deletion():
    # missing head meta description + canonical (theme-controlled) must NOT delete a live post
    audit = {
        "passed": False,
        "issues": [
            "canonical_not_self_referencing",
            "answer_engine_blocks_missing_or_incomplete",
            "weak_permalink_slug",
        ],
    }
    assert NewsPipeline._post_publish_fatal_issues(audit) == []


def test_fatal_issues_trigger_deletion():
    audit = {
        "passed": False,
        "issues": [
            "published_title_mismatch",
            "canonical_not_self_referencing",  # advisory, ignored
            "ai_topic_leaked_to_news_blog",
        ],
    }
    fatal = NewsPipeline._post_publish_fatal_issues(audit)
    assert "published_title_mismatch" in fatal
    assert "ai_topic_leaked_to_news_blog" in fatal
    assert "canonical_not_self_referencing" not in fatal


def test_title_integrity_prefix_is_fatal():
    audit = {"issues": ["published_title_integrity:clickbait_marker"]}
    assert NewsPipeline._post_publish_fatal_issues(audit) == [
        "published_title_integrity:clickbait_marker"
    ]


def test_empty_audit_has_no_fatal_issues():
    assert NewsPipeline._post_publish_fatal_issues({}) == []
    assert NewsPipeline._post_publish_fatal_issues({"issues": None}) == []
