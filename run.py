import argparse
import multiprocessing
import os
import sys

from spoolhouse.desktop import resolve_data_dir, run_desktop_app

# PyInstaller windowed (console=False) builds run with sys.stdout/stderr set to
# None. uvicorn's logging formatter calls sys.stdout.isatty() during startup,
# which raises AttributeError on None and crashes before the server can bind —
# breaking every launch that has no attached console (i.e. a double-click).
# Route the missing streams to the null device so logging (and any stray print)
# is harmless. This runs at import time, so spawned worker children that
# re-execute this module are covered too. Running from a real console leaves the
# streams untouched.
for _stream_name in ("stdout", "stderr"):
    if getattr(sys, _stream_name) is None:
        setattr(sys, _stream_name, open(os.devnull, "w"))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spoolhouse",
        description="Browse a library of STL and G-code files.",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help=(
            "Where to keep SpoolHouse's SQLite database, preview cache, and "
            "log file. Defaults to ./spoolhouse-data in the current working "
            "directory. Can also be set via SPOOLHOUSE_DATA_DIR."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Number of Uvicorn worker processes to run (default: 1).",
    )
    parser.add_argument(
        "--scan-workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Parallelism for preview generation during library scans (default: "
            "1 = sequential). Higher values use a process pool to render STL "
            "and G-code thumbnails on multiple CPU cores. Can also be set via "
            "SPOOLHOUSE_SCAN_WORKERS."
        ),
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.scan_workers < 1:
        parser.error("--scan-workers must be >= 1")

    data_dir = resolve_data_dir(args.data_dir)
    run_desktop_app(
        data_dir=data_dir,
        workers=args.workers,
        scan_workers=args.scan_workers,
    )


if __name__ == "__main__":
    # Required for the frozen (PyInstaller) build: child processes spawned by
    # the scan ProcessPoolExecutor and uvicorn's Multiprocess supervisor re-run
    # this executable, and freeze_support() short-circuits them into worker mode
    # instead of re-opening the desktop window. Harmless when running from
    # source.
    multiprocessing.freeze_support()
    main()
