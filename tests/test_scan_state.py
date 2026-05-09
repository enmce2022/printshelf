from __future__ import annotations

from printshelf.scan_state import ScanRunStore


def test_start_claim_progress_complete(scan_store: ScanRunStore) -> None:
    assert scan_store.start_run("run-A", "/lib") is True

    state = scan_store.get_state()
    assert state["status"] == "counting"
    assert state["run_id"] == "run-A"
    assert state["root_path"] == "/lib"
    assert state["cancel_requested"] is False
    assert state["restart_requested"] is False

    assert scan_store.claim_owner("run-A", "owner-1") is True

    scan_store.update_progress(
        "run-A",
        status="running",
        total_files=10,
        scanned=4,
        changed=4,
        reused=0,
        deleted=0,
        progress_percent=40.0,
        message="working",
    )
    state = scan_store.get_state()
    assert state["status"] == "running"
    assert state["scanned"] == 4
    assert state["progress_percent"] == 40.0

    scan_store.complete_run(
        "run-A",
        {"scanned": 10, "changed": 4, "reused": 6, "deleted": 0},
        "done",
    )
    state = scan_store.get_state()
    assert state["status"] == "completed"
    assert state["progress_percent"] == 100.0
    assert state["error"] == ""


def test_start_run_blocked_while_active(scan_store: ScanRunStore) -> None:
    assert scan_store.start_run("run-A", "/lib") is True
    # A second start while still in 'counting' must not succeed.
    assert scan_store.start_run("run-B", "/lib") is False
    state = scan_store.get_state()
    assert state["run_id"] == "run-A"


