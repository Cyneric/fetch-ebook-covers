"""
Book Cover Downloader

Test cover image validation, JPEG conversion, and safe file publication.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from fetch_ebook_covers import images


def test_png_becomes_real_jpeg(png):
    with Image.open(BytesIO(images.to_jpeg(png))) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (80, 120)


def test_transparency_is_composited_on_white():
    buffer = BytesIO()
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(buffer, "PNG")
    with Image.open(BytesIO(images.to_jpeg(buffer.getvalue()))) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("data", [b"", b"<html>Not found</html>", b"\xff\xd8\xff\xe0broken"])
def test_non_images_rejected(data):
    with pytest.raises(images.InvalidImage):
        images.to_jpeg(data)


def test_truncated_image_rejected(png):
    with pytest.raises(images.InvalidImage):
        images.to_jpeg(png[: len(png) // 2])


def test_known_placeholder_hash_preserved(png, monkeypatch):
    monkeypatch.setattr(
        images, "GENERIC_COVER_HASHES", {hashlib.md5(png, usedforsecurity=False).hexdigest()}
    )
    with pytest.raises(images.InvalidImage, match="placeholder"):
        images.to_jpeg(png)


def test_tiny_placeholder_rejected():
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, "PNG")
    with pytest.raises(images.InvalidImage, match="too small"):
        images.to_jpeg(buffer.getvalue())


@pytest.mark.parametrize("constant, limit", [("MAX_IMAGE_BYTES", 10), ("MAX_IMAGE_PIXELS", 100)])
def test_image_resource_limits(png, monkeypatch, constant, limit):
    monkeypatch.setattr(images, constant, limit)
    with pytest.raises(images.InvalidImage):
        images.to_jpeg(png)


@pytest.mark.parametrize("name", ["cover.jpg", "COVER.JPEG", "cover.png", "Cover.WebP"])
def test_existing_cover_variants(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"existing")
    assert images.existing_cover(tmp_path) == path


def test_atomic_save_and_no_overwrite(tmp_path, png):
    destination = tmp_path / "cover.jpg"
    images.save_cover(png, destination)
    assert destination.read_bytes() == png
    with pytest.raises(FileExistsError):
        images.save_cover(b"replacement", destination)
    assert destination.read_bytes() == png
    assert list(tmp_path.glob(".cover-*.tmp")) == []


def test_different_existing_extension_not_overwritten(tmp_path):
    (tmp_path / "cover.png").write_bytes(b"old")
    with pytest.raises(FileExistsError):
        images.save_cover(b"new", tmp_path / "cover.jpg")
    assert not (tmp_path / "cover.jpg").exists()


def test_force_replaces_only_requested_destination(tmp_path):
    destination = tmp_path / "cover.jpg"
    destination.write_bytes(b"old")
    (tmp_path / "cover.png").write_bytes(b"other")
    images.save_cover(b"new", destination, force=True)
    assert destination.read_bytes() == b"new"
    assert (tmp_path / "cover.png").read_bytes() == b"other"


def test_concurrent_creation_cannot_be_clobbered(tmp_path, monkeypatch):
    destination = tmp_path / "cover.jpg"
    original_link = images.os.link

    def racing_link(source, target):
        target.write_bytes(b"other writer")
        return original_link(source, target)

    monkeypatch.setattr(images.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        images.save_cover(b"new", destination)
    assert destination.read_bytes() == b"other writer"
    assert list(tmp_path.glob(".cover-*.tmp")) == []


@pytest.mark.parametrize("exception", [OSError("disk failure"), KeyboardInterrupt()])
def test_interrupted_write_preserves_existing_cover(tmp_path, monkeypatch, exception):
    destination = tmp_path / "cover.jpg"
    destination.write_bytes(b"original")

    def fail(*args):
        raise exception

    monkeypatch.setattr(images.os, "fsync", fail)
    with pytest.raises(type(exception)):
        images.save_cover(b"new", destination, force=True)
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.glob(".cover-*.tmp")) == []


def test_failed_publish_preserves_cover(tmp_path, monkeypatch):
    destination = tmp_path / "cover.jpg"
    destination.write_bytes(b"original")

    def fail(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(images.os, "replace", fail)
    with pytest.raises(PermissionError):
        images.save_cover(b"new", destination, force=True)
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.glob(".cover-*.tmp")) == []
