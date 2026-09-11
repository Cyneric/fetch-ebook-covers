# Book Cover Downloader

Fetch missing covers for an EPUB library, or extract artwork already embedded in a book. Covers are saved as `cover.jpg` beside each EPUB. EPUB files are never modified.

Python 3.11+ is required. Windows, Linux, and macOS are supported. The intended layout is one book per folder.

## Install

From a checkout of this repository:

```sh
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On Linux or macOS:

```sh
source .venv/bin/activate
```

Then install the command:

```sh
python -m pip install .
fetch-ebook-covers --help
```

The original script command still works. For script-only use, install dependencies with `python -m pip install -r requirements.txt` and run it from this checkout:

```sh
python getBookCovers.py "/path/to/books"
```

## Usage

```sh
# Preview a recursive scan without downloads or file changes
fetch-ebook-covers "/path/to/books" --dry-run

# Download missing folder covers
fetch-ebook-covers "/path/to/books"

# Process one book
fetch-ebook-covers "/path/to/book.epub"

# Prefer this edition's embedded artwork, then try online sources
fetch-ebook-covers "/path/to/books" --prefer-embedded

# Extract embedded artwork without any network access
fetch-ebook-covers "/path/to/books" --offline

# Replace cover.jpg only after obtaining valid artwork
fetch-ebook-covers "/path/to/books" --force

# Select providers and their order
fetch-ebook-covers "/path/to/books" --sources openlibrary,google
```

`python -m fetch_ebook_covers` is also available after installation. All three entry points accept the same options.

| Option | Behavior |
| --- | --- |
| `--dry-run` | Read local metadata and report intended actions; no network requests or writes. Does not verify that a cover is available. |
| `--force` | Write or replace `cover.jpg` even if a folder cover exists. Other cover files are retained. |
| `--prefer-embedded` | Try declared embedded artwork before downloading. |
| `--offline` | Extract embedded artwork only. Overrides online source selection. |
| `--sources LIST` | Comma-separated providers in order: `buch.isbn.de,openlibrary,google` by default. Omitting `google` also disables title search. |
| `--timeout SECONDS` | Positive connect/read timeout per request, default `10`. This is not a total run deadline. |
| `--retries N` | Retries after transient failures, from `0` to `10`, default `2`. |
| `--verbose` | Show additional diagnostics. |
| `--no-color` | Disable ANSI colors. Redirected output and `NO_COLOR` also disable colors. |
| `--version` | Show the installed version. |

The directory scan includes uppercase `.EPUB` extensions and does not recurse into directory symlinks. Existing `cover.jpg`, `cover.jpeg`, `cover.png`, and `cover.webp` entries are recognized without regard to case and skipped by default.

If several EPUBs share a folder, the first successfully handled book in sorted traversal order supplies the folder cover. Later books in that folder are skipped, including with `--force`. If a book fails, the next book can still supply the cover. Earlier missing/failed results remain in the summary.

## Metadata and cover selection

The reader follows `META-INF/container.xml` to the package document, with an OPF scan as a fallback for older malformed files. XML namespace prefixes do not matter. It reads title, authors, publication year, and all valid ISBN-10/13 identifiers, normalizing prefixes and separators and checking ISBN checksums.

For each metadata ISBN, the downloader tries the selected providers in order. If none supplies artwork and Google is enabled, it searches by title and author. Candidates must agree on the complete normalized title and, when present, at least one complete normalized author name. Matching ignores case, punctuation, whitespace, and accents. Matching publication years rank first; Google's result order breaks ties. This deliberately conservative lookup can leave books with incomplete or differently spelled metadata unresolved.

Embedded extraction supports EPUB 3 `cover-image` declarations, EPUB 2 cover metadata, and cover guide references. XHTML/SVG wrappers can point to a raster image inside the archive. Pure vector artwork, encrypted artwork, external URLs, and unsupported image formats are not rendered or fetched. With `--prefer-embedded`, unsupported artwork falls back to the online providers; with `--offline`, it is reported as missing. See the [EPUB specification](https://www.w3.org/TR/epub-33/).

Downloaded and embedded images are validated with Pillow and saved as real JPEGs, with transparent areas composited on white. Known placeholder hashes, tiny placeholders, corrupt files, images over 20 MiB, and images over 40 million pixels are rejected. XML documents and API metadata responses are limited to 2 MiB. Generic artwork that is not a known placeholder may still pass validation.

## Providers and API configuration

The default source order remains **buch.isbn.de → Open Library → Google Books**. All requests use HTTPS and a shared session. Requests are sequential, paced per host, and retried only for transient network failures or HTTP 408, 429, 500, 502, 503, and 504 responses.

Open Library ISBN requests are spaced at least 3.1 seconds apart, including retries. Its API documents a limit of 100 such requests per IP per five minutes and is not intended for bulk downloading. Requests from other processes on the same IP also count. Missing covers use `default=false`, which requests a 404 instead of a blank image. For large libraries, use embedded extraction or exclude Open Library with `--sources buch.isbn.de,google`. See the [Open Library Covers API](https://openlibrary.org/dev/docs/api/covers) for its bulk-access guidance.

Google documents an API key requirement for public Books API requests. The tool still attempts unauthenticated access for compatibility, but access and quotas are not guaranteed. Set your own key without editing the script:

```powershell
# Windows PowerShell, for this shell session
$env:GOOGLE_BOOKS_API_KEY = "your-api-key"
fetch-ebook-covers "D:\Books"
```

```sh
# Linux/macOS
export GOOGLE_BOOKS_API_KEY="your-api-key"
fetch-ebook-covers "/path/to/books"
```

See [Google Books API configuration](https://developers.google.com/books/docs/v1/using). Keys and complete request URLs are excluded from application logs. API keys are sent only to the Google Books API; authenticated redirects are rejected.

HTTP 401/403 disables that host for the remainder of the run and reports the access problem. Retry-After headers are honored up to 60 seconds; longer requested delays disable the host for the run instead of retrying early. Another provider can still succeed. Provider availability, quotas, and edition coverage can change.

## File safety and results

A cover is fully written and flushed to a temporary file beside its destination before publication. Without `--force`, atomic hard-link publication prevents overwriting a `cover.jpg` created concurrently. This requires a filesystem that supports hard links; unsupported filesystems fail safely. With `--force`, the finished temporary file replaces `cover.jpg` atomically. Existing artwork is retained if downloading, validation, or writing fails.

Temporary files are cleaned up after handled failures and Ctrl+C. Abrupt process termination or power loss can leave a `.cover-*.tmp` file; it is never treated as a cover. The tool does not lock an entire library, so avoid running multiple `--force` processes against the same folders.

The summary reports saved, skipped, missing, failed, and planned counts. Missing means no usable artwork was found; failed means a processing, I/O, or unresolved provider error occurred. Directory scan errors also count as failed. One failed book does not stop the remaining scan.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed successfully, including empty scans and successful previews. |
| `1` | At least one missing cover or processing failure. |
| `2` | Invalid arguments or input path. |
| `130` | Interrupted with Ctrl+C. |

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
```

Tests generate their own EPUBs and images and block live network access. They cover parsing, matching, embedded artwork, HTTP failures and pacing, image validation, safe writes, CLI behavior, and entry-point compatibility.

GitHub Actions runs lint, formatting, tests, and builds on Windows and Linux with Python 3.11 through 3.14. A macOS job installs the wheel in a clean environment and checks the installed command outside the checkout.

## Author and license

Christian Blank <christianblank91@gmail.com>

Copyright (c) 2026 Christian Blank. Licensed under the [MIT License](LICENSE).
