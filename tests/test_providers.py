"""
Book Cover Downloader

Test provider selection, metadata matching, HTTP failures, retries,
and request pacing without live network access.

Author: Christian Blank <christianblank91@gmail.com>
License: MIT License
Copyright (c) 2026 Christian Blank
"""

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests

from fetch_ebook_covers import providers
from fetch_ebook_covers.epub import BookMetadata

ISBN = "9780306406157"


class Response:
    def __init__(self, status=200, data=b"", headers=None, chunks=None):
        self.status_code = status
        self.data = data
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        yield from self.chunks if self.chunks is not None else [self.data]


@pytest.fixture
def client(monkeypatch):
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(providers.time, "sleep", sleep)
    instance = providers.CoverClient()
    instance.session.get = Mock()
    instance.clock = clock
    yield instance
    instance.close()


def volume(title="The Test Book", authors=None, year="2024", isbn=ISBN, images=None):
    return {
        "title": title,
        "authors": ["Jane Example"] if authors is None else authors,
        "publishedDate": year,
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}],
        "imageLinks": images or {},
    }


def google_response(*infos):
    return Response(data=json.dumps({"items": [{"volumeInfo": info} for info in infos]}).encode())


def test_provider_fallback_rejects_html_and_preserves_order(client, png):
    client.session.get.side_effect = [Response(data=b"<html>oops</html>"), Response(data=png)]
    cover = client.find_cover(BookMetadata(isbns=(ISBN,)), providers.SOURCES)
    assert cover.startswith(b"\xff\xd8")
    urls = [call.args[0] for call in client.session.get.call_args_list]
    assert "buch.isbn.de" in urls[0]
    assert urls[1] == f"https://covers.openlibrary.org/b/isbn/{ISBN}-L.jpg?default=false"


def test_all_metadata_isbns_tried_before_title_search(client, png):
    client.session.get.side_effect = [Response(404), Response(data=png)]
    result = client.find_cover(BookMetadata("Test", isbns=(ISBN, "0306406152")), ("buch.isbn.de",))
    assert result is not None
    assert "0306406152" in client.session.get.call_args_list[1].args[0]


def test_google_cover_matches_isbn10_and_prefers_large_image(client, png):
    client.session.get.side_effect = [
        google_response(
            volume(
                isbn=ISBN,
                images={
                    "large": "http://books.google.com/large",
                    "thumbnail": "https://books.google.com/small",
                },
            )
        ),
        Response(data=png),
    ]
    assert client.find_cover(BookMetadata(isbns=("0306406152",)), ("google",)) is not None
    assert client.session.get.call_args_list[1].args[0] == "https://books.google.com/large"


def test_google_rejects_wrong_edition_identifier(client):
    client.session.get.return_value = google_response(
        volume(isbn="9780140328721", images={"thumbnail": "https://example.com/wrong"})
    )
    assert list(client._urls("google", ISBN)) == []


def test_title_search_matches_author_and_prefers_year(client):
    client.session.get.return_value = google_response(
        volume(title="Wrong title"),
        volume(authors=["Wrong Author"]),
        volume(year="1990", isbn="9780140328721"),
        volume(title="THE TEST BOOK!", authors=["Jane Éxample"], year="2024"),
    )
    assert client._search(BookMetadata("The Test Book", ("Jane Example",), "2024")) == [
        ISBN,
        "9780140328721",
    ]
    params = client.session.get.call_args.kwargs["params"]
    assert params["q"] == 'intitle:"The Test Book" inauthor:"Jane Example"'


def test_title_search_can_work_without_author(client):
    client.session.get.return_value = google_response(volume(authors=[]))
    assert client._search(BookMetadata("The Test Book")) == [ISBN]


def test_title_search_api_relevance_breaks_year_tie(client):
    client.session.get.return_value = google_response(volume(isbn="9780140328721"), volume())
    assert client._search(BookMetadata("The Test Book", ("Jane Example",), "2024")) == [
        "9780140328721",
        ISBN,
    ]


def test_disabling_google_disables_title_search(client):
    assert client.find_cover(BookMetadata("Title", ("Author",)), ("openlibrary",)) is None
    client.session.get.assert_not_called()


def test_no_isbn_title_search_then_cover_download(client, png):
    client.session.get.side_effect = [google_response(volume()), Response(data=png)]
    assert (
        client.find_cover(BookMetadata("The Test Book", ("Jane Example",)), providers.SOURCES)
        is not None
    )
    assert "googleapis" in client.session.get.call_args_list[0].args[0]
    assert "buch.isbn.de" in client.session.get.call_args_list[1].args[0]


def test_google_metadata_cache_avoids_duplicate_queries(client):
    client.session.get.return_value = google_response(volume())
    assert client._volumes("isbn:test") == client._volumes("isbn:test")
    assert client.session.get.call_count == 1


@pytest.mark.parametrize("data", [b"not JSON", b"[]", b'{"items":null}', b'{"error":{}}', b"\xff"])
def test_malformed_json_isolated(client, data):
    client.session.get.return_value = Response(data=data)
    assert client._volumes("test") == []
    assert client.had_error


def test_incomplete_google_items_ignored(client):
    client.session.get.return_value = Response(
        data=b'{"items":[null, {}, {"volumeInfo":null}, {"volumeInfo":{"industryIdentifiers":null}}]}'
    )
    assert list(client._urls("google", ISBN)) == []


@pytest.mark.parametrize(
    "failure", [Response(500), Response(503), Response(429), requests.Timeout("timeout")]
)
def test_transient_failures_retry_and_close_responses(client, failure):
    success = Response(data=b"done")
    client.session.get.side_effect = [failure, success]
    assert client._get("https://example.com/image") == b"done"
    assert client.session.get.call_count == 2
    assert success.closed
    if isinstance(failure, Response):
        assert failure.closed
    assert client.session.get.call_args.kwargs["timeout"] == 10
    assert client.session.get.call_args.kwargs["stream"] is True


def test_retry_limit(client):
    client.session.get.return_value = Response(503)
    assert client._get("https://example.com/image") is None
    assert client.session.get.call_count == 3
    assert client.had_error


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_permanent_failures_are_not_retried(client, status):
    client.session.get.return_value = Response(status)
    assert client._get("https://example.com/image") is None
    assert client.session.get.call_count == 1
    assert client.had_error == (status not in (404, 410))


def test_openlibrary_requests_are_paced_including_retries(client):
    times = []
    responses = iter([Response(503), Response(404), Response(404)])

    def request(*args, **kwargs):
        times.append(client.clock[0])
        return next(responses)

    client.session.get.side_effect = request
    client._get("https://covers.openlibrary.org/first")
    client._get("https://covers.openlibrary.org/second")
    assert times == pytest.approx([0, 3.1, 6.2])


def test_retry_after_honored(client):
    client.session.get.side_effect = [
        Response(429, headers={"Retry-After": "12"}),
        Response(data=b"ok"),
    ]
    assert client._get("https://example.com/image") == b"ok"
    assert client.clock[0] == 12


def test_retry_after_date_and_invalid_values():
    future = datetime.now(UTC) + timedelta(seconds=30)
    assert 28 <= providers._retry_delay(format_datetime(future), 0) <= 31
    assert providers._retry_delay("invalid", 1) == 2


def test_long_retry_after_disables_host_instead_of_retrying_early(client):
    client.session.get.return_value = Response(429, headers={"Retry-After": "3600"})
    assert client._get("https://example.com/image") is None
    assert client._get("https://example.com/other") is None
    assert client.session.get.call_count == 1
    assert client.clock[0] == 0


def test_redirected_rate_limit_applies_to_actual_host(client):
    client.session.get.side_effect = [
        Response(302, headers={"Location": "https://cdn.example.com/image"}),
        Response(429, headers={"Retry-After": "3600"}),
    ]
    assert client._get("https://example.com/image") is None
    assert client._get("https://cdn.example.com/other") is None
    assert client.session.get.call_count == 2


def test_authentication_errors_do_not_leak_api_key(client, caplog):
    client.api_key = "SUPER-SECRET-KEY"
    client.session.get.return_value = Response(403)
    with caplog.at_level("DEBUG"):
        assert client._volumes("test") == []
    assert "SUPER-SECRET-KEY" not in caplog.text
    assert "GOOGLE_BOOKS_API_KEY" in caplog.text
    assert client.session.get.call_args.kwargs["params"]["key"] == "SUPER-SECRET-KEY"


def test_request_exception_url_not_logged(client, caplog):
    client.session.get.side_effect = requests.ConnectionError("https://example.com?key=SECRET")
    with caplog.at_level("DEBUG"):
        client._get("https://example.com")
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "response", [Response(headers={"Content-Length": "10"}), Response(chunks=[b"123", b"456"])]
)
def test_download_size_limits(client, response):
    client.session.get.return_value = response
    assert client._get("https://example.com", limit=5) is None
    assert client.had_error
    assert response.closed


def test_http_redirect_is_rejected(client):
    client.session.get.return_value = Response(
        302, headers={"Location": "http://example.com/plain"}
    )
    assert client._get("https://example.com/image") is None
    assert client.session.get.call_count == 1


def test_https_redirect_is_followed(client):
    client.session.get.side_effect = [
        Response(302, headers={"Location": "https://cdn.example.com/image"}),
        Response(data=b"ok"),
    ]
    assert client._get("https://example.com/image") == b"ok"
    assert client.session.get.call_args.args[0] == "https://cdn.example.com/image"


@pytest.mark.parametrize("location", ["", "https://[invalid"])
def test_malformed_redirect_isolated(client, location):
    client.session.get.return_value = Response(302, headers={"Location": location})
    assert client._get("https://example.com/image") is None
    assert client.had_error
    assert client.session.get.call_count == 1


def test_authenticated_redirect_does_not_forward_key(client):
    client.api_key = "SECRET"
    client.session.get.return_value = Response(
        302, headers={"Location": "https://other.example.com"}
    )
    assert client._volumes("test") == []
    assert client.session.get.call_count == 1


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://user:password@example.com", "not-a-url"]
)
def test_unsupported_url_does_not_request(client, url):
    assert client._get(url) is None
    client.session.get.assert_not_called()
