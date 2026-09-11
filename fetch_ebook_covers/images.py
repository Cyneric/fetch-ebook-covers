"""
Book Cover Downloader

Validate cover images, convert them to JPEG, and safely save completed
cover files beside their EPUBs.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
GENERIC_COVER_HASHES = {
    "f81b2d84d8a69ba9e8bf1f50c806faab",
    "0d23d0b62908b75e89014ac3f864484e",
}
COVER_FILENAMES = {"cover.jpg", "cover.jpeg", "cover.png", "cover.webp"}


class InvalidImage(ValueError):
    """A download is not a usable cover image."""


def to_jpeg(content: bytes) -> bytes:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise InvalidImage("Empty image or image larger than 20 MiB")
    if hashlib.md5(content, usedforsecurity=False).hexdigest() in GENERIC_COVER_HASHES:
        raise InvalidImage("Known placeholder cover")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidImage("Image exceeds 40 million pixels")
                if min(image.size) < 10:
                    raise InvalidImage("Image is too small to be a cover")
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgba = oriented.convert("RGBA")
                result = Image.new("RGB", rgba.size, "white")
                result.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                result.save(output, format="JPEG", quality=95)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise InvalidImage(f"Invalid or unsupported cover image: {exc}") from exc


def existing_cover(directory: Path) -> Path | None:
    return next((p for p in sorted(directory.iterdir()) if p.name.lower() in COVER_FILENAMES), None)


def save_cover(content: bytes, destination: Path, *, force: bool = False) -> None:
    """Publish a finished file; without force, a racing writer always wins."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cover-", suffix=".tmp", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, destination)
        else:
            if existing_cover(destination.parent):
                raise FileExistsError("A folder cover already exists")
            # Atomic publication fails if the target appeared meanwhile. Unsupported
            # filesystems fail safely rather than risk overwriting an existing cover.
            os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
