"""Contract tests over the actual pinned SDK HTTP/Xet progress hooks, offline."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace
import sys

import pytest
from huggingface_hub import file_download

from app.services import huggingface_transfer as transfer
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.model_download import download_progress, transition_download


@pytest.mark.parametrize("status", [200, 206])
def test_http_resume_or_range_reset_reports_observed_bytes(monkeypatch, tmp_path, status):
    events = []
    output = BytesIO(b"ab")
    output.seek(2)
    response = SimpleNamespace(status_code=status, headers={"Content-Length": "4" if status == 200 else "2",
                                                          "Content-Range": "bytes 2-3/4"} if status == 206 else {"Content-Length": "4"},
                               iter_content=lambda **kwargs: iter([b"ab", b"cd"] if status == 200 else [b"cd"]))
    monkeypatch.setattr(file_download, "_request_wrapper", lambda **kwargs: response)
    monkeypatch.setattr(file_download, "hf_raise_for_status", lambda r: None)
    monkeypatch.setattr(file_download.constants, "HF_HUB_ENABLE_HF_TRANSFER", False)
    def sdk(*args, **kwargs):
        file_download.http_get("https://example.invalid/file", output, resume_size=2, expected_size=4)
        return str(tmp_path / "file")
    monkeypatch.setattr(transfer, "hf_hub_download", sdk)
    transfer.download_file("owner/repository", "file.gguf", revision="a" * 40, local_dir=tmp_path,
                           callback=lambda n, total: events.append((n, total)))
    assert output.getvalue() == b"abcd"
    assert events[0] == (0 if status == 200 else 2, 4)
    assert events[-1] == (4, 4)
    assert transfer._callback.get() is None


def test_xet_progress_uses_callbacks_not_preallocated_file_size(tmp_path, monkeypatch):
    target = tmp_path / "file.incomplete"
    target.write_bytes(b"\0" * 1000)  # simulated preallocation must not become progress
    events = []
    def xet_download(infos, **kwargs):
        for size in (200, 300, 500):
            kwargs["progress_updater"][0](size)
    monkeypatch.setitem(sys.modules, "hf_xet", SimpleNamespace(
        PyXetDownloadInfo=lambda **kwargs: kwargs, download_files=xet_download))
    monkeypatch.setattr(file_download, "refresh_xet_connection_info", lambda **kwargs: SimpleNamespace(
        endpoint="https://example.invalid", access_token="not-a-real-token", expiration_unix_epoch=1))
    def sdk(*args, **kwargs):
        file_download.xet_get(incomplete_path=target, xet_file_data=SimpleNamespace(file_hash="a" * 64), headers={}, expected_size=1000)
        return str(target)
    monkeypatch.setattr(transfer, "hf_hub_download", sdk)
    transfer.download_file("owner/repository", "file.gguf", revision="a" * 40, local_dir=tmp_path,
                           callback=lambda n, total: events.append((n, total)))
    assert events == [(0, 1000), (200, 1000), (500, 1000), (1000, 1000)]


def test_progress_is_scoped_to_each_transfer_and_non_studio_calls_fall_through(tmp_path, monkeypatch):
    def sdk(repo, filename, **kwargs):
        with file_download._get_progress_bar_context(desc=filename, log_level=20, total=2, initial=0) as bar:
            bar.update(1); bar.update(1)
        return filename
    monkeypatch.setattr(transfer, "hf_hub_download", sdk)
    def run(name):
        events = []
        transfer.download_file("owner/repository", name, revision="a" * 40, local_dir=tmp_path,
                               callback=lambda n, total: events.append(n))
        return events
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, ["one.gguf", "two.gguf"])) == [[0, 1, 2], [0, 1, 2]]
    calls = []
    monkeypatch.setattr(transfer, "_original_progress", lambda **kwargs: calls.append(kwargs) or "original")
    assert file_download._get_progress_bar_context(desc="outside", log_level=20) == "original"
    assert len(calls) == 1 and transfer._callback.get() is None


def test_callback_scope_is_reset_even_when_sdk_fails(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError("interrupted")
    monkeypatch.setattr(transfer, "hf_hub_download", failed)
    with pytest.raises(OSError):
        transfer.download_file("owner/repository", "one.gguf", revision="a" * 40, local_dir=tmp_path, callback=lambda *args: None)
    assert transfer._callback.get() is None


def test_download_states_and_unknown_totals_never_fabricate_percentages():
    job = {"status": "queued", "files": [{"name": "a", "bytes": None, "downloaded_bytes": 5}], "current_file": "a"}
    assert download_progress(job)["percentage"] is None
    assert download_progress(job)["eta_seconds"] is None
    for status in ("downloading", "verifying", "registering", "complete"):
        transition_download(job, status)
    with pytest.raises(ValidationError):
        transition_download(job, "downloading")
    assert download_progress(job)["bytes_per_second"] is None
    job = {"status": "downloading", "files": [{"name": "a", "bytes": 20, "downloaded_bytes": 5}], "bytes_per_second": 5}
    progress = download_progress(job)
    assert progress["percentage"] == 25 and progress["eta_seconds"] == 3
