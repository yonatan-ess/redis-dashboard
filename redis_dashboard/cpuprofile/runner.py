import threading
import time

from django.db import close_old_connections, connection as db_connection
from django.utils import timezone

from .cpuproflib import take_sample
from .models import Capture, Sample

# capture ids with a live thread in this process; anything else "running" died with a restart
_live = set()
_lock = threading.Lock()


def is_live(capture_id):
    return capture_id in _live


def reap_orphans():
    Capture.objects.filter(status=Capture.RUNNING).exclude(id__in=list(_live)).update(
        status=Capture.INTERRUPTED, finished_at=timezone.now(),
        error='Server restarted while this capture was running.')


def start(capture, conn):
    with _lock:
        _live.add(capture.id)
    threading.Thread(target=_run, args=(capture.id, conn), daemon=True).start()


def _run(capture_id, conn):
    capture = Capture.objects.get(id=capture_id)
    try:
        for i in range(1, capture.samples_requested + 1):
            if Capture.objects.filter(id=capture_id, stop_requested=True).exists():
                capture.status = Capture.STOPPED
                break
            stats = take_sample(conn, capture.amount, capture.max_sample_seconds)
            Sample.objects.create(
                capture=capture, index=i, stats=stats,
                avg_usec_per_call=stats['avg_usec_per_call'], cpu_pct=stats['cpu_pct'],
                ops_per_sec=stats['ops_per_sec'], level=capture.level_for(stats['avg_usec_per_call']))
            if i < capture.samples_requested:
                time.sleep(capture.interval)
        else:
            capture.status = Capture.DONE
    except Exception as e:  # surface any failure in the UI instead of dying silently
        capture.status = Capture.FAILED
        capture.error = f'{type(e).__name__}: {e}'
    finally:
        capture.finished_at = timezone.now()
        capture.save(update_fields=['status', 'error', 'finished_at'])
        conn.close()
        with _lock:
            _live.discard(capture_id)
        close_old_connections()
        db_connection.close()
