#!/usr/bin/env python3
"""
Book Cover Downloader

This script recursively searches directories for EPUB files, extracts ISBNs,
and downloads corresponding book covers from various online sources.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2024 Christian Blank
"""

import hashlib
import os
import zipfile
from dataclasses import dataclass
from typing import Optional, List
from bs4 import BeautifulSoup
import requests
import sys
import json
import re
import logging

# Configuration
GOOGLE_BOOKS_API_KEY = ""
GENERIC_COVER_HASHES = [
    "f81b2d84d8a69ba9e8bf1f50c806faab",
    "0d23d0b62908b75e89014ac3f864484e"
]
COVER_FILENAMES = ["cover.jpg", "cover.jpeg"]

# ANSI color codes
COLORS = {
    'BLUE': '\033[94m',
    'CYAN': '\033[96m',
    'GREEN': '\033[92m',
    'YELLOW': '\033[93m',
    'RED': '\033[91m',
    'BOLD_GREEN': '\033[1;92m',
    'RESET': '\033[0m'
}

@dataclass
class BookMetadata:
    """Container for book metadata"""
    title: Optional[str] = None
    author: Optional[str] = None
    year: Optional[str] = None
    isbn: Optional[str] = None

class CoverDownloader:
    """Handles the downloading of book covers from various sources"""

    @staticmethod
    def download_from_sources(isbn: str, output_path: str) -> bool:
        """Try downloading cover from multiple sources"""
        sources = [
            ('buch.isbn.de', lambda: CoverDownloader._from_buch_isbn_de(isbn)),
            ('OpenLibrary', lambda: CoverDownloader._from_openlibrary(isbn)),
            ('Google Books', lambda: CoverDownloader._from_google_books(isbn))
        ]

        for source_name, download_func in sources:
            logging.info(f"\t- Trying {source_name}...")
            if content := download_func():
                CoverDownloader._save_cover(content, output_path)
                return True

        logging.error(f"{COLORS['RED']}\t- No cover found from any source{COLORS['RESET']}")
        return False

    @staticmethod
    def _from_buch_isbn_de(isbn: str) -> Optional[bytes]:
        """Download cover from buch.isbn.de"""
        url = f"https://buch.isbn.de/gross/{isbn}.jpg"
        return CoverDownloader._download_url(url)

    @staticmethod
    def _from_openlibrary(isbn: str) -> Optional[bytes]:
        """Download cover from OpenLibrary"""
        url = f"http://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
        return CoverDownloader._download_url(url)

    @staticmethod
    def _from_google_books(isbn: str) -> Optional[bytes]:
        """Download cover from Google Books"""
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        if GOOGLE_BOOKS_API_KEY:
            url += f"&key={GOOGLE_BOOKS_API_KEY}"

        response = requests.get(url)
        if response.status_code != 200:
            return None

        data = response.json()
        if "items" not in data:
            return None

        image_links = data["items"][0]["volumeInfo"].get("imageLinks", {})
        if "thumbnail" not in image_links:
            return None

        return CoverDownloader._download_url(image_links["thumbnail"])

    @staticmethod
    def _download_url(url: str, max_retries: int = 3) -> Optional[bytes]:
        """Download content from URL with retries and generic cover detection"""
        logging.info(f"{COLORS['CYAN']}\t- Downloading from: {url}{COLORS['RESET']}")

        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        logging.warning(f"\t- Attempt {attempt + 1} failed, retrying...")
                        continue
                    return None

                # Check for generic covers
                md5_hash = hashlib.md5()
                md5_hash.update(response.content)
                if md5_hash.hexdigest() in GENERIC_COVER_HASHES:
                    logging.warning(f"{COLORS['YELLOW']}\t- Generic cover detected, skipping{COLORS['RESET']}")
                    return None

                return response.content

            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"\t- Attempt {attempt + 1} failed: {e}, retrying...")
                    continue
                logging.error(f"{COLORS['RED']}\t- Download error: {e}{COLORS['RESET']}")

        return None

    @staticmethod
    def _save_cover(content: bytes, output_path: str) -> None:
        """Save downloaded cover to file"""
        with open(output_path, "wb") as f:
            f.write(content)
        logging.info(f"{COLORS['BOLD_GREEN']}\t- Cover saved to: {output_path}{COLORS['RESET']}")

