import time
from threading import Event
from orbit_demo.workers import LatestWorker


def test_worker_mailbox_coalesces_and_stops():
    started,release = Event(),Event()
    worker = LatestWorker('test-bounded-mailbox')
    calls = []
    def slow():
        started.set()
        release.wait(3)
        calls.append('first')
        return 1
    def last(value):
        calls.append(value)
        return value
    try:
        worker.submit('first',slow)
        assert started.wait(3)
        for i in range(100): worker.submit(i,last,i)
        assert worker.pending[0]==99
        release.set()
        deadline = time.perf_counter()+3
        while len(calls)<2 and time.perf_counter()<deadline: time.sleep(.005)
        assert calls==['first',99]
        deadline = time.perf_counter()+3
        result = None
        while time.perf_counter()<deadline:
            result = worker.take()
            if result and result[0]==99: break
            time.sleep(.005)
        assert result==(99,99,None)
        assert worker.pending is None
    finally:
        release.set()
        worker.stop()
    assert not worker.isRunning()
