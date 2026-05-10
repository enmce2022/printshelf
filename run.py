import argparse

from printshelf.desktop import resolve_data_dir, run_desktop_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="printshelf",
        description="Browse a library of STL and G-code files.",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help=(
            "Where to keep PrintShelf's SQLite database, preview cache, and "
            "log file. Defaults to ./printshelf-data in the current working "
            "directory. Can also be set via PRINTSHELF_DATA_DIR."
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
            "PRINTSHELF_SCAN_WORKERS."
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
    main()