class EPUBProcessor:
    """Handles EPUB file processing and ISBN extraction"""

    @staticmethod
    def process_directory(directory: str) -> None:
        """Recursively process directory for EPUB files"""
        epub_files = []
        for root, _, files in os.walk(directory):
            epub_files.extend(
                (root, file) for file in files if file.endswith(".epub")
            )

        if not epub_files:
            logging.info("No EPUB files found in directory")
            return

        logging.info(f"Found {len(epub_files)} EPUB files")
        for i, (root, file) in enumerate(epub_files, 1):
            logging.info(f"\nProcessing file {i}/{len(epub_files)}")
            EPUBProcessor.process_file(root, file)

    @staticmethod
    def process_file(root: str, filename: str) -> None:
        """Process single EPUB file"""
        epub_path = os.path.join(root, filename)

        # Check for existing covers
        for cover_name in COVER_FILENAMES:
            cover_path = os.path.join(root, cover_name)
            if os.path.isfile(cover_path):
                logging.info(f"{COLORS['YELLOW']}\t- Cover exists ({cover_name}), skipping{COLORS['RESET']}")
                return

        # Default to cover.jpg for new downloads
        cover_path = os.path.join(root, COVER_FILENAMES[0])

        logging.info(f"{COLORS['BLUE']}Processing: {filename}{COLORS['RESET']}")
        if isbn := EPUBProcessor.extract_isbn(epub_path):
            CoverDownloader.download_from_sources(isbn, cover_path)

    @staticmethod
    def extract_isbn(epub_path: str) -> Optional[str]:
        """Extract ISBN from EPUB metadata"""
        try:
            with zipfile.ZipFile(epub_path, "r") as epub:
                for file in epub.namelist():
                    if not file.endswith(".opf"):
                        continue

                    metadata = EPUBProcessor._parse_opf(epub.read(file).decode("utf-8"))

                    # Try direct ISBN
                    if metadata.isbn:
                        return metadata.isbn

                    # Fallback to title search
                    if metadata.title:
                        return EPUBProcessor._find_isbn_by_title(metadata)

        except Exception as e:
            logging.error(f"{COLORS['RED']}\t- Error processing EPUB: {e}{COLORS['RESET']}")

        return None

    @staticmethod
    def _parse_opf(opf_content: str) -> BookMetadata:
        """Parse OPF content for metadata"""
        soup = BeautifulSoup(opf_content, "xml")
        metadata = BookMetadata()

        # Extract ISBN
        if isbn_node := soup.find("dc:identifier", attrs={"opf:scheme": "ISBN"}):
            isbn = isbn_node.text
            if isbn.startswith("urn:isbn:"):
                isbn = isbn[9:]
            metadata.isbn = isbn
            logging.info(f"{COLORS['CYAN']}\t- Found ISBN: {isbn}{COLORS['RESET']}")

        # Extract title
        if title_node := soup.find("dc:title"):
            metadata.title = title_node.text

        return metadata

    @staticmethod
    def _find_isbn_by_title(metadata: BookMetadata) -> Optional[str]:
        """Find ISBN using Google Books API title search"""
        query_parts = [metadata.title]
        if metadata.author:
            query_parts.append(metadata.author)
        if metadata.year:
            query_parts.append(f"({metadata.year})")

        query = " ".join(query_parts)
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}"
        if GOOGLE_BOOKS_API_KEY:
            url += f"&key={GOOGLE_BOOKS_API_KEY}"

        try:
            response = requests.get(url)
            data = response.json()

            if "items" not in data:
                return None

            for item in data["items"]:
                if "volumeInfo" not in item or "industryIdentifiers" not in item["volumeInfo"]:
                    continue

                for identifier in item["volumeInfo"]["industryIdentifiers"]:
                    if identifier["type"] == "ISBN_13":
                        return identifier["identifier"]

        except Exception as e:
            logging.error(f"{COLORS['RED']}\t- Error in title search: {e}{COLORS['RESET']}")

        return None

def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print("Usage: python getBookCovers.py <path_to_folder>")
        sys.exit(1)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    EPUBProcessor.process_directory(directory)

if __name__ == "__main__":
    main()