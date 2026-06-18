"""
자동 반복 수집기 (선택).
일정 간격으로 eBay 를 다시 수집해서 대시보드를 최신으로 유지.
실행:  python run_loop.py 600    (600초 = 10분 간격, 생략 시 600초)
중지:  Ctrl + C
"""
import sys
import time
import datetime as dt

import collector

interval = int(sys.argv[1]) if len(sys.argv) > 1 else 600

print(f"{interval}초 간격으로 수집 시작 (Ctrl+C 로 중지)")
while True:
    try:
        n = collector.run()
        print(f"[{dt.datetime.now():%H:%M:%S}] {n}개 수집 완료")
    except Exception as e:
        print(f"[{dt.datetime.now():%H:%M:%S}] 오류: {e}")
    time.sleep(interval)
