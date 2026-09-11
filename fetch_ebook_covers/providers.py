"""
Book Cover Downloader

Download book covers from online providers using a shared HTTP session
with timeouts, retries, and request pacing.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from . import __version__
from .epub import BookMetadata, normalize_isbn
from .images import MAX_IMAGE_BYTES, InvalidImage, to_jpeg

LOG = logging.getLogger(__name__)
SOURCES = ("buch.isbn.de", "openlibrary", "google")
GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RETRY_WAIT = 60.0


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(c if c.isalnum() else " " for c in value if not unicodedata.combining(c)).split()
    )


def _identifiers(info: dict) -> list[str]:
    identifiers = info.get("industryIdentifiers", [])
    if not isinstance(identifiers, list):
        return []
    result = []
    for item in identifiers:
        if isinstance(item, dict) and isinstance(item.get("identifier"), str):
            if isbn := normalize_isbn(item["identifier"]):
                result.append(isbn)
    return list(dict.fromkeys(result))


def _isbn13(isbn: str) -> str:
    if len(isbn) == 13:
        return isbn
    prefix = "978" + isbn[:9]
    check = (-sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(prefix))) % 10
    return prefix + str(check)


def _retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0.0, float(int(value)))
        except (ValueError, OverflowError):
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                return max(0.0, (date - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return min(2**attempt, MAX_RETRY_WAIT)


class CoverClient:
    def __init__(self, *, timeout: float = 10, retries: int = 2, api_key: str = "") -> None:
        self.timeout = timeout
        self.retries = retries
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            f"fetch-ebook-covers/{__version__} (+https://github.com/Cyneric/fetch-ebook-covers)"
        )
        self.had_error = False
        self._next_request: dict[str, float] = {}
        self._disabled_hosts: set[str] = set()
        self._google_cache: dict[str, list[dict]] = {}

    def close(self) -> None:
        self.session.close()

    def _pace(self, host: str) -> None:
        delay = self._next_request.get(host, 0) - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        interval = 3.1 if host == "covers.openlibrary.org" else 1.0
        self._next_request[host] = time.monotonic() + interval

    def _get(
        self, url: str, *, params: dict | None = None, limit: int = MAX_IMAGE_BYTES
    ) -> bytes | None:
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("https", "http")
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Unsupported URL")
            # Google sometimes returns http imageLinks. Always request them over TLS.
            url = urlunsplit(parsed._replace(scheme="https", fragment=""))
            host = parsed.hostname
        except ValueError:
            self.had_error = True
            LOG.warning("Provider returned an invalid image URL")
            return None
        if host in self._disabled_hosts:
            self.had_error = True
            return None
        for attempt in range(self.retries + 1):
            self._pace(host)
            delay = min(2**attempt, MAX_RETRY_WAIT)
            try:
                LOG.debug("Requesting %s (attempt %d/%d)", host, attempt + 1, self.retries + 1)
                # Follow redirects ourselves so an HTTPS request cannot downgrade to HTTP.
                request_url, request_params = url, params
                for redirect in range(6):
                    response_host = urlsplit(request_url).hostname or host
                    with self.session.get(
                        request_url,
                        params=request_params,
                        timeout=self.timeout,
                        stream=True,
                        allow_redirects=False,
                    ) as response:
                        status = response.status_code
                        if status in (301, 302, 303, 307, 308):
                            try:
                                location = response.headers.get("Location", "")
                                if not location:
                                    raise ValueError("Missing redirect location")
                                target = urlsplit(urljoin(request_url, location))
                            except ValueError:
                                self.had_error = True
                                LOG.warning("%s returned a malformed redirect", host)
                                return None
                            if (
                                redirect == 5
                                or target.scheme != "https"
                                or not target.hostname
                                or target.username
                                or target.password
                            ):
                                self.had_error = True
                                LOG.warning("%s returned an unsupported redirect", host)
                                return None
                            # API credentials must never be forwarded to another host.
                            if params and "key" in params:
                                self.had_error = True
                                LOG.warning("%s redirected an authenticated API request", host)
                                return None
                            if target.hostname in self._disabled_hosts:
                                self.had_error = True
                                return None
                            self._pace(target.hostname)
                            request_url, request_params = target.geturl(), None
                            continue
                        if status in (404, 410):
                            return None
                        if status in (401, 403):
                            self.had_error = True
                            self._disabled_hosts.add(response_host)
                            hint = (
                                " Check GOOGLE_BOOKS_API_KEY and Books API access/quota."
                                if response_host == "www.googleapis.com"
                                else " Access denied or provider rate limit reached."
                            )
                            LOG.warning(
                                "%s returned HTTP %d.%s Skipping this host for the rest of the run.",
                                response_host,
                                status,
                                hint,
                            )
                            return None
                        if status in RETRY_STATUSES:
                            LOG.warning(
                                "%s returned HTTP %d%s",
                                response_host,
                                status,
                                " (rate limit reached)" if status == 429 else "",
                            )
                            delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                            if delay > MAX_RETRY_WAIT:
                                # Do not shorten a server's Retry-After and retry too early.
                                self._disabled_hosts.add(response_host)
                                self.had_error = True
                                LOG.warning(
                                    "%s requested a long retry delay; skipping it for this run",
                                    response_host,
                                )
                                return None
                            self._next_request[response_host] = max(
                                self._next_request.get(response_host, 0), time.monotonic() + delay
                            )
                            break
                        if status != 200:
                            self.had_error = True
                            LOG.warning("%s returned HTTP %d", host, status)
                            return None
                        length = response.headers.get("Content-Length", "")
                        if length.isdigit() and int(length) > limit:
                            self.had_error = True
                            LOG.warning("%s response exceeds the download size limit", host)
                            return None
                        data = bytearray()
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            data.extend(chunk)
                            if len(data) > limit:
                                self.had_error = True
                                LOG.warning("%s response exceeds the download size limit", host)
                                return None
                        return bytes(data)
            except requests.RequestException as exc:
                # Request exceptions can embed full URLs, including API keys.
                LOG.warning("%s request failed (%s)", host, type(exc).__name__)
            if attempt < self.retries:
                LOG.info("Retrying %s after %.1f seconds", host, delay)
                time.sleep(delay)
        self.had_error = True
        LOG.warning("%s exhausted its request attempts", host)
        return None

    def _volumes(self, query: str) -> list[dict]:
        if query in self._google_cache:
            return self._google_cache[query]
        params = {"q": query, "maxResults": 10, "printType": "books"}
        if self.api_key:
            params["key"] = self.api_key
        content = self._get(GOOGLE_API, params=params, limit=MAX_JSON_BYTES)
        if content is None:
            return []
        try:
            data = json.loads(content)
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("items", []), list)
                or "error" in data
            ):
                raise ValueError("Unexpected Google Books response")
            result = [
                item["volumeInfo"]
                for item in data.get("items", [])
                if isinstance(item, dict) and isinstance(item.get("volumeInfo"), dict)
            ]
        except (ValueError, UnicodeDecodeError):
            self.had_error = True
            LOG.warning("Google Books returned malformed metadata")
            return []
        self._google_cache[query] = result
        return result

    def _search(self, book: BookMetadata) -> list[str]:
        if not book.title:
            return []
        query = f'intitle:"{book.title.replace(chr(34), " ")}"'
        if book.authors:
            query += f' inauthor:"{book.authors[0].replace(chr(34), " ")}"'
        matches = []
        for info in self._volumes(query):
            title, authors = info.get("title"), info.get("authors", [])
            if not isinstance(title, str) or _normalized(title) != _normalized(book.title):
                continue
            if book.authors:
                if not isinstance(authors, list) or not any(
                    _normalized(a) == _normalized(b)
                    for a in authors
                    if isinstance(a, str)
                    for b in book.authors
                ):
                    continue
            year = info.get("publishedDate", "")
            matches.append(
                (bool(book.year and isinstance(year, str) and year[:4] == book.year), info)
            )
        matches.sort(key=lambda match: match[0], reverse=True)
        return list(dict.fromkeys(isbn for _, info in matches for isbn in _identifiers(info)))

    def _urls(self, source: str, isbn: str) -> Iterator[str]:
        if source == "buch.isbn.de":
            yield f"https://buch.isbn.de/gross/{isbn}.jpg"
        elif source == "openlibrary":
            yield f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
        elif source == "google":
            for info in self._volumes(f"isbn:{isbn}"):
                if not any(_isbn13(candidate) == _isbn13(isbn) for candidate in _identifiers(info)):
                    continue
                images = info.get("imageLinks", {})
                if isinstance(images, dict):
                    for size in (
                        "extraLarge",
                        "large",
                        "medium",
                        "small",
                        "thumbnail",
                        "smallThumbnail",
                    ):
                        if isinstance(images.get(size), str):
                            yield images[size]

    def find_cover(self, book: BookMetadata, sources: tuple[str, ...]) -> bytes | None:
        tried: set[str] = set()

        def try_isbns(isbns: tuple[str, ...] | list[str]) -> bytes | None:
            for isbn in isbns:
                if isbn in tried:
                    continue
                tried.add(isbn)
                LOG.info("Looking up ISBN %s", isbn)
                for source in sources:
                    LOG.info("Trying %s", source)
                    for url in self._urls(source, isbn):
                        content = self._get(url)
                        if content is None:
                            continue
                        try:
                            return to_jpeg(content)
                        except InvalidImage as exc:
                            LOG.warning("Rejected cover from %s: %s", source, exc)
            return None

        cover = try_isbns(book.isbns)
        if cover is None and "google" in sources and book.title:
            LOG.info("Searching Google Books by title and author")
            cover = try_isbns(self._search(book))
        return cover
