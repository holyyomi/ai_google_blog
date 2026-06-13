from __future__ import annotations

from dataclasses import dataclass

from blogspot_automation.topic_discovery.parser import ParsedItem


PRIMARY_VERTICALS = {
    "automation_workflows",
    "ai_tool_reviews",
}


@dataclass(slots=True)
class TopicStrategy:
    topic_cluster: str
    topic_subcluster: str
    content_mode: str
    main_keyword: str
    supporting_keywords: list[str]
    user_intent: str
    audience_level: str
    geo_targeting_hint: str
    age_targeting_hint: str
    search_angle: str
    monetization_angle: str
    automation_angle: str


def build_topic_strategy(
    *,
    item: ParsedItem,
    topic_name: str,
    keyword_primary: str,
    keyword_secondary: list[str],
) -> TopicStrategy:
    cluster, subcluster = _classify_cluster(item)
    content_mode = _classify_content_mode(item)
    user_intent = _classify_user_intent(cluster, item)
    audience_level = _classify_audience_level(item)
    return TopicStrategy(
        topic_cluster=cluster,
        topic_subcluster=subcluster,
        content_mode=content_mode,
        main_keyword=keyword_primary,
        supporting_keywords=keyword_secondary,
        user_intent=user_intent,
        audience_level=audience_level,
        geo_targeting_hint=_geo_hint(cluster),
        age_targeting_hint=_age_hint(cluster),
        search_angle=_search_angle(cluster, content_mode, topic_name),
        monetization_angle=_monetization_angle(cluster),
        automation_angle=_automation_angle(cluster),
    )


def cluster_priority_bonus(cluster: str) -> float:
    return 0.08 if cluster in PRIMARY_VERTICALS else 0.0


def _classify_cluster(item: ParsedItem) -> tuple[str, str]:
    haystack = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
    if any(term in haystack for term in ("workflow", "automation", "agent", "integration", "zapier")):
        return "automation_workflows", "agent_workflows"
    if any(term in haystack for term in ("tool", "platform", "app", "assistant", "copilot")):
        return "ai_tool_reviews", "product_capabilities"
    if any(term in haystack for term in ("marketing", "seo", "ads", "campaign", "content marketing")):
        return "ai_marketing", "growth_workflows"
    if any(term in haystack for term in ("prompt", "prompting", "system prompt")):
        return "prompts_prompting_systems", "prompt_design"
    if any(term in haystack for term in ("pricing", "enterprise", "team", "business", "roi")):
        return "ai_business_strategy", "adoption_strategy"
    return "ai_policy_infrastructure_major_launches", "major_launch_explainer"


def _classify_content_mode(item: ParsedItem) -> str:
    haystack = f"{item.title} {item.summary}".lower()
    if any(term in haystack for term in ("launch", "release", "update", "announces", "new")):
        return "news_explainer"
    return "evergreen_explainer"


def _classify_user_intent(cluster: str, item: ParsedItem) -> str:
    haystack = f"{item.title} {item.summary}".lower()
    if "pricing" in haystack or "compare" in haystack:
        return "commercial_investigation"
    if cluster in {"automation_workflows", "prompts_prompting_systems"}:
        return "how_to"
    if cluster in {"ai_tool_reviews", "ai_business_strategy"}:
        return "evaluation"
    return "informational"


def _classify_audience_level(item: ParsedItem) -> str:
    haystack = f"{item.title} {item.summary}".lower()
    if any(term in haystack for term in ("api", "sdk", "developer", "benchmark")):
        return "intermediate"
    return "beginner_to_intermediate"


def _geo_hint(cluster: str) -> str:
    if cluster == "ai_marketing":
        return "Prioritize globally relevant search demand and English-speaking market examples."
    return "Use globally understandable examples first, then note region-specific implications only when needed."


def _age_hint(cluster: str) -> str:
    if cluster == "automation_workflows":
        return "Target readers who use AI answer engines to find workflow shortcuts and actionable tool stacks."
    return "Target readers who ask AI answer engines for concise definitions, comparisons, and adoption guidance."


def _search_angle(cluster: str, content_mode: str, topic_name: str) -> str:
    if content_mode == "news_explainer":
        return f"Explain what changed in {topic_name}, why it matters now, and how to act on it."
    if cluster == "ai_tool_reviews":
        return f"Review {topic_name} through practical use cases, limits, and selection criteria."
    return f"Explain {topic_name} with intent-rich examples, operational steps, and decision points."


def _monetization_angle(cluster: str) -> str:
    mapping = {
        "ai_tool_reviews": "Affiliate or consulting angle through tool selection and implementation guidance.",
        "ai_marketing": "Lead generation, agency service packaging, and campaign optimization angle.",
        "prompts_prompting_systems": "Template products, training, and workflow consulting angle.",
        "automation_workflows": "Automation service retainers and internal productivity consulting angle.",
        "ai_business_strategy": "Advisory, workshops, and implementation roadmap angle.",
        "ai_policy_infrastructure_major_launches": "Executive briefings and strategy newsletter angle.",
    }
    return mapping[cluster]


def _automation_angle(cluster: str) -> str:
    mapping = {
        "ai_tool_reviews": "Focus on where the tool fits into a repeatable automation stack.",
        "ai_marketing": "Connect the topic to repeatable campaign, reporting, and distribution workflows.",
        "prompts_prompting_systems": "Show prompt systems as reusable operating procedures.",
        "automation_workflows": "Emphasize trigger-action chains, human review gates, and orchestration patterns.",
        "ai_business_strategy": "Connect strategy choices to scalable internal operating workflows.",
        "ai_policy_infrastructure_major_launches": "Explain how policy or infrastructure changes alter automation risk and deployment design.",
    }
    return mapping[cluster]
