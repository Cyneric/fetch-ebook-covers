"""
Book Cover Downloader

Read EPUB metadata and declared cover images without extracting
or modifying the archive.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, ParseError
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

LOG = logging.getLogger(__name__)
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_COVER_BYTES = 20 * 1024 * 1024


class EPUBError(ValueError):
    """An EPUB cannot be read safely or has no usable package document."""


@dataclass(frozen=True)
class BookMetadata:
    title: str = ""
    authors: tuple[str, ...] = ()
    year: str = ""
    isbns: tuple[str, ...] = ()


def normalize_isbn(value: str) -> str | None:
    """Accept ISBN-10/13 identifiers only when their checksum is valid."""
    value = re.sub(r"^(?:urn:isbn:|isbn(?:-1[03])?\s*:?\s*)", "", value.strip(), flags=re.I)
    value = re.sub(r"[\s\-\u2010-\u2015]", "", value).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", value):
        digits = [10 if c == "X" else int(c) for c in value]
        if sum((10 - i) * digit for i, digit in enumerate(digits)) % 11 == 0:
            return value
    if re.fullmatch(r"97[89][0-9]{10}", value):
        if sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0:
            return value
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _read(archive: ZipFile, name: str, limit: int) -> bytes:
    try:
        if archive.getinfo(name).file_size > limit:
            raise EPUBError(f"Archive member exceeds the size limit: {name}")
        with archive.open(name) as stream:
            data = stream.read(limit + 1)
    except (BadZipFile, ZlibError, EOFError, RuntimeError, NotImplementedError) as exc:
        raise EPUBError(f"Unreadable archive member: {name}") from exc
    if len(data) > limit:
        raise EPUBError(f"Archive member exceeds the size limit: {name}")
    return data


def _xml(archive: ZipFile, name: str) -> Element:
    try:
        return fromstring(_read(archive, name, MAX_XML_BYTES))
    except (ParseError, DefusedXmlException, LookupError, ValueError) as exc:
        raise EPUBError(f"Unreadable XML document: {name}") from exc


def _resolve(base: str, href: str) -> str:
    try:
        reference = urlsplit(href)
    except ValueError as exc:
        raise EPUBError("Invalid archive resource reference") from exc
    if reference.scheme or reference.netloc:
        raise EPUBError("External EPUB resource references are not supported")
    path = unquote(reference.path)
    if "\\" in path or path.startswith("/") or "\x00" in path:
        raise EPUBError("Invalid archive resource path")
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), path))
    if name == ".." or name.startswith("../"):
        raise EPUBError("EPUB resource points outside the archive")
    return name


def parse_metadata(package: Element) -> BookMetadata:
    metadata = next((n for n in package if _local_name(n.tag) == "metadata"), None)
    if metadata is None:
        raise EPUBError("Package document has no metadata")
    title, year = "", ""
    authors: list[str] = []
    isbns: list[str] = []
    for node in metadata:
        name, value = _local_name(node.tag), _text(node)
        if name == "title" and not title:
            title = value
        elif name == "creator" and value:
            authors.append(value)
        elif name == "date" and not year:
            match = re.search(r"\b[0-9]{4}\b", value)
            year = match.group() if match else ""
        elif name == "identifier":
            if isbn := normalize_isbn(value):
                isbns.append(isbn)
    return BookMetadata(title, tuple(dict.fromkeys(authors)), year, tuple(dict.fromkeys(isbns)))


def _package(archive: ZipFile) -> tuple[str, Element, BookMetadata]:
    candidates: list[str] = []
    try:
        container = _xml(archive, "META-INF/container.xml")
        for node in container.iter():
            if _local_name(node.tag) == "rootfile" and node.get("full-path"):
                candidates.append(_resolve("", node.attrib["full-path"]))
    except (KeyError, ParseError, DefusedXmlException, EPUBError):
        LOG.debug("Missing or malformed container.xml; searching OPF files")
    candidates.extend(n for n in archive.namelist() if n.lower().endswith(".opf"))
    for name in dict.fromkeys(candidates):
        try:
            package = _xml(archive, name)
            return name, package, parse_metadata(package)
        except (KeyError, ParseError, DefusedXmlException, EPUBError):
            LOG.debug("Unusable package document: %s", name)
    raise EPUBError("No readable EPUB package document found")


def read_metadata(path: Path) -> BookMetadata:
    try:
        with ZipFile(path) as archive:
            return _package(archive)[2]
    except (BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
        raise EPUBError(f"Cannot read EPUB archive ({type(exc).__name__})") from exc


def embedded_covers(path: Path) -> Iterator[bytes]:
    """Yield declared raster images, including images in an EPUB 2 cover page."""
    with ZipFile(path) as archive:
        package_path, package, _ = _package(archive)
        items = [n for n in package.iter() if _local_name(n.tag) == "item"]
        by_id = {n.get("id"): n for n in items}
        hrefs = [
            n.get("href", "") for n in items if "cover-image" in n.get("properties", "").split()
        ]
        for node in package.iter():
            if _local_name(node.tag) == "meta" and node.get("name") == "cover":
                item = by_id.get(node.get("content"))
                if item is not None:
                    hrefs.append(item.get("href", ""))
            elif _local_name(node.tag) == "reference" and "cover" in node.get("type", "").split():
                hrefs.append(node.get("href", ""))
        for href in dict.fromkeys(hrefs):
            if not href:
                continue
            try:
                name = _resolve(package_path, href)
                # Wrappers may reference raster images; no HTML/SVG rendering is attempted.
                if name.lower().endswith((".xhtml", ".html", ".htm", ".svg")):
                    page = _xml(archive, name)
                    for node in page.iter():
                        if _local_name(node.tag) not in ("img", "image"):
                            continue
                        image_href = (
                            node.get("src")
                            or node.get("href")
                            or node.get("{http://www.w3.org/1999/xlink}href")
                        )
                        if image_href:
                            yield _read(archive, _resolve(name, image_href), MAX_COVER_BYTES)
                else:
                    yield _read(archive, name, MAX_COVER_BYTES)
            except (
                KeyError,
                ParseError,
                DefusedXmlException,
                EPUBError,
                RuntimeError,
                BadZipFile,
                NotImplementedError,
            ):
                LOG.warning("Embedded cover reference is unreadable or unsupported: %s", href)
