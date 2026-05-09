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
    args = parser.parse_args()

    data_dir = resolve_data_dir(args.data_dir)
    run_desktop_app(data_dir=data_dir)


if __name__ == "__main__":
    main()
