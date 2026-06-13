from __future__ import annotations

from pathlib import Path
import sys
import datetime

SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
import streamlit.components.v1 as components

from blogspot_automation.ui.service import (
    find_today_topic,
    generate_content,
    get_work_item_snapshot,
    publish_content,
    run_qa,
)
from blogspot_automation.ui.scheduler import start_scheduler, stop_scheduler

# ──────────────────────────────────────────────────────────────
# Clean Typography & Button Styling
# ──────────────────────────────────────────────────────────────
CLEAN_CSS = """<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
* { font-family: 'Pretendard', sans-serif !important; }
/* Custom Buttons (Subtle gradient) */
.stButton>button { width: 100%; border-radius: 8px; height: 3rem; font-weight: 600; transition: all 0.2s ease; }
.stButton>button[kind="primary"] { background: linear-gradient(90deg, #1d4ed8, #2563eb); color: white; border: none; }
.stButton>button[kind="primary"]:hover { background: linear-gradient(90deg, #1e40af, #1d4ed8); box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4); }
/* Dashboard Metric Styling */
[data-testid="stMetricValue"] { font-size: 2rem !important; font-weight: 700 !important; color: #2563eb; }
[data-testid="stMetricLabel"] { font-size: 0.9rem !important; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
/* Article Preview Frame */
iframe { border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); background: #ffffff; }
</style>"""

ROOT_DIR = Path(".")

st.set_page_config(
    page_title="블로그 자동화 시스템 (One-Click)",
    page_icon="🤖",
    layout="wide",
)

