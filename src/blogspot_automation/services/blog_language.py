"""블로그 출력 언어 스위치 (2026-07-17 영어 전환).

holyyomiai.blogspot.com을 영어권(미국·영국·캐나다·인도) 독자 대상 영어 AI 블로그로
전환하기 위한 단일 진실 소스. BLOG_LANGUAGE 환경변수 하나로 파이프라인 전체의
언어 분기(주제 쿼리, 프롬프트, GEO 블록, 게이트 텀뱅크)를 통제한다.

- 기본값 "ko": 기존 한국어 동작·테스트를 그대로 보존한다.
- "en": cli_ai.py가 기본값으로 설정 — ai_blog.yml 스케줄 경로가 자동으로 영어 모드.
  (워크플로 파일·발행 로직·스케줄은 건드리지 않는다.)
"""
from __future__ import annotations

import os

_EN_VALUES = {"en", "en-us", "en_us", "english"}


def blog_language() -> str:
    """현재 출력 언어 코드 반환: "en" 또는 "ko"."""
    raw = os.getenv("BLOG_LANGUAGE", "ko").strip().lower()
    return "en" if raw in _EN_VALUES else "ko"


def is_english_mode() -> bool:
    """영어 블로그 모드 여부 — 콘텐츠·게이트·템플릿의 언어 분기 지점에서 사용."""
    return blog_language() == "en"
