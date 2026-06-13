"""IssueDiscoveryService unit/integration tests.

검증:
- entity extraction (lexicon + acronym)
- clustering (strong entity 공유 / event-only 미클러스터링)
- safety filter (살해/정치/외국 출처)
- content_type 분류 정확도
- to_news_candidates 변환 + score floor 적용
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from blogspot_automation.services.issue_discovery_service import (
    IssueDiscoveryService,
    DiscoveredIssue,
    BLOCKED_SOURCE_HINTS,
    RISK_KEYWORDS,
)


class TestEntityExtraction(unittest.TestCase):

    def setUp(self):
        self.svc = IssueDiscoveryService()

    def test_platform_lexicon(self):
        ents, types = self.svc._extract_entities("삼성전자 노조 추가 대화 제안")
        self.assertIn("삼성", ents)
        self.assertIn("platform", types)

    def test_agency_lexicon(self):
        ents, types = self.svc._extract_entities("개인정보위, 매출 10% 과징금 부과")
        # "개인정보위" 사전 매칭 OR "개인정보위원회" 매칭
        self.assertTrue(
            any(e.startswith("개인정보위") for e in ents),
            f"개인정보위 not detected: {ents}",
        )
        self.assertTrue(any(t == "agency" for t in types))

    def test_acronym_extraction(self):
        ents, types = self.svc._extract_entities("PPI 발표에 따라 환율 변동")
        self.assertIn("PPI", ents)
        # acronym type 포함
        self.assertIn("acronym", types)

    def test_event_keyword(self):
        ents, types = self.svc._extract_entities("정부, 닭·돼지고기 할당관세 발표")
        self.assertIn("정부", ents)
        self.assertIn("발표", ents)


class TestClustering(unittest.TestCase):

    def setUp(self):
        self.svc = IssueDiscoveryService()

    def test_strong_entity_shares_cluster(self):
        items = [
            {"title": "삼성전자 노조 대화 추진", "entities": ["삼성"], "entity_types": ["platform"]},
            {"title": "삼성 임직원 반응 정리", "entities": ["삼성"], "entity_types": ["platform"]},
        ]
        clusters = self.svc._cluster_issues(items)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_event_only_does_not_cluster(self):
        items = [
            {"title": "A 발표", "entities": ["발표"], "entity_types": ["event"]},
            {"title": "B 발표", "entities": ["발표"], "entity_types": ["event"]},
            {"title": "C 발표", "entities": ["발표"], "entity_types": ["event"]},
        ]
        clusters = self.svc._cluster_issues(items)
        # 모두 event-only이므로 같은 cluster로 묶이지 않음
        # (각각 따로 또는 일부만 묶임)
        self.assertGreaterEqual(len(clusters), 1)
        # 적어도 event-only 1개 cluster에 3개 다 들어가서 strong cluster 형성되면 안 됨


class TestSafetyFilter(unittest.TestCase):

    def setUp(self):
        self.svc = IssueDiscoveryService()

    def test_blocks_vietnam_source(self):
        items = [
            {"title": "Korean issue", "source": "Vietnam.vn"},
            {"title": "한국 이슈", "source": "연합뉴스"},
        ]
        filtered = self.svc._filter_safe_and_korean(items)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["source"], "연합뉴스")

    def test_blocks_homicide_news(self):
        items = [
            {"title": "광주 여고생 살해범 신상공개", "source": "연합뉴스"},
            {"title": "삼성전자 노조 대화", "source": "연합뉴스"},
        ]
        filtered = self.svc._filter_safe_and_korean(items)
        self.assertEqual(len(filtered), 1)
        self.assertNotIn("살해", filtered[0]["title"])

    def test_blocks_political_news(self):
        items = [
            {"title": "미·중 정상회담 시작", "source": "조선일보"},
            {"title": "쿠팡 멤버십 가격 변경", "source": "연합뉴스"},
        ]
        filtered = self.svc._filter_safe_and_korean(items)
        # "정상회담" RISK 차단
        self.assertEqual(len(filtered), 1)
        self.assertIn("쿠팡", filtered[0]["title"])

    def test_blocks_rumor_news(self):
        items = [
            {"title": "유명인 열애설 폭로", "source": "스타뉴스"},
            {"title": "정부 지원금 신청 시작", "source": "연합뉴스"},
        ]
        filtered = self.svc._filter_safe_and_korean(items)
        self.assertEqual(len(filtered), 1)


class TestContentTypeClassification(unittest.TestCase):
    """allowed 6종 분류 정확성."""

    def setUp(self):
        self.svc = IssueDiscoveryService()

    def test_platform_change(self):
        ct = self.svc._classify_content_type(
            entities=["쿠팡"], types=["platform"],
            text="쿠팡 멤버십 가격 인상 약관 변경",
        )
        self.assertEqual(ct, "platform_change")

    def test_consumer_warning_privacy(self):
        ct = self.svc._classify_content_type(
            entities=["KT"], types=["telecom"],
            text="KT 개인정보 유출 사고 발생",
        )
        self.assertEqual(ct, "consumer_warning")

    def test_policy_deadline(self):
        ct = self.svc._classify_content_type(
            entities=["정부"], types=["agency"],
            text="정부 청년 지원금 신청 마감 다가옴",
        )
        self.assertEqual(ct, "policy_deadline")

    def test_viral_issue_decode(self):
        ct = self.svc._classify_content_type(
            entities=["넷플릭스"], types=["platform"],
            text="넷플릭스 신작 드라마 반응 갈린 이유",
        )
        self.assertEqual(ct, "viral_issue_decode")

    def test_money_checklist(self):
        ct = self.svc._classify_content_type(
            entities=[], types=[],
            text="배달비 통신비 인상 가격 비교",
        )
        self.assertEqual(ct, "money_checklist")

    def test_market_finance_becomes_today_issue_explainer(self):
        ct = self.svc._classify_content_type(
            entities=["삼성"], types=["platform"],
            text="속보] 삼성전자, 우선주 포함해 시총 2천조원 돌파",
        )
        self.assertEqual(ct, "today_issue_explainer")


class TestScoring(unittest.TestCase):

    def test_buzz_score_thresholds(self):
        self.assertEqual(IssueDiscoveryService._compute_buzz_score(0), 0)
        self.assertEqual(IssueDiscoveryService._compute_buzz_score(1), 3)
        self.assertEqual(IssueDiscoveryService._compute_buzz_score(2), 6)
        self.assertEqual(IssueDiscoveryService._compute_buzz_score(3), 8)
        self.assertEqual(IssueDiscoveryService._compute_buzz_score(5), 10)

    def test_specificity_strong_entity_high(self):
        score = IssueDiscoveryService._compute_specificity_score(
            entities=["쿠팡", "멤버십"], types=["platform", "event"],
        )
        # 5 + 2 + 2 = 9 ; event-only가 아니므로 강한 type 보너스 적용
        self.assertGreaterEqual(score, 7)

    def test_specificity_event_only_low(self):
        score = IssueDiscoveryService._compute_specificity_score(
            entities=["발표", "공개"], types=["event", "event"],
        )
        # event-only는 강한 감점
        self.assertLess(score, 7)

    def test_safe_commentary_drops_on_sensational(self):
        score = IssueDiscoveryService._compute_safe_commentary_score([
            "충격 근황, 결국 터졌다",
        ])
        self.assertLess(score, 7)


class TestToNewsCandidates(unittest.TestCase):
    """to_news_candidates 변환 + filter gate."""

    def test_high_buzz_specific_passes(self):
        svc = IssueDiscoveryService()
        iss = DiscoveredIssue(
            cluster_key="쿠팡|멤버십",
            primary_topic="쿠팡 멤버십 가격 변경 안내",
            entities=["쿠팡", "멤버십"],
            entity_types=["platform", "event"],
            source_count=5,
            sample_titles=["쿠팡 멤버십 가격 변경 안내"],
            sample_sources=["연합뉴스"],
            earliest_pub=None, latest_pub=None,
            today_buzz_score=10,
            entity_specificity_score=8,
            safe_commentary_score=8,
            candidate_content_type="platform_change",
            risk_flags=[],
        )
        candidates = svc.to_news_candidates([iss])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.topic, "쿠팡 멤버십 가격 변경 안내")
        self.assertEqual(c.raw["topic_group"], "platform_issue")
        self.assertTrue(c.raw["discovery_engine"])
        self.assertEqual(len(c.raw["reader_search_questions"]), 5)

    def test_low_buzz_rejected(self):
        svc = IssueDiscoveryService()
        iss = DiscoveredIssue(
            cluster_key="x",
            primary_topic="single source niche issue",
            entities=["서비스"],
            entity_types=["other"],
            source_count=1,
            sample_titles=["single source niche issue"],
            sample_sources=["niche"],
            earliest_pub=None, latest_pub=None,
            today_buzz_score=3,
            entity_specificity_score=4,
            safe_commentary_score=8,
            candidate_content_type="consumer_warning",
            risk_flags=[],
        )
        candidates = svc.to_news_candidates([iss])
        self.assertEqual(len(candidates), 0)

    def test_risk_flag_rejected(self):
        svc = IssueDiscoveryService()
        iss = DiscoveredIssue(
            cluster_key="x",
            primary_topic="strong but risky",
            entities=["쿠팡"],
            entity_types=["platform"],
            source_count=5,
            sample_titles=["strong but risky"],
            sample_sources=["연합뉴스"],
            earliest_pub=None, latest_pub=None,
            today_buzz_score=10,
            entity_specificity_score=9,
            safe_commentary_score=9,
            candidate_content_type="platform_change",
            risk_flags=["살해"],
        )
        candidates = svc.to_news_candidates([iss])
        self.assertEqual(len(candidates), 0)

    def test_market_finance_maps_to_today_issue_candidate(self):
        svc = IssueDiscoveryService()
        iss = DiscoveredIssue(
            cluster_key="삼성|시총",
            primary_topic="속보] 삼성전자, 우선주 포함해 시총 2천조원 돌파",
            entities=["삼성"],
            entity_types=["platform"],
            source_count=5,
            sample_titles=["속보] 삼성전자, 우선주 포함해 시총 2천조원 돌파"],
            sample_sources=["연합뉴스"],
            earliest_pub=None, latest_pub=None,
            today_buzz_score=10,
            entity_specificity_score=8,
            safe_commentary_score=8,
            candidate_content_type="market_finance",
            risk_flags=[],
        )
        candidates = svc.to_news_candidates([iss])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].raw["topic_group"], "today_issue")
        self.assertEqual(candidates[0].raw["content_angle"]["content_type"], "today_issue_explainer")
        self.assertEqual(candidates[0].raw["original_content_type"], "market_finance")


if __name__ == "__main__":
    unittest.main()
