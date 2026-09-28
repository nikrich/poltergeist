from __future__ import annotations

from datetime import UTC, datetime

import pytest
from googleapiclient.errors import HttpError

from ghostbrain.connectors.gdrive import drive
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from tests.gdrive_fakes import FakeDrive, drive_file, http_error


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(drive, "_sleep", lambda s: None)


def test_build_query_window_and_mimes():
    q = drive.build_query(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert q.startswith("trashed = false and (")
    for m in drive.SUPPORTED_MIMES:
        assert f"mimeType = '{m}'" in q
    assert "modifiedTime > '2026-09-01T00:00:00'" in q
    assert "modifiedTime < '2026-10-01T00:00:00'" in q
    assert "modifiedTime <" not in drive.build_query(datetime(2026, 9, 1, tzinfo=UTC))


def test_list_page_pages_and_passes_params():
    fake = FakeDrive([drive_file(str(i), modified=f"2026-09-0{i}T10:00:00.000Z") for i in range(1, 4)])
    files, token = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC), page_size=2)
    assert [f["id"] for f in files] == ["3", "2"] and token == "2"
    files, token = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC), page_size=2, page_token=token)
    assert [f["id"] for f in files] == ["1"] and token is None
    kw = fake.list_calls[0]
    assert kw["supportsAllDrives"] and kw["includeItemsFromAllDrives"]
    assert kw["orderBy"] == "modifiedTime desc"
    assert kw["fields"] == f"nextPageToken,files({drive.FILE_FIELDS})"


@pytest.mark.parametrize("owned,mod,expected", [
    (True, False, True), (False, True, True), (False, False, False),
])
def test_is_mine(owned, mod, expected):
    assert drive.is_mine(drive_file("x", owned=owned, modified_by_me=mod)) is expected


def test_execute_retries_rate_limit_then_succeeds():
    fake = FakeDrive([drive_file("a")])
    fake.fail_next = [http_error(403, "userRateLimitExceeded"), http_error(503, "backendError")]
    files, _ = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))
    assert [f["id"] for f in files] == ["a"]


def test_execute_gives_up_after_retries():
    fake = FakeDrive([drive_file("a")])
    fake.fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    with pytest.raises(drive.DriveRateLimited):
        drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))


def test_execute_maps_api_disabled():
    fake = FakeDrive()
    fake.fail_next = [http_error(403, "accessNotConfigured")]
    with pytest.raises(drive.DriveApiDisabled, match="Enable the Google Sheets API"):
        drive.execute(fake.list(q=""), api="Sheets")


def test_execute_maps_401_to_auth_error():
    fake = FakeDrive()
    fake.fail_next = [http_error(401, "authError")]
    with pytest.raises(GdriveAuthError):
        drive.execute(fake.list(q=""))


def test_execute_reraises_other_http_errors():
    fake = FakeDrive()
    fake.fail_next = [http_error(404, "notFound")]
    with pytest.raises(HttpError):
        drive.execute(fake.list(q=""))


def test_folder_path_walks_parents_and_skips_root():
    fake = FakeDrive()
    fake.folders = {
        "p2": {"id": "p2", "name": "Specs", "parents": ["p1"]},
        "p1": {"id": "p1", "name": "Work", "parents": ["root"]},
        "root": {"id": "root", "name": "My Drive"},
    }
    cache: dict = {}
    assert drive.folder_path(fake, drive_file("f", parents=["p2"]), cache) == "Work/Specs"
    assert set(cache) == {"p2", "p1", "root"}
    assert drive.folder_path(fake, drive_file("g"), cache) is None


def test_folder_path_is_best_effort():
    fake = FakeDrive()
    fake.fail_next = [http_error(404, "notFound")]
    assert drive.folder_path(fake, drive_file("f", parents=["gone"]), {}) is None


def test_parse_time_handles_z_and_millis():
    assert drive.parse_time("2026-09-01T10:00:00.123Z") == datetime(2026, 9, 1, 10, 0, 0, 123000, tzinfo=UTC)


@pytest.mark.parametrize("reason", ["dailyLimitExceeded", "quotaExceeded"])
def test_execute_treats_quota_403s_as_rate_limits(reason):
    fake = FakeDrive([drive_file("a")])
    fake.fail_next = [http_error(403, reason)]
    files, _ = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))
    assert [f["id"] for f in files] == ["a"]
    fake.fail_next = [http_error(403, reason)] * (drive.MAX_RETRIES + 1)
    with pytest.raises(drive.DriveRateLimited):
        drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))


class _FailingDownloader:
    """MediaIoBaseDownload stand-in: writes one chunk, then raises ``error``."""

    error: Exception | None = None

    def __init__(self, fh, request, chunksize):
        self.fh, self.calls = fh, 0

    def next_chunk(self, num_retries=0):
        self.calls += 1
        if self.calls == 1:
            self.fh.write(b"part")
            return None, False
        raise type(self).error


@pytest.mark.parametrize("error,expected", [
    (http_error(401, "authError"), GdriveAuthError),
    (http_error(429, "rateLimitExceeded"), drive.DriveRateLimited),
    (http_error(503, "backendError"), drive.DriveRateLimited),
    (http_error(403, "userRateLimitExceeded"), drive.DriveRateLimited),
    (http_error(403, "quotaExceeded"), drive.DriveRateLimited),
    (http_error(403, "accessNotConfigured"), drive.DriveApiDisabled),
    (http_error(404, "notFound"), HttpError),
])
def test_download_maps_http_errors_like_execute(monkeypatch, tmp_path, error, expected):
    import googleapiclient.http

    _FailingDownloader.error = error
    monkeypatch.setattr(googleapiclient.http, "MediaIoBaseDownload", _FailingDownloader)
    with pytest.raises(expected) as info:
        drive.download(FakeDrive(), "f1", tmp_path / "out")
    if expected is HttpError:
        assert info.value is error
    else:
        assert info.value.__cause__ is error


def test_download_streams_all_chunks(monkeypatch, tmp_path):
    import googleapiclient.http

    class _Ok:
        def __init__(self, fh, request, chunksize):
            self.fh, self.n = fh, 0

        def next_chunk(self, num_retries=0):
            self.n += 1
            self.fh.write(b"ab")
            return None, self.n == 2

    monkeypatch.setattr(googleapiclient.http, "MediaIoBaseDownload", _Ok)
    drive.download(FakeDrive(), "f1", tmp_path / "out")
    assert (tmp_path / "out").read_bytes() == b"abab"
