"""
Book Cover Downloader

Verify an installed package outside the source checkout using a generated
EPUB and the public command-line entry points.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

import fetch_ebook_covers


def main() -> None:
    checkout = Path(__file__).resolve().parents[1]
    module_path = Path(fetch_ebook_covers.__file__).resolve()
    # A venv may be inside the checkout, but the module must come from site-packages.
    assert "site-packages" in module_path.parts, module_path
    assert module_path != checkout / "fetch_ebook_covers" / "__init__.py"
    executable = Path(sys.executable).parent / (
        "fetch-ebook-covers.exe" if sys.platform == "win32" else "fetch-ebook-covers"
    )
    with tempfile.TemporaryDirectory(prefix="covers-smoke-") as directory:
        root = Path(directory)
        book = root / "Smoke Book.EPUB"
        buffer = BytesIO()
        Image.new("RGB", (60, 100), "navy").save(buffer, "PNG")
        with ZipFile(book, "w") as archive:
            archive.writestr(
                "META-INF/container.xml", '<container><rootfile full-path="book.opf"/></container>'
            )
            archive.writestr(
                "book.opf",
                '<package><metadata><title>Smoke Book</title></metadata><manifest><item properties="cover-image" href="cover.png"/></manifest></package>',
            )
            archive.writestr("cover.png", buffer.getvalue())
        original = book.read_bytes()
        dry = subprocess.run(
            [str(executable), str(book), "--dry-run"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "planned=1" in dry.stderr
        assert not (root / "cover.jpg").exists()
        run = subprocess.run(
            [str(executable), str(book), "--offline"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "saved=1" in run.stderr
        with Image.open(root / "cover.jpg") as image:
            assert image.format == "JPEG"
        assert book.read_bytes() == original
        module = subprocess.run(
            [sys.executable, "-m", "fetch_ebook_covers", str(root), "--offline"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "skipped=1" in module.stderr
        assert "\x1b" not in run.stderr
    print(
        "Installed-wheel smoke passed: dry-run, offline extraction, module entry point, existing-cover skip, and EPUB preservation."
    )


if __name__ == "__main__":
    main()
