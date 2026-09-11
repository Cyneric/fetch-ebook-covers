"""
Book Cover Downloader

Test command-line behavior, offline extraction, batch processing,
and compatibility between entry points.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from fetch_ebook_covers import cli


def embedded_book(make_epub, png, name="book.epub"):
    return make_epub(
        name,
        manifest='<item properties="cover-image" href="cover.png"/>',
        members={"OPS/cover.png": png},
    )


def test_offline_extracts_real_cover_without_network(make_epub, png, capsys):
    path = embedded_book(make_epub, png)
    original = path.read_bytes()
    assert cli.main([str(path), "--offline"]) == 0
    assert (path.parent / "cover.jpg").read_bytes().startswith(b"\xff\xd8")
    assert path.read_bytes() == original
    assert "saved=1" in capsys.readouterr().err


def test_dry_run_no_network_or_writes(make_epub, monkeypatch, capsys):
    path = make_epub()
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        cli, "CoverClient", Mock(side_effect=AssertionError("must not create client"))
    )
    assert cli.main([str(path.parent), "--dry-run"]) == 0
    after = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    assert before == after
    assert "planned=1" in capsys.readouterr().err


def test_offline_missing_cover_exit_code(make_epub, capsys):
    path = make_epub()
    assert cli.main([str(path), "--offline"]) == 1
    assert "missing=1" in capsys.readouterr().err


def test_existing_cover_skips_even_corrupt_epub(tmp_path, capsys):
    path = tmp_path / "bad.epub"
    path.write_bytes(b"bad")
    (tmp_path / "cover.webp").write_bytes(b"existing")
    assert cli.main([str(tmp_path), "--offline"]) == 0
    assert "skipped=1" in capsys.readouterr().err


def test_force_replaces_after_validation(make_epub, png):
    path = embedded_book(make_epub, png)
    cover = path.parent / "cover.jpg"
    cover.write_bytes(b"old")
    assert cli.main([str(path), "--offline", "--force"]) == 0
    assert cover.read_bytes().startswith(b"\xff\xd8")


def test_force_missing_cover_preserves_existing(make_epub):
    path = make_epub()
    cover = path.parent / "cover.jpg"
    cover.write_bytes(b"original")
    assert cli.main([str(path), "--offline", "--force"]) == 1
    assert cover.read_bytes() == b"original"


def test_batch_continues_after_corrupt_archive_and_finds_uppercase(make_epub, png, capsys):
    good = embedded_book(make_epub, png, "b/book.EPUB")
    bad = good.parent.parent / "a" / "bad.epub"
    bad.parent.mkdir()
    bad.write_bytes(b"broken")
    assert cli.main([str(bad.parent.parent), "--offline"]) == 1
    assert (good.parent / "cover.jpg").exists()
    output = capsys.readouterr().err
    assert "saved=1" in output
    assert "failed=1" in output


def test_multiple_books_one_folder_only_one_write_even_with_force(make_epub, png, capsys):
    first = embedded_book(make_epub, png, "a.epub")
    embedded_book(make_epub, png, "b.epub")
    assert cli.main([str(first.parent), "--offline", "--force"]) == 0
    output = capsys.readouterr().err
    assert "saved=1 skipped=1" in output


def test_failed_first_book_does_not_prevent_second_book(make_epub, png, capsys):
    make_epub("a.epub")
    second = embedded_book(make_epub, png, "b.epub")
    assert cli.main([str(second.parent), "--offline"]) == 1
    assert (second.parent / "cover.jpg").exists()
    assert "saved=1 skipped=0 missing=1" in capsys.readouterr().err


def test_prefer_embedded_avoids_online_lookup(make_epub, png, monkeypatch):
    path = embedded_book(make_epub, png)
    find = Mock(side_effect=AssertionError("must use embedded cover"))
    monkeypatch.setattr(cli.CoverClient, "find_cover", find)
    assert cli.main([str(path), "--prefer-embedded"]) == 0
    find.assert_not_called()


def test_invalid_embedded_cover_falls_back_online(make_epub, png, monkeypatch):
    path = make_epub(
        manifest='<item properties="cover-image" href="cover.png"/>',
        members={"OPS/cover.png": b"not an image"},
    )
    find = Mock(return_value=cli.to_jpeg(png))
    monkeypatch.setattr(cli.CoverClient, "find_cover", find)
    assert cli.main([str(path), "--prefer-embedded"]) == 0
    find.assert_called_once()


def test_unreadable_embedded_cover_falls_back_online(make_epub, png, monkeypatch):
    path = make_epub(manifest='<item properties="cover-image" href="missing.png"/>')
    find = Mock(return_value=cli.to_jpeg(png))
    monkeypatch.setattr(cli.CoverClient, "find_cover", find)
    assert cli.main([str(path), "--prefer-embedded"]) == 0
    find.assert_called_once()


def test_provider_errors_classified_as_failed(make_epub, monkeypatch, capsys):
    path = make_epub()

    def fail(client, *args):
        client.had_error = True
        return None

    monkeypatch.setattr(cli.CoverClient, "find_cover", fail)
    assert cli.main([str(path)]) == 1
    assert "missing=0 failed=1" in capsys.readouterr().err


def test_write_error_continues_to_next_folder(make_epub, png, monkeypatch, capsys):
    first = embedded_book(make_epub, png, "a/book.epub")
    second = embedded_book(make_epub, png, "b/book.epub")
    original_save = cli.save_cover

    def save(content, destination, **kwargs):
        if destination.parent == first.parent:
            raise PermissionError("Read-only directory")
        original_save(content, destination, **kwargs)

    monkeypatch.setattr(cli, "save_cover", save)
    assert cli.main([str(first.parent.parent), "--offline"]) == 1
    assert (second.parent / "cover.jpg").exists()
    assert "saved=1 skipped=0 missing=0 failed=1" in capsys.readouterr().err


def test_default_mode_still_downloads_despite_embedded_cover(make_epub, png, monkeypatch):
    path = embedded_book(make_epub, png)
    find = Mock(return_value=cli.to_jpeg(png))
    monkeypatch.setattr(cli.CoverClient, "find_cover", find)
    assert cli.main([str(path)]) == 0
    find.assert_called_once()


def test_client_receives_settings_and_environment_key(make_epub, monkeypatch):
    path = make_epub()
    client = Mock(had_error=False)
    client.find_cover.return_value = None
    factory = Mock(return_value=client)
    monkeypatch.setattr(cli, "CoverClient", factory)
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "private")
    assert (
        cli.main(
            [str(path), "--timeout", "5", "--retries", "0", "--sources", "openlibrary,buch.isbn.de"]
        )
        == 1
    )
    factory.assert_called_once_with(timeout=5, retries=0, api_key="private")
    assert client.find_cover.call_args.args[1] == ("openlibrary", "buch.isbn.de")
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--timeout", "0"],
        ["--timeout", "nan"],
        ["--timeout", "inf"],
        ["--retries", "-1"],
        ["--retries", "11"],
        ["--retries", "1.5"],
        ["--sources", "unknown"],
        ["--sources", ""],
    ],
)
def test_invalid_options_exit_two(tmp_path, arguments):
    with pytest.raises(SystemExit) as exc:
        cli.main([str(tmp_path), *arguments])
    assert exc.value.code == 2


def test_invalid_input_exit_two(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main([str(tmp_path / "missing")])
    assert exc.value.code == 2


def test_empty_directory_success(tmp_path, capsys):
    assert cli.main([str(tmp_path), "--offline"]) == 0
    assert "Found 0 EPUB" in capsys.readouterr().err


def test_interruption_returns_130_and_closes_session(make_epub, monkeypatch, capsys):
    path = make_epub()
    client = Mock()
    client.find_cover.side_effect = KeyboardInterrupt
    monkeypatch.setattr(cli, "CoverClient", Mock(return_value=client))
    assert cli.main([str(path)]) == 130
    client.close.assert_called_once()
    assert "Interrupted" in capsys.readouterr().err


def test_redirected_output_has_no_ansi(make_epub, capsys):
    path = make_epub()
    cli.main([str(path), "--dry-run", "--verbose"])
    assert "\x1b" not in capsys.readouterr().err


def test_no_color_and_no_color_environment(make_epub, monkeypatch):
    path = make_epub()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    cli.main([str(path), "--dry-run", "--no-color"])
    assert not cli.logging.getLogger("fetch_ebook_covers").handlers[0].formatter.color
    monkeypatch.setenv("NO_COLOR", "")
    cli.main([str(path), "--dry-run"])
    assert not cli.logging.getLogger("fetch_ebook_covers").handlers[0].formatter.color


def test_launcher_module_and_installed_command_agree():
    root = Path(__file__).resolve().parents[1]
    scripts = Path(sys.executable).parent
    console = scripts / (
        "fetch-ebook-covers.exe" if sys.platform == "win32" else "fetch-ebook-covers"
    )
    commands = [
        [sys.executable, str(root / "getBookCovers.py")],
        [sys.executable, "-m", "fetch_ebook_covers"],
        [str(console)],
    ]
    outputs = [
        subprocess.run(
            [*command, "--help"], cwd=root, capture_output=True, text=True, check=True
        ).stdout
        for command in commands
    ]
    assert outputs[0] == outputs[1] == outputs[2]
