#!/usr/bin/env python3
"""
Book Cover Downloader

This script recursively searches directories for EPUB files, extracts ISBNs,
and downloads corresponding book covers from various online sources.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from fetch_ebook_covers.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
