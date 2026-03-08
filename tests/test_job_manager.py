"""Tests for core/server/job_manager.py."""
import time

from core.server.job_manager import JobManager, RUNNING, DONE, ERROR


def test_start_returns_job_id():
    jm = JobManager()
    job_id = jm.start(lambda: "output", label="test")
    assert isinstance(job_id, str)
    assert len(job_id) > 0


def test_job_initially_running():
    jm = JobManager()
    job_id = jm.start(lambda: (time.sleep(0.5), "done")[1], label="slow")
    job = jm.get(job_id)
    assert job is not None
    assert job["status"] == RUNNING


def test_job_completes_with_output():
    jm = JobManager()
    job_id = jm.start(lambda: "hello world", label="quick")
    time.sleep(0.2)
    job = jm.get(job_id)
    assert job["status"] == DONE
    assert job["output"] == "hello world"


def test_job_records_error_on_exception():
    jm = JobManager()

    def fail():
        raise RuntimeError("something broke")

    job_id = jm.start(fail, label="failing")
    time.sleep(0.2)
    job = jm.get(job_id)
    assert job["status"] == ERROR
    assert "something broke" in job["error"]


def test_get_returns_none_for_unknown_job():
    jm = JobManager()
    assert jm.get("doesnotexist") is None


def test_list_all_returns_all_jobs():
    jm = JobManager()
    id1 = jm.start(lambda: "a", label="job1")
    id2 = jm.start(lambda: "b", label="job2")
    time.sleep(0.2)
    jobs = jm.list_all()
    ids = [j["id"] for j in jobs]
    assert id1 in ids
    assert id2 in ids


def test_job_labels_are_stored():
    jm = JobManager()
    job_id = jm.start(lambda: "x", label="my-label")
    job = jm.get(job_id)
    assert job["label"] == "my-label"


def test_multiple_jobs_run_independently():
    jm = JobManager()
    results = []
    jm.start(lambda: (time.sleep(0.05), results.append(1))[1] or "a", label="j1")
    jm.start(lambda: (time.sleep(0.05), results.append(2))[1] or "b", label="j2")
    time.sleep(0.3)
    assert 1 in results
    assert 2 in results
