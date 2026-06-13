from __future__ import annotations

from typing import Any

from blogspot_automation.models.news_models import ScoredNewsCandidate


class NewsImagePromptService:
    """Build Discover-ready image prompt metadata without generating images."""

    image_size_recommendation = "1200x675 or larger"
    image_usage_note = (
        "Use as a representative 16:9 blog cover image prompt only. "
        "Do not generate or insert an image during the news automation run."
    )

    def build(
        self,
        *,
        selected: ScoredNewsCandidate,
        selected_title: str,
    ) -> dict[str, str]:
        topic = (selected.candidate.topic or "").strip()
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        topic_group = str(raw.get("topic_group") or "general_life")
        content_angle = raw.get("content_angle") if isinstance(raw.get("content_angle"), dict) else {}
        content_type = str(content_angle.get("content_type") or "")
        content_type = content_type or self._content_type_for_topic_group(topic_group)

        concept = self._concept_for_content_type(content_type)
        safe_title = self._plain(selected_title)
        safe_topic = self._plain(topic)
        prompt = (
            f"Clean realistic editorial blog cover image for a Korean lifestyle decision blog. "
            f"Topic: {safe_topic}. Title context: {safe_title}. "
            f"Scene: {concept}. "
            "Calm trustworthy mood, natural daylight, modern composition, practical everyday objects, "
            "16:9 aspect ratio, suitable for 1200x675 or larger, fast-loading web cover image, "
            "no text, no readable letters, no logo, no watermark, no brand marks, "
            "no clickbait, no exaggerated emotion, no fear, no sensational style."
        )
        return {
            "image_prompt": prompt,
            "image_alt_text": self._alt_text(
                title=safe_title,
                topic=safe_topic,
                content_type=content_type,
            ),
            "image_size_recommendation": self.image_size_recommendation,
            "image_usage_note": self.image_usage_note,
        }

    @staticmethod
    def _content_type_for_topic_group(topic_group: str) -> str:
        return {
            "delivery_money": "money_checklist",
            "refund_consumer": "consumer_warning",
            "ai_work": "ai_work_tip",
            "trend_meme": "trend_decode",
            "entertainment_sports": "trend_decode",
            "policy_benefit": "policy_deadline",
            "platform_issue": "platform_change",
        }.get(topic_group, "general_life")

    @staticmethod
    def _concept_for_content_type(content_type: str) -> str:
        concepts = {
            "policy_deadline": (
                "a calendar deadline, checklist document, and government support application concept "
                "on a clean desk"
            ),
            "money_checklist": (
                "a smartphone payment screen concept without readable text, receipts, and a cost comparison checklist"
            ),
            "consumer_warning": (
                "an online shopping refund checklist concept with receipt, smartphone, and calm customer support icons"
            ),
            "platform_change": (
                "a smartphone app update and service change concept with device compatibility cues"
            ),
            "ai_work_tip": (
                "an office desk with laptop, workflow notes, checklist, and subtle AI productivity concept"
            ),
            "trend_decode": (
                "a social media trend and product queue concept focused on consumer choice"
            ),
        }
        return concepts.get(
            content_type,
            "a practical lifestyle decision checklist with smartphone, notes, and everyday planning objects",
        )

    @staticmethod
    def _alt_text(*, title: str, topic: str, content_type: str) -> str:
        subject = title or topic or "오늘 이슈"
        suffix = {
            "policy_deadline": "신청 마감과 대상 조건 확인을 상징하는 체크리스트 이미지",
            "money_checklist": "최종 결제금액과 비용 비교를 상징하는 이미지",
            "consumer_warning": "환불 증거와 소비자 대응 체크리스트를 상징하는 이미지",
            "platform_change": "앱 변경과 서비스 종료 확인을 상징하는 이미지",
            "ai_work_tip": "AI 업무 설정과 생산성 점검을 상징하는 사무공간 이미지",
            "trend_decode": "트렌드 소비 전 선택 기준을 상징하는 생활 이미지",
        }.get(content_type, "생활 의사결정 기준을 상징하는 체크리스트 이미지")
        return f"{subject}와 관련해 {suffix}"

    @staticmethod
    def _plain(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()
