"""
Book Cover Downloader

Handle command-line options and process EPUB libraries, saving one cover
per book folder.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from collections import Counter
from pathlib import Path
from zipfile import BadZipFile

from . import __version__
from .epub import EPUBError, embedded_covers, read_metadata
from .images import InvalidImage, existing_cover, save_cover, to_jpeg
from .providers import SOURCES, CoverClient

LOG = logging.getLogger(__name__)


def _timeout(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return number


def _retries(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("retries must be an integer from 0 to 10") from exc
    if not 0 <= number <= 10:
        raise argparse.ArgumentTypeError("retries must be between 0 and 10")
    return number


def _sources(value: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(n.strip().lower() for n in value.split(",")))
    if not names or any(n not in SOURCES for n in names):
        raise argparse.ArgumentTypeError(
            f"sources must be a comma-separated list of: {', '.join(SOURCES)}"
        )
    return names


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="fetch-ebook-covers",
        description="Save missing EPUB covers as cover.jpg beside each book.",
    )
    result.add_argument("path", type=Path, help="an EPUB file or a directory to search recursively")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="report intended actions without network requests or writes",
    )
    result.add_argument(
        "--force", action="store_true", help="replace cover.jpg even when a folder cover exists"
    )
    result.add_argument(
        "--prefer-embedded",
        action="store_true",
        help="try declared EPUB artwork before online providers",
    )
    result.add_argument(
        "--offline",
        action="store_true",
        help="extract embedded artwork only; never access the network",
    )
    result.add_argument(
        "--sources",
        type=_sources,
        default=SOURCES,
        metavar="LIST",
        help=f"ordered, comma-separated providers (default: {','.join(SOURCES)}); omitting google also disables title search",
    )
    result.add_argument(
        "--timeout",
        type=_timeout,
        default=10.0,
        metavar="SECONDS",
        help="connect/read timeout per request (default: 10)",
    )
    result.add_argument(
        "--retries",
        type=_retries,
        default=2,
        metavar="N",
        help="retries after transient failures, 0-10 (default: 2)",
    )
    result.add_argument("--verbose", action="store_true", help="show diagnostic messages")
    result.add_argument("--no-color", action="store_true", help="disable colored console messages")
    return result


class _Formatter(logging.Formatter):
    def __init__(self, color: bool) -> None:
        super().__init__("%(message)s")
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if self.color:
            code = (
                "31"
                if record.levelno >= logging.ERROR
                else "33"
                if record.levelno >= logging.WARNING
                else "36"
            )
            return f"\033[{code}m{text}\033[0m"
        return text


def _configure_logging(args: argparse.Namespace) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        _Formatter(not args.no_color and "NO_COLOR" not in os.environ and sys.stderr.isatty())
    )
    logger = logging.getLogger("fetch_ebook_covers")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logger.propagate = False


def _discover(path: Path, counts: Counter) -> list[Path]:
    if path.is_file():
        return [path]

    def onerror(error: OSError) -> None:
        counts["failed"] += 1
        LOG.error("Cannot scan %s: %s", error.filename, error.strerror)

    files = []
    for root, directories, names in os.walk(path, onerror=onerror, followlinks=False):
        directories.sort()
        files.extend(Path(root) / name for name in sorted(names) if name.lower().endswith(".epub"))
    return files


def _process(path: Path, args: argparse.Namespace, client: CoverClient | None) -> str:
    if not args.force and (cover := existing_cover(path.parent)):
        LOG.info("Skipping %s: %s exists", path.name, cover.name)
        return "skipped"
    LOG.info("Processing %s", path)
    book = read_metadata(path)
    if args.dry_run:
        action = (
            "extract embedded artwork"
            if args.offline
            else "try embedded artwork, then download"
            if args.prefer_embedded
            else "download artwork"
        )
        LOG.info(
            "Would %s for %s -> %s", action, book.title or path.stem, path.parent / "cover.jpg"
        )
        return "planned"
    content = None
    if args.offline or args.prefer_embedded:
        candidates = embedded_covers(path)
        try:
            for candidate in candidates:
                try:
                    content = to_jpeg(candidate)
                    LOG.info("Using embedded cover")
                    break
                except InvalidImage as exc:
                    LOG.warning("Rejected embedded cover: %s", exc)
        finally:
            candidates.close()
        if content is None:
            LOG.info("No supported embedded cover found")
    if content is None and client is not None:
        client.had_error = False
        content = client.find_cover(book, args.sources)
    if content is None:
        LOG.warning("No usable cover found for %s", path.name)
        return "failed" if client is not None and client.had_error else "missing"
    try:
        save_cover(content, path.parent / "cover.jpg", force=args.force)
    except FileExistsError:
        LOG.info("Skipping %s: a cover appeared while processing", path.name)
        return "skipped"
    LOG.info("Saved %s", path.parent / "cover.jpg")
    return "saved"


def main(argv: list[str] | None = None) -> int:
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    args.path = args.path.expanduser()
    if not args.path.is_dir() and not (args.path.is_file() and args.path.suffix.lower() == ".epub"):
        arg_parser.error(f"not an EPUB file or readable directory: {args.path}")
    _configure_logging(args)
    counts: Counter = Counter()
    client = None
    interrupted = False
    try:
        files = _discover(args.path, counts)
        LOG.info("Found %d EPUB file(s)", len(files))
        if not args.offline and not args.dry_run:
            client = CoverClient(
                timeout=args.timeout,
                retries=args.retries,
                api_key=os.environ.get("GOOGLE_BOOKS_API_KEY", ""),
            )
        completed_folders: set[Path] = set()
        for path in files:
            # One cover per folder: even --force must not repeatedly replace it.
            if path.parent in completed_folders:
                LOG.info("Skipping %s: folder already handled", path.name)
                counts["skipped"] += 1
                continue
            try:
                status = _process(path, args, client)
                counts[status] += 1
                if status in ("saved", "skipped", "planned"):
                    completed_folders.add(path.parent)
            except (EPUBError, OSError, BadZipFile, RuntimeError, NotImplementedError) as exc:
                counts["failed"] += 1
                LOG.error("Failed %s: %s", path.name, exc)
    except KeyboardInterrupt:
        interrupted = True
        LOG.warning("Interrupted")
    finally:
        if client is not None:
            client.close()
        LOG.info(
            "Summary: saved=%d skipped=%d missing=%d failed=%d planned=%d",
            *(counts[name] for name in ("saved", "skipped", "missing", "failed", "planned")),
        )
    if interrupted:
        return 130
    return 1 if counts["missing"] or counts["failed"] else 0
