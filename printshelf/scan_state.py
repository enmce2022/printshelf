from __future__ import annotations

from typing import Any

from .database import Database


class ScanRunStore:
    """Operations on the `scan_state` table.

    The scan state machine has subtle invariants encoded in WHERE clauses
    (claim-once semantics, restart-while-running, cancel-without-restart).
    This class concentrates those operations behind named methods so the
    worker loop in `service.py` doesn't have to encode them inline.

    Schema for `scan_state` is owned by `Database` (one row, id=1). This
    class only reads/writes that row.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _coerce(row: Any) -> dict[str, Any]:
        payload = dict(row)
        payload["cancel_requested"] = bool(payload.get("cancel_requested"))
        payload["restart_requested"] = bool(payload.get("restart_requested"))
        payload["pause_requested"] = bool(payload.get("pause_requested"))
        return payload

    def get_state(self) -> dict[str, Any]:
        with self._db._connect() as conn:
            row = conn.execute("SELECT * FROM scan_state WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("scan_state row is missing")
            return self._coerce(row)

    def start_run(self, run_id: str, root_path: str) -> bool:
        """Begin a fresh run. Only succeeds if no run is currently active."""
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'counting',
                    run_id = ?,
                    owner_token = '',
                    root_path = ?,
                    total_files = 0,
                    scanned = 0,
                    changed = 0,
                    reused = 0,
                    deleted = 0,
                    progress_percent = 0,
                    message = 'Counting files...',
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    pause_requested = 0,
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('idle', 'completed', 'failed')
                """,
                (run_id, root_path),
            )
            return cursor.rowcount > 0

    def request_restart(self, root_path: str) -> bool:
        """Queue a restart at the new root path on the currently-active run."""
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'canceling',
                    root_path = ?,
                    cancel_requested = 1,
                    restart_requested = 1,
                    pause_requested = 0,
                    message = 'Restart requested. Waiting for current file to finish...',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('counting', 'running', 'canceling', 'paused')
                """,
                (root_path,),
            )
            return cursor.rowcount > 0

    def request_cancel(self) -> bool:
        """Cancel the active run without queueing a restart."""
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'canceling',
                    cancel_requested = 1,
                    restart_requested = 0,
                    pause_requested = 0,
                    message = 'Cancel requested. Waiting for current file to finish...',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('counting', 'running', 'canceling', 'paused')
                """,
            )
            return cursor.rowcount > 0

    def request_pause(self) -> bool:
        """Pause the active run between file boundaries.

        Refuses to pause once a cancel or restart has been queued; cancel
        preempts pause and we don't want to silently downgrade.
        """
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'paused',
                    pause_requested = 1,
                    message = 'Pause requested. Waiting for current file to finish...',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('counting', 'running')
                  AND cancel_requested = 0
                  AND restart_requested = 0
                """,
            )
            return cursor.rowcount > 0

    def request_resume(self) -> bool:
        """Resume a paused run. No-ops if a cancel/restart was queued meanwhile."""
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'running',
                    pause_requested = 0,
                    message = 'Resuming...',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status = 'paused'
                  AND cancel_requested = 0
                  AND restart_requested = 0
                """,
            )
            return cursor.rowcount > 0

    def claim_owner(self, run_id: str, owner_token: str) -> bool:
        """Atomically take ownership of a run; only the owner may update progress."""
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET owner_token = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND run_id = ?
                  AND (owner_token = '' OR owner_token = ?)
                """,
                (owner_token, run_id, owner_token),
            )
            return cursor.rowcount > 0

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._db._connect() as conn:
            row = conn.execute(
                "SELECT run_id, cancel_requested FROM scan_state WHERE id = 1"
            ).fetchone()
            if row is None:
                return False
            return str(row["run_id"]) == run_id and bool(row["cancel_requested"])

    def is_pause_requested(self, run_id: str) -> bool:
        with self._db._connect() as conn:
            row = conn.execute(
                "SELECT run_id, pause_requested FROM scan_state WHERE id = 1"
            ).fetchone()
            if row is None:
                return False
            return str(row["run_id"]) == run_id and bool(row["pause_requested"])

    def update_progress(
        self,
        run_id: str,
        *,
        status: str,
        total_files: int,
        scanned: int,
        changed: int,
        reused: int,
        deleted: int,
        progress_percent: float,
        message: str,
    ) -> bool:
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = CASE
                        WHEN pause_requested = 1 THEN 'paused'
                        ELSE ?
                    END,
                    total_files = ?,
                    scanned = ?,
                    changed = ?,
                    reused = ?,
                    deleted = ?,
                    progress_percent = ?,
                    message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (
                    status,
                    int(total_files),
                    int(scanned),
                    int(changed),
                    int(reused),
                    int(deleted),
                    float(progress_percent),
                    message,
                    run_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_canceling(self, run_id: str, message: str) -> bool:
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET status = 'canceling', message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (message, run_id),
            )
            return cursor.rowcount > 0

    def complete_run(self, run_id: str, result: dict[str, Any], message: str) -> bool:
        total_files = int(result.get("total_files", result.get("scanned", 0)))
        scanned = int(result.get("scanned", 0))
        changed = int(result.get("changed", 0))
        reused = int(result.get("reused", 0))
        deleted = int(result.get("deleted", 0))
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'completed',
                    total_files = ?,
                    scanned = ?,
                    changed = ?,
                    reused = ?,
                    deleted = ?,
                    progress_percent = ?,
                    message = ?,
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    pause_requested = 0,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ? AND cancel_requested = 0
                """,
                (
                    total_files,
                    scanned,
                    changed,
                    reused,
                    deleted,
                    100.0 if total_files >= 0 else 0.0,
                    message,
                    run_id,
                ),
            )
            return cursor.rowcount > 0

    def fail_run(self, run_id: str, error_message: str) -> bool:
        with self._db._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'failed',
                    error = ?,
                    message = 'Scan failed.',
                    cancel_requested = 0,
                    restart_requested = 0,
                    pause_requested = 0,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (error_message, run_id),
            )
            return cursor.rowcount > 0

    def claim_restart(
        self, previous_run_id: str, new_run_id: str, owner_token: str
    ) -> str | None:
        """Atomically pick up a queued restart and start a new run.

        Returns the new root path if a restart was claimed, else None.
        """
        with self._db._connect() as conn:
            row = conn.execute(
                """
                SELECT root_path
                FROM scan_state
                WHERE id = 1 AND run_id = ? AND restart_requested = 1
                """,
                (previous_run_id,),
            ).fetchone()
            if row is None:
                return None

            root_path = str(row["root_path"] or "")
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'counting',
                    run_id = ?,
                    owner_token = ?,
                    total_files = 0,
                    scanned = 0,
                    changed = 0,
                    reused = 0,
                    deleted = 0,
                    progress_percent = 0,
                    message = 'Counting files...',
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    pause_requested = 0,
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND run_id = ?
                  AND restart_requested = 1
                """,
                (new_run_id, owner_token, previous_run_id),
            )
            if cursor.rowcount <= 0:
                return None
            return root_path
