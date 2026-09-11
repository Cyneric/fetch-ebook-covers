"""
Book Cover Downloader

Provide generated EPUB and image fixtures and prevent live network access
during automated tests.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from io import BytesIO
from zipfile import ZipFile

import pytest
import requests
from PIL import Image


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never access the network")

    monkeypatch.setattr(requests.Session, "get", forbidden)


@pytest.fixture
def png():
    stream = BytesIO()
    Image.new("RGBA", (80, 120), (100, 20, 150, 180)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def make_epub(tmp_path, png):
    def make(
        name="book.epub",
        *,
        metadata=None,
        manifest="",
        extra="",
        members=None,
        container=True,
        package_path="OPS/book.opf",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if metadata is None:
            metadata = "<dc:title>The Test Book</dc:title><dc:creator>Jane Example</dc:creator><dc:date>2024-01-01</dc:date><dc:identifier>urn:isbn:9780306406157</dc:identifier>"
        package = f'<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>{metadata}</metadata><manifest>{manifest}</manifest>{extra}</package>'
        with ZipFile(path, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            if container:
                content = (
                    f'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="{package_path}"/></rootfiles></container>'
                    if container is True
                    else container
                )
                archive.writestr("META-INF/container.xml", content)
            archive.writestr(package_path, package)
            for member, content in (members or {}).items():
                archive.writestr(member, content)
        return path

    return make
