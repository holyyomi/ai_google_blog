"""runs/ 디렉터리 누적 산출물 정리 도구.

뉴스/AI 파이프라인이 매번 runs/news_YYYYMMDD_HHMMSS/ 디렉터리를 만들기 때문에
로컬에 100개+ 디렉터리가 쌓일 수 있다. 이 스크립트는 기본 7일 이전 디렉터리를 삭제한다.

사용:
  python tools/cleanup_runs.py              # dry-run (기본): 무엇이 지워질지만 출력
  python tools/cleanup_runs.py --apply      # 실제 삭제
  python tools/cleanup_runs.py --days 30    # 30일 이전만 대상
  python tools/cleanup_runs.py --runs-dir custom_runs --apply

runs/는 .gitignore되어 있으므로 이 정리는 로컬 디스크 정리 목적이다.
GitHub Actions schedule에는 영향이 없다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


def collect_old_dirs(runs_dir: Path, cutoff_seconds: float) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    now = time.time()
    targets: list[Path] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) >= cutoff_seconds:
            targets.append(entry)
    targets.sort(key=lambda p: p.stat().st_mtime)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="runs/ 오래된 디렉터리 정리")
    parser.add_argument("--runs-dir", default="runs", help="대상 디렉터리 (기본: runs)")
    parser.add_argument("--days", type=int, default=7, help="이 일 수보다 오래된 디렉터리를 대상으로 한다 (기본: 7)")
    parser.add_argument("--apply", action="store_true", help="실제 삭제 실행 (없으면 dry-run)")
    args = parser.parse_args()

    if args.days < 1:
        sys.stderr.write("ERROR: --days 는 1 이상이어야 합니다.\n")
        return 2

    runs_dir = Path(args.runs_dir).resolve()
    cutoff_seconds = args.days * 86400.0

    targets = collect_old_dirs(runs_dir, cutoff_seconds)
    if not targets:
        print(f"정리 대상 없음 ({runs_dir} 기준 {args.days}일 이전 디렉터리 0개)")
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {runs_dir} 기준 {args.days}일 이전 디렉터리 {len(targets)}개")
    deleted = 0
    failed = 0
    for target in targets:
        age_days = (time.time() - target.stat().st_mtime) / 86400.0
        if args.apply:
            try:
                shutil.rmtree(target)
                deleted += 1
                print(f"  removed  {target.name}  (age={age_days:.1f}d)")
            except Exception as exc:
                failed += 1
                print(f"  FAILED   {target.name}: {exc}")
        else:
            print(f"  would rm {target.name}  (age={age_days:.1f}d)")

    if args.apply:
        print(f"\n완료: 삭제 {deleted}개, 실패 {failed}개")
    else:
        print(f"\ndry-run 결과만 출력했습니다. 실제로 삭제하려면 --apply 를 추가하세요.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
