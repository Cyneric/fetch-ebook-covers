"""
Book Cover Downloader

Test EPUB metadata parsing, ISBN validation, and embedded cover discovery.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from zipfile import ZipFile

import pytest
from defusedxml.ElementTree import fromstring

from fetch_ebook_covers import epub


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("urn:isbn:978-0-306-40615-7", "9780306406157"),
        (" ISBN-13: 978 0 306 40615 7 ", "9780306406157"),
        ("0-8044-2957-x", "080442957X"),
        ("0306406152", "0306406152"),
        ("9780306406158", None),
        ("0306406153", None),
        ("urn:uuid:9780306406157", None),
        ("123", None),
        ("9780306406157 extra", None),
        ("９７８０３０６４０６１５７", None),
    ],
)
def test_isbn_validation(raw, expected):
    assert epub.normalize_isbn(raw) == expected


def test_metadata_namespace_variations_and_multiple_identifiers():
    package = fromstring("""<p:package xmlns:p="http://www.idpf.org/2007/opf" xmlns:d="http://purl.org/dc/elements/1.1/">
    <p:metadata><d:title> A <d:span>Test</d:span> Book </d:title>
    <d:creator>Jane Example</d:creator><d:creator>John Example</d:creator>
    <d:date>2024-06-01</d:date><d:identifier>invalid</d:identifier>
    <d:identifier>9780306406157</d:identifier><d:identifier>0306406152</d:identifier>
    <d:identifier>urn:isbn:9780306406157</d:identifier></p:metadata></p:package>""")
    metadata = epub.parse_metadata(package)
    assert metadata == epub.BookMetadata(
        "A Test Book", ("Jane Example", "John Example"), "2024", ("9780306406157", "0306406152")
    )


def test_container_package_takes_precedence(make_epub):
    path = make_epub(
        members={"old.opf": "<package><metadata><title>Wrong book</title></metadata></package>"}
    )
    assert epub.read_metadata(path).title == "The Test Book"


@pytest.mark.parametrize(
    "container", [False, "malformed", '<container><rootfile full-path="missing.opf"/></container>']
)
def test_legacy_opf_fallback(make_epub, container):
    path = make_epub(container=container, package_path="legacy.OPF")
    assert epub.read_metadata(path).isbns == ("9780306406157",)


def test_skips_malformed_package_before_valid_fallback(make_epub):
    path = make_epub(
        container='<container><rootfile full-path="bad.opf"/></container>',
        members={"bad.opf": "not XML"},
    )
    assert epub.read_metadata(path).title == "The Test Book"


def test_xml_entity_expansion_rejected(tmp_path):
    path = tmp_path / "bad.epub"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "book.opf",
            '<!DOCTYPE package [<!ENTITY x "expanded">]><package><metadata><title>&x;</title></metadata></package>',
        )
    with pytest.raises(epub.EPUBError):
        epub.read_metadata(path)


def test_unknown_xml_encoding_is_reported_as_epub_error(tmp_path):
    path = tmp_path / "bad.epub"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "book.opf",
            '<?xml version="1.0" encoding="made-up-encoding"?><package><metadata/></package>',
        )
    with pytest.raises(epub.EPUBError):
        epub.read_metadata(path)


def test_oversized_xml_rejected(make_epub, monkeypatch):
    path = make_epub()
    monkeypatch.setattr(epub, "MAX_XML_BYTES", 20)
    with pytest.raises(epub.EPUBError):
        epub.read_metadata(path)


def test_corrupt_archive(tmp_path):
    path = tmp_path / "broken.epub"
    path.write_bytes(b"not a ZIP file")
    with pytest.raises(epub.EPUBError):
        epub.read_metadata(path)


def test_corrupt_compressed_member_is_reported_as_epub_error(make_epub, monkeypatch):
    path = make_epub()

    def broken_member(*args, **kwargs):
        raise epub.ZlibError("invalid compressed stream")

    monkeypatch.setattr(ZipFile, "open", broken_member)
    with pytest.raises(epub.EPUBError):
        epub.read_metadata(path)


def test_epub3_cover_with_encoded_relative_path(make_epub, png):
    path = make_epub(
        manifest='<item id="cover" properties="nav cover-image" href="../images/my%20cover.png"/>',
        members={"images/my cover.png": png},
    )
    before = path.read_bytes()
    assert list(epub.embedded_covers(path)) == [png]
    assert path.read_bytes() == before


def test_epub2_cover_metadata(make_epub, png):
    path = make_epub(
        metadata='<dc:title>Old</dc:title><meta name="cover" content="picture"/>',
        manifest='<item id="picture" href="cover.png"/>',
        members={"OPS/cover.png": png},
    )
    assert list(epub.embedded_covers(path)) == [png]


@pytest.mark.parametrize(
    "wrapper",
    [
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="../images/cover.png"/></body></html>',
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="../images/cover.png"/></svg>',
    ],
)
def test_epub2_guide_cover_wrapper(make_epub, png, wrapper):
    path = make_epub(
        extra='<guide><reference type="cover" href="text/cover.xhtml#image"/></guide>',
        members={"OPS/text/cover.xhtml": wrapper, "OPS/images/cover.png": png},
    )
    assert list(epub.embedded_covers(path)) == [png]


@pytest.mark.parametrize(
    "href",
    [
        "../../escape.png",
        "https://example.com/cover.png",
        "//example.com/cover.png",
        "/absolute.png",
        "..%2f..%2fescape.png",
        "..\\cover.png",
    ],
)
def test_unsafe_archive_references_skipped(make_epub, href):
    path = make_epub(manifest=f'<item properties="cover-image" href="{href}"/>')
    assert list(epub.embedded_covers(path)) == []


def test_missing_embedded_candidate_allows_next_candidate(make_epub, png):
    path = make_epub(
        manifest='<item properties="cover-image" href="missing.png"/><item properties="cover-image" href="cover.png"/>',
        members={"OPS/cover.png": png},
    )
    assert list(epub.embedded_covers(path)) == [png]


def test_oversized_cover_skipped(make_epub, png, monkeypatch):
    path = make_epub(
        manifest='<item properties="cover-image" href="cover.png"/>', members={"OPS/cover.png": png}
    )
    monkeypatch.setattr(epub, "MAX_COVER_BYTES", 10)
    assert list(epub.embedded_covers(path)) == []


def test_malformed_embedded_url_does_not_abort_fallback(make_epub, png):
    path = make_epub(
        manifest='<item properties="cover-image" href="https://[invalid"/><item properties="cover-image" href="cover.png"/>',
        members={"OPS/cover.png": png},
    )
    assert list(epub.embedded_covers(path)) == [png]
