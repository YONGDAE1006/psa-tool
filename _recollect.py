import datetime as dt, os
import db, collector
with db.get_conn() as conn:
    conn.execute("DELETE FROM id_cache")
    conn.execute("DELETE FROM sold_cache")
print("수집 시작:", dt.datetime.now().isoformat())
try:
    collector.run()
    print("수집 완료:", dt.datetime.now().isoformat())
except Exception as e:
    print("오류:", repr(e))
try:
    os.remove(__file__)
except Exception:
    pass