# ──────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────
def _init() -> None:
    defaults = {
        "current_work_item_id": None,
        "ui_error": None,
        "scheduler_active": False,
        "schedule_time": datetime.time(7, 30),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if not st.session_state["current_work_item_id"]:
        try:
            from blogspot_automation.app.runtime import build_service_runtime
            _svc = build_service_runtime(root_dir=ROOT_DIR)
            _items = _svc.work_repo.list_recent(limit=20)
            _best = next((i for i in _items if i.article_html and not i.id.startswith("test-")), None)
            if _best:
                st.session_state["current_work_item_id"] = _best.id
        except Exception:
            pass

def _err(msg: str) -> None:
    st.session_state["ui_error"] = msg

def _clear_err() -> None:
    st.session_state["ui_error"] = None

# ──────────────────────────────────────────────────────────────
# One-Click Action Handlers
# ──────────────────────────────────────────────────────────────
def _do_auto_generate() -> None:
    _clear_err()
    with st.spinner("🤖 자동화 파이프라인 가동 중... (주제 탐색 ➜ 콘텐츠 생성 ➜ 품질 검증) | 약 2~3분 소요"):
        try:
            # 1. Topic discovery
            st.toast("📡 오늘의 신규 주제 탐색 중...")
            topic_payload = find_today_topic(root_dir=ROOT_DIR)
            wid = topic_payload.get("saved_work_item_id")
            
            if topic_payload.get("publish_status") in ("planned_fail", "source_insufficient"):
                _err("새로운 주제를 찾지 못했거나 소스가 부족합니다.")
                return

            # 2. Generation
            st.toast("✍️ AI 3-Pass 원고 작성 중...")
            gen_payload = generate_content(root_dir=ROOT_DIR, selected_payload=topic_payload, work_item_id=wid)
            wid = gen_payload.get("work_item_id")

            # 3. QA Review
            st.toast("🔍 품질(QA) 검토 중...")
            run_qa(root_dir=ROOT_DIR, work_item_id=wid)
            
            st.session_state["current_work_item_id"] = wid
            st.toast("✅ 콘텐츠 완성!")

        except Exception as exc:
            _err(f"생성 실패: {exc}")

def _do_publish() -> None:
    _clear_err()
    wid = st.session_state.get("current_work_item_id")
    if not wid:
        _err("발행할 콘텐츠가 없습니다.")
        return
    with st.spinner("🚀 블로그에 즉시 업로드 중..."):
        try:
            # Force auto-publish regardless of QA validation rules
            publish_content(
                root_dir=ROOT_DIR,
                work_item_id=wid,
                publish_mode="public",
                manual_soft_fail_approval=True,
            )
            st.toast("🎉 블로그 업로드 성공!")
        except Exception as exc:
            _err(f"업로드 실패: {exc}")

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _snapshot() -> dict | None:
    if not st.session_state["current_work_item_id"]: return None
    return get_work_item_snapshot(root_dir=ROOT_DIR, work_item_id=st.session_state["current_work_item_id"])

# ──────────────────────────────────────────────────────────────
# Sidebar Scheduler UI
# ──────────────────────────────────────────────────────────────
_init()

st.sidebar.markdown("## ⏰ 매일 자동 업로드 설정")
schedule_time = st.sidebar.time_input("업로드 예약 시간 (매일)", value=st.session_state["schedule_time"])
auto_on = st.sidebar.toggle("스케줄러 켜기", value=st.session_state["scheduler_active"])

if st.session_state["schedule_time"] != schedule_time or st.session_state["scheduler_active"] != auto_on:
    st.session_state["schedule_time"] = schedule_time
    st.session_state["scheduler_active"] = auto_on
    if auto_on:
        start_scheduler(schedule_time.strftime("%H:%M"), ROOT_DIR)
        st.toast(f"✅ 스케줄러가 매일 {schedule_time.strftime('%H:%M')}에 작동합니다.")
    else:
        stop_scheduler()
        st.toast("🚫 스케줄러가 정지되었습니다.")

if auto_on:
    st.sidebar.success(f"현재 스케줄러 가동 중: 매일 {schedule_time.strftime('%H:%M')}")
else:
    st.sidebar.info("스위치를 켜면 백그라운드에서 매일 자동으로 포스팅이 생성 및 업로드됩니다.")

# ──────────────────────────────────────────────────────────────
# Main UI
# ──────────────────────────────────────────────────────────────
st.markdown(CLEAN_CSS, unsafe_allow_html=True)

st.title("🤖 AI Blog Architect")
st.caption("고도화된 AI 페르소나와 자동화 파이프라인으로 최적의 수익형 콘텐츠를 설계합니다.")

if err := st.session_state.get("ui_error"):
    st.error(f"⚠️ {err}")

snap = _snapshot()
wi = snap.get("work_item", {}) if snap else {}
pkg = snap.get("package", {}) if snap else {}

# 📊 Dashboard Metrics Area
if snap:
    st.markdown("### 📊 Workflow Insight")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        score = wi.get("topic_score", 0)
        st.metric("수익성 점수", f"{score:.1f} / 10")
    with m2:
        status = wi.get("publish_status", "N/A").upper()
        # Custom color styling for publish status
        st.metric("발행 상태", status)
    with m3:
        source_count = wi.get("source_count", 0)
        st.metric("수집 소스", f"{source_count}개")
    with m4:
        qa_score = wi.get("qa_result", "미측정")
        st.metric("품질 지수", str(qa_score).upper())
    
    st.write("")

# Action Bar (Simplifed)
c1, c2 = st.columns(2)
with c1:
    if st.button("✨ 콘텐츠 전체 자동 생성 (주제찾기 + 자동작성)", use_container_width=True, type="primary"):
        _do_auto_generate()
        st.rerun()

has_html = bool(pkg.get("article_html") or wi.get("article_html"))
with c2:
    if st.button("🚀 블로그 즉시 업로드", use_container_width=True, type="primary" if has_html else "secondary", disabled=not has_html):
        _do_publish()
        st.rerun()

st.divider()

# Blog Preview
article_html = str(pkg.get("article_html") or wi.get("article_html") or "")
final_title = str(pkg.get("final_title") or wi.get("final_title") or wi.get("topic_title") or "")
pub_url = str(wi.get("blog_url") or "")

if pub_url:
    st.success(f"🎉 **블로그 발행 완료!** 링크를 확인하세요: [{pub_url}]({pub_url})")

if has_html:
    st.markdown("## 📄 바로 업로드 가능한 블로그 포스팅")
    st.markdown(f"### 제목: {final_title}")
    
    qa_score = wi.get("qa_result")
    if qa_score:
        st.caption(f"시스템 백그라운드 평가 결과: {qa_score}")
        
    components.html(article_html, height=900, scrolling=True)
else:
    st.info("👆 [콘텐츠 전체 자동 생성] 버튼을 누르시면, 새로운 블로그 포스팅이 아름다운 레이아웃과 함께 여기에 표시됩니다.")