def test_request_restart_while_running(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib1")
    scan_store.claim_owner("run-A", "owner-1")

    assert scan_store.request_restart("/lib2") is True
    state = scan_store.get_state()
    assert state["status"] == "canceling"
    assert state["restart_requested"] is True
    assert state["cancel_requested"] is True
    assert state["root_path"] == "/lib2"

    # Worker observes cancel and tries to claim the queued restart.
    new_root = scan_store.claim_restart("run-A", "run-B", "owner-1")
    assert new_root == "/lib2"

    state = scan_store.get_state()
    assert state["run_id"] == "run-B"
    assert state["status"] == "counting"
    assert state["root_path"] == "/lib2"
    assert state["restart_requested"] is False
    assert state["cancel_requested"] is False


def test_cancel_without_restart(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")

    assert scan_store.request_cancel() is True
    state = scan_store.get_state()
    assert state["status"] == "canceling"
    assert state["cancel_requested"] is True
    # critical: cancel must NOT set restart_requested
    assert state["restart_requested"] is False
    assert scan_store.is_cancel_requested("run-A") is True

    # claim_restart finds nothing because restart was never queued.
    assert scan_store.claim_restart("run-A", "run-B", "owner-1") is None


def test_concurrent_claim_only_one_wins(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    assert scan_store.claim_owner("run-A", "owner-A") is True
    # Same owner can re-claim (idempotent).
    assert scan_store.claim_owner("run-A", "owner-A") is True
    # Different owner cannot steal.
    assert scan_store.claim_owner("run-A", "owner-B") is False


def test_is_cancel_requested_only_for_current_run(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.request_cancel()

    # Same run -> True
    assert scan_store.is_cancel_requested("run-A") is True
    # A stale run id (e.g. from a previous iteration) -> False
    assert scan_store.is_cancel_requested("run-X") is False


def test_complete_run_blocked_when_cancel_pending(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.request_cancel()

    # complete_run should refuse while cancel_requested is set.
    completed = scan_store.complete_run(
        "run-A",
        {"scanned": 1, "changed": 1, "reused": 0, "deleted": 0},
        "done",
    )
    assert completed is False
    assert scan_store.get_state()["status"] == "canceling"


def test_fail_run_clears_flags(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.request_restart("/lib2")  # sets cancel + restart flags

    assert scan_store.fail_run("run-A", "boom") is True
    state = scan_store.get_state()
    assert state["status"] == "failed"
    assert state["cancel_requested"] is False
    assert state["restart_requested"] is False
    assert state["error"] == "boom"


def test_start_after_completed_succeeds(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.complete_run(
        "run-A", {"scanned": 0, "changed": 0, "reused": 0, "deleted": 0}, "done"
    )
    # A fresh start should be allowed after completed.
    assert scan_store.start_run("run-B", "/lib") is True
    assert scan_store.get_state()["run_id"] == "run-B"


def test_request_pause_then_resume(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.update_progress(
        "run-A",
        status="running",
        total_files=10,
        scanned=2,
        changed=2,
        reused=0,
        deleted=0,
        progress_percent=20.0,
        message="working",
    )

    assert scan_store.request_pause() is True
    state = scan_store.get_state()
    assert state["status"] == "paused"
    assert state["pause_requested"] is True
    assert scan_store.is_pause_requested("run-A") is True
    assert scan_store.is_pause_requested("run-X") is False

    assert scan_store.request_resume() is True
    state = scan_store.get_state()
    assert state["status"] == "running"
    assert state["pause_requested"] is False


def test_request_pause_rejected_when_idle(scan_store: ScanRunStore) -> None:
    # Fresh store starts in 'idle'.
    assert scan_store.request_pause() is False
    assert scan_store.get_state()["status"] == "idle"


def test_request_pause_rejected_when_cancel_pending(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.request_cancel()

    # cancel preempts; pause must not silently downgrade.
    assert scan_store.request_pause() is False
    state = scan_store.get_state()
    assert state["status"] == "canceling"
    assert state["pause_requested"] is False


def test_request_pause_rejected_when_restart_pending(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib1")
    scan_store.request_restart("/lib2")

    assert scan_store.request_pause() is False
    assert scan_store.get_state()["pause_requested"] is False


def test_cancel_while_paused(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.request_pause()

    assert scan_store.request_cancel() is True
    state = scan_store.get_state()
    assert state["status"] == "canceling"
    assert state["cancel_requested"] is True
    assert state["pause_requested"] is False


def test_restart_while_paused(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib1")
    scan_store.request_pause()

    assert scan_store.request_restart("/lib2") is True
    state = scan_store.get_state()
    assert state["status"] == "canceling"
    assert state["restart_requested"] is True
    assert state["cancel_requested"] is True
    assert state["pause_requested"] is False
    assert state["root_path"] == "/lib2"


def test_resume_blocked_after_cancel_pending(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.request_pause()
    scan_store.request_cancel()  # this also clears pause_requested and flips to canceling

    # Resume must not bring the run back from canceling.
    assert scan_store.request_resume() is False
    assert scan_store.get_state()["status"] == "canceling"


def test_update_progress_preserves_paused_status(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.request_pause()

    # Worker fires a stale 'running' progress callback while pause_requested=1.
    scan_store.update_progress(
        "run-A",
        status="running",
        total_files=10,
        scanned=3,
        changed=3,
        reused=0,
        deleted=0,
        progress_percent=30.0,
        message="working",
    )

    state = scan_store.get_state()
    # Status stays 'paused' even though caller passed 'running'.
    assert state["status"] == "paused"
    assert state["pause_requested"] is True
    # Counters still update.
    assert state["scanned"] == 3


def test_complete_run_clears_pause_requested(scan_store: ScanRunStore) -> None:
    scan_store.start_run("run-A", "/lib")
    scan_store.claim_owner("run-A", "owner-1")
    scan_store.request_pause()
    # Resume so cancel_requested stays 0 (complete_run gates on that).
    scan_store.request_resume()
    # Re-pause to assert complete still wins over a lingering pause flag.
    scan_store.request_pause()

    completed = scan_store.complete_run(
        "run-A",
        {"scanned": 5, "changed": 5, "reused": 0, "deleted": 0},
        "done",
    )
    # complete_run only gates on cancel_requested, not pause_requested.
    assert completed is True
    state = scan_store.get_state()
    assert state["status"] == "completed"
    assert state["pause_requested"] is False
