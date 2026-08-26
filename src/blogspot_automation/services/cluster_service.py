"""주제 클러스터 — 흩어진 일일 뉴스 대신 한 주제를 6~7편으로 묶는다.

배경(2026-08-26): 사이트맵 32 URL 중 색인 0건, 검색 노출 0. GSC 실측 진단에서
남은 원인 세 개 중 두 개가 "외부 링크 0 → 권위 0"과 "주제 분산"이었다. 32편이
전부 다른 AI 뉴스라 구글 입장에서 이 사이트가 무엇의 전문가인지 판정할 근거가
없다. 이 서비스는 그중 '주제 분산'을 코드로 푼다.

설계 원칙(과거 사고에서 나온 것들):

1. **상태 파일을 새로 만들지 않는다.** 진행 상황은 data/publish_history.json의
   ``cluster_slot`` 필드로만 판정한다. 원장과 별도 상태를 두면 둘이 어긋나고,
   그 desync가 이 저장소에서 이미 한 번 발행 사고를 냈다.

2. **후보를 주입할 뿐 뉴스 파이프라인을 대체하지 않는다.** 클러스터 요일이
   아니면 아무 일도 하지 않고, 클러스터 요일이어도 후보 하나를 기존 후보 앞에
   얹을 뿐이다. 클러스터가 게이트에 막히면 그날은 평소의 뉴스 경로가 그대로
   돈다 — 클러스터 도입이 발행 0건을 만들 수 없는 구조.

3. **source_type은 evergreen_fallback을 그대로 쓴다.** 새 source_type을 만들면
   신선도·자동발행 허용·골든패턴 등 source_type을 분기하는 지점 전부를 다시
   통과시켜야 하고, 하나라도 놓치면 "후보는 뽑혔는데 발행은 안 되는" 조용한
   0건이 된다. live_ai_demand_topic_service도 같은 이유로 이 값을 재사용한다.
   클러스터 여부는 ``topic_cluster``/``cluster_slot`` 마커로 따로 식별한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import logging
import os
from pathlib import Path
from typing import Any

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.blog_language import is_english_mode

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("config/clusters.json")
# 월/수/금/일 = 주 4일 클러스터, 나머지 3일은 기존 뉴스 경로.
_DEFAULT_CLUSTER_WEEKDAYS = "0,2,4,6"


@dataclass(frozen=True, slots=True)
class ClusterSlot:
    slot_id: str
    topic: str
    search_demand_topic: str
    questions: tuple[str, ...]
    click_reason: str
    reader_benefit: str
    content_promise: str
    angle_type: str
    is_pillar: bool = False


@dataclass(frozen=True, slots=True)
class ClusterPlan:
    key: str
    name: str
    why: str
    topic_group: str
    content_type: str
    slots: tuple[ClusterSlot, ...]

    @property
    def child_slots(self) -> tuple[ClusterSlot, ...]:
        return tuple(slot for slot in self.slots if not slot.is_pillar)

    @property
    def pillar_slots(self) -> tuple[ClusterSlot, ...]:
        return tuple(slot for slot in self.slots if slot.is_pillar)


@dataclass(frozen=True, slots=True)
class ClusterProgress:
    plan: ClusterPlan
    done_slot_ids: frozenset[str]
    next_slot: ClusterSlot | None

    @property
    def done_count(self) -> int:
        return len([slot for slot in self.plan.slots if slot.slot_id in self.done_slot_ids])

    @property
    def total_count(self) -> int:
        return len(self.plan.slots)

    @property
    def complete(self) -> bool:
        return self.next_slot is None


class ClusterService:
    """활성 클러스터의 '다음에 쓸 글' 하나를 후보로 만들어 준다."""

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        cluster_key: str = "",
    ) -> None:
        self.config_path = Path(
            config_path
            or (os.getenv("CLUSTER_CONFIG_PATH", "").strip() or _DEFAULT_CONFIG_PATH)
        )
        self._cluster_key_override = (
            cluster_key or os.getenv("ACTIVE_CLUSTER_KEY", "").strip()
        )
        self._plan_cache: ClusterPlan | None = None
        self._plan_loaded = False

    # ------------------------------------------------------------------ config

    def active_plan(self) -> ClusterPlan | None:
        if self._plan_loaded:
            return self._plan_cache
        self._plan_loaded = True
        self._plan_cache = self._load_plan()
        return self._plan_cache

    def _load_plan(self) -> ClusterPlan | None:
        if not self.config_path.exists():
            logger.info("cluster config not found (skipping cluster): %s", self.config_path)
            return None
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 설정 오류가 발행을 막으면 안 된다
            logger.warning("cluster config load failed (skipping cluster): %s", exc)
            return None
        if not isinstance(payload, dict):
            return None

        wanted = self._cluster_key_override or str(payload.get("active_cluster") or "").strip()
        if not wanted:
            return None
        clusters = payload.get("clusters")
        if not isinstance(clusters, list):
            return None
        for entry in clusters:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("key") or "").strip() != wanted:
                continue
            return self._parse_plan(entry)
        logger.warning("active cluster '%s' not found in %s", wanted, self.config_path)
        return None

    @staticmethod
    def _parse_plan(entry: dict[str, Any]) -> ClusterPlan | None:
        slots: list[ClusterSlot] = []
        for raw_slot in entry.get("slots") or []:
            if not isinstance(raw_slot, dict):
                continue
            slot_id = str(raw_slot.get("slot_id") or "").strip()
            topic = str(raw_slot.get("topic") or "").strip()
            search_topic = str(raw_slot.get("search_demand_topic") or "").strip()
            if not slot_id or not topic or not search_topic:
                logger.warning("cluster slot skipped (missing required field): %s", slot_id or raw_slot)
                continue
            questions = tuple(
                str(question).strip()
                for question in (raw_slot.get("questions") or [])
                if str(question).strip()
            )
            slots.append(
                ClusterSlot(
                    slot_id=slot_id,
                    topic=topic,
                    search_demand_topic=search_topic,
                    questions=questions,
                    click_reason=str(raw_slot.get("click_reason") or "").strip(),
                    reader_benefit=str(raw_slot.get("reader_benefit") or "").strip(),
                    content_promise=str(raw_slot.get("content_promise") or "").strip(),
                    angle_type=str(raw_slot.get("angle_type") or "money_compare").strip(),
                    is_pillar=bool(raw_slot.get("is_pillar")),
                )
            )
        if not slots:
            return None
        return ClusterPlan(
            key=str(entry.get("key") or "").strip(),
            name=str(entry.get("name") or "").strip(),
            why=str(entry.get("why") or "").strip(),
            topic_group=str(entry.get("topic_group") or "ai_work").strip(),
            content_type=str(entry.get("content_type") or "ai_work_tip").strip(),
            slots=tuple(slots),
        )

    # ---------------------------------------------------------------- progress

    def progress(self, history_records: list[dict[str, Any]] | None) -> ClusterProgress | None:
        plan = self.active_plan()
        if plan is None:
            return None
        done = self.done_slot_ids(history_records, cluster_key=plan.key)
        return ClusterProgress(
            plan=plan,
            done_slot_ids=done,
            next_slot=self._next_slot(plan, done),
        )

    @staticmethod
    def done_slot_ids(
        history_records: list[dict[str, Any]] | None,
        *,
        cluster_key: str,
    ) -> frozenset[str]:
        """원장에서 '이미 라이브에 존재하는' 이 클러스터의 슬롯 ID들.

        발행 판정은 PublishHistoryService.is_published_record를 그대로 쓴다 —
        같은 질문에 두 개의 답이 생기면 반드시 어긋난다.
        """
        from blogspot_automation.services.publish_history_service import PublishHistoryService

        done: set[str] = set()
        for record in history_records or []:
            if not isinstance(record, dict):
                continue
            if str(record.get("cluster_key") or "").strip() != cluster_key:
                continue
            slot_id = str(record.get("cluster_slot") or "").strip()
            if not slot_id:
                continue
            if not PublishHistoryService.is_published_record(record):
                continue
            done.add(slot_id)
        return frozenset(done)

    @staticmethod
    def _next_slot(plan: ClusterPlan, done: frozenset[str]) -> ClusterSlot | None:
        # 자식 글이 전부 발행된 뒤에야 허브(pillar)를 쓴다. 허브는 자식 글들을
        # 링크하는 글이라, 링크할 대상이 없는 시점에 먼저 나오면 의미가 없다.
        for slot in plan.child_slots:
            if slot.slot_id not in done:
                return slot
        for slot in plan.pillar_slots:
            if slot.slot_id not in done:
                return slot
        return None

    # -------------------------------------------------------------- scheduling

    @staticmethod
    def enabled() -> bool:
        return str(os.getenv("ENABLE_TOPIC_CLUSTER", "true")).strip().lower() in {
            "1", "true", "yes", "on",
        }

    @staticmethod
    def cluster_weekdays() -> frozenset[int]:
        raw = (os.getenv("CLUSTER_WEEKDAYS", "") or "").strip() or _DEFAULT_CLUSTER_WEEKDAYS
        days: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = int(chunk)
            except ValueError:
                continue
            if 0 <= value <= 6:
                days.add(value)
        return frozenset(days)

    @classmethod
    def is_cluster_day(cls, today: date | None = None) -> bool:
        return (today or date.today()).weekday() in cls.cluster_weekdays()

    # -------------------------------------------------------------- candidates

    def collect_candidates(
        self,
        history_records: list[dict[str, Any]] | None,
        *,
        today: date | None = None,
        ignore_schedule: bool = False,
    ) -> list[NewsCandidate]:
        """오늘 쓸 클러스터 후보(0개 또는 1개).

        0개를 돌려주는 경우는 전부 정상 동작이다 — 기능 꺼짐, 클러스터 요일
        아님, 클러스터 완주. 어느 쪽이든 호출부는 평소의 뉴스 경로로 간다.
        """
        if not self.enabled():
            return []
        if not ignore_schedule and not self.is_cluster_day(today):
            return []
        progress = self.progress(history_records)
        if progress is None or progress.next_slot is None:
            if progress is not None:
                logger.info(
                    "topic_cluster '%s' complete (%d/%d) — 새 클러스터를 config/clusters.json에 넣을 때다",
                    progress.plan.key, progress.done_count, progress.total_count,
                )
            return []
        logger.info(
            "topic_cluster '%s': slot %s (%d/%d 완료) 후보 주입",
            progress.plan.key,
            progress.next_slot.slot_id,
            progress.done_count,
            progress.total_count,
        )
        return [self.to_candidate(progress.plan, progress.next_slot)]

    @staticmethod
    def to_candidate(plan: ClusterPlan, slot: ClusterSlot) -> NewsCandidate:
        questions = list(slot.questions) or [slot.search_demand_topic]
        search_angle: dict[str, Any] = {
            "original_topic": slot.topic,
            "search_demand_topic": slot.search_demand_topic,
            "reader_search_questions": questions,
            "click_reason": slot.click_reason,
            "reader_benefit": slot.reader_benefit,
            "urgency_reason": "Free-tier limits change without notice; a current, measured answer wins the click.",
            "content_promise": slot.content_promise,
            "angle_type": slot.angle_type,
            "should_transform_title": True,
            "commercial_support_signal": False,
            "generic_support_keyword": "",
            "public_benefit_keyword": "",
            "public_benefit_confidence": "none",
            "public_benefit_promotion_blocked": False,
        }
        content_angle = {
            "content_type": plan.content_type,
            "reader_question": questions[0],
            "reader_loss": slot.click_reason,
            "practical_value": slot.reader_benefit,
            "example_needed": True,
        }
        return NewsCandidate(
            topic=slot.search_demand_topic,
            category="tech",
            summary=f"{slot.topic} — measured, numbers-first answer for people running a daily job on free tiers.",
            source_hint="evergreen_fallback",
            published_at=None,
            url=None,
            raw={
                # source_type은 의도적으로 evergreen_fallback (모듈 docstring 3번 참고).
                "source": "topic_cluster",
                "source_type": "evergreen_fallback",
                "is_test_candidate": False,
                "publish_allowed": True,
                "evergreen_axis": "ai_automation",
                "evergreen_reason": plan.why or "One topic, covered deeply enough to be the reference for it.",
                "evergreen_fallback": True,
                "is_stale": False,
                # 클러스터 마커 — 이 세 개로만 클러스터 후보를 식별한다.
                "topic_cluster": True,
                "cluster_key": plan.key,
                "cluster_slot": slot.slot_id,
                "cluster_is_pillar": slot.is_pillar,
                "cluster_name": plan.name,
                "target_reader": (
                    "developers and solo builders running small automated jobs (US/UK/CA/IN)"
                    if is_english_mode()
                    else "직접 자동화를 돌리는 개발자·1인 운영자"
                ),
                "query_group": "ai_automation",
                "topic_group": plan.topic_group,
                "content_angle": content_angle,
                "search_angle": search_angle,
                "search_demand_topic": slot.search_demand_topic,
                # 골든 패턴 매칭은 topic + search_demand_topic + 질문 2개 +
                # sample_titles로 판정한다. 슬롯의 서술형 topic을 여기 넣지 않으면
                # 매칭에 쓰이는 텍스트가 검색어 한 줄뿐이라, 실제로는 AI 도구
                # 비교·가격 글인데 패턴이 안 붙어 article_candidate가 생성되지
                # 않는다(2026-08-26 실측: confidence 52, 기준 80).
                "sample_titles": [slot.topic],
                "reader_search_questions": questions,
                "click_reason": slot.click_reason,
                "reader_benefit": slot.reader_benefit,
                "urgency_reason": search_angle["urgency_reason"],
                "content_promise": slot.content_promise,
                "angle_type": slot.angle_type,
            },
        )


def is_cluster_candidate(raw: Any) -> bool:
    """후보(raw dict)가 클러스터 후보인지. 게이트/쿨다운 예외 판정에 쓴다."""
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("topic_cluster")) and bool(str(raw.get("cluster_slot") or "").strip())
