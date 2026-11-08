import time

from xiaoxi_singer.jobs import JobRunner


def test_jobs_run_in_order_and_report():
    r = JobRunner()
    seen = []

    def make(name):
        def fn(job):
            seen.append(name)
            job.stage = "working"

        return fn

    a = r.submit("x", {}, make("a"))
    b = r.submit("x", {}, make("b"))

    deadline = time.time() + 5
    while time.time() < deadline and (r.get(b.id).status != "done"):
        time.sleep(0.05)

    assert seen == ["a", "b"]
    assert r.get(a.id).status == "done"
    assert r.get(b.id).progress == 1.0


def test_jobs_capture_errors():
    r = JobRunner()

    def boom(job):
        raise ValueError("nope")

    j = r.submit("x", {}, boom)
    deadline = time.time() + 5
    while time.time() < deadline and r.get(j.id).status != "error":
        time.sleep(0.05)
    got = r.get(j.id)
    assert got.status == "error"
    assert "ValueError" in got.error
