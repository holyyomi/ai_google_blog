import threading
import time
from datetime import datetime
from typing import Any
from blogspot_automation.ui.service import find_today_topic, generate_content, run_qa, publish_content

_SCHEDULER_THREAD = None
_SCHEDULER_ACTIVE = False
_SCHEDULE_TIME = "10:00"
_ROOT_DIR = None

def _daily_job():
    print(f"\n============================================\n[{datetime.now()}] 🚀 자동화 스케줄러 파이프라인 시작...")
    try:
        print("1. 주제를 찾고 있습니다...")
        topic = find_today_topic(root_dir=_ROOT_DIR)
        wid = topic.get("saved_work_item_id")
        
        if topic.get("publish_status") in ("planned_fail", "source_insufficient"):
            print(f"-> 주제 건너뜀 사유: {topic.get('stop_reason', '불충분한 소스')}")
            return

        print("2. AI 콘텐츠를 생성하는 중입니다...")
        gen = generate_content(root_dir=_ROOT_DIR, selected_payload=topic, work_item_id=wid)
        
        print("3. 품질 검증(QA) 평가 중...")
        run_qa(root_dir=_ROOT_DIR, work_item_id=wid)
        
        print("4. 블로그 서버로 업로드 중...")
        publish_content(root_dir=_ROOT_DIR, work_item_id=wid, publish_mode="public", manual_soft_fail_approval=True)
        print(f"[{datetime.now()}] ✅ 자동화 업로드 완료!\n============================================\n")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ 스케줄러 에러 발생: {e}\n============================================\n")

def _run_schedule():
    print(f"스케줄러 모니터링 시작 (목표 시간: 매일 {_SCHEDULE_TIME})")
    while _SCHEDULER_ACTIVE:
        now = datetime.now().strftime("%H:%M")
        if now == _SCHEDULE_TIME:
            _daily_job()
            print("작업 완료. 다음 날까지 대기합니다...")
            time.sleep(61) # skip the rest of the current minute
        time.sleep(10)

def start_scheduler(time_str: str, root_dir: Any):
    global _SCHEDULER_ACTIVE, _SCHEDULE_TIME, _SCHEDULER_THREAD, _ROOT_DIR
    _SCHEDULE_TIME = time_str
    _ROOT_DIR = root_dir
    
    # 만약 이미 돌고있다면 시간만 바꾼다
    if _SCHEDULER_ACTIVE:
        print(f"스케줄러 시간이 수정되었습니다: {_SCHEDULE_TIME}")
        return

    _SCHEDULER_ACTIVE = True
    _SCHEDULER_THREAD = threading.Thread(target=_run_schedule, daemon=True)
    _SCHEDULER_THREAD.start()
    print("스케줄러 데몬이 실행되었습니다.")

def stop_scheduler():
    global _SCHEDULER_ACTIVE
    if _SCHEDULER_ACTIVE:
        _SCHEDULER_ACTIVE = False
        print("스케줄러가 정지되었습니다.")
