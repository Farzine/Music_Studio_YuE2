"""Byte callbacks for the pinned huggingface-hub 0.36.2 HTTP/Xet transfers.

Its public hf_hub_download has no progress argument. Isolate the single private
progress-factory seam here, scoped by ContextVar; unrelated SDK calls retain their
original progress bars. No directory-size polling (Xet may preallocate files),
replacement HTTP implementation, global disable flags or token persistence.
"""
from contextvars import ContextVar
from threading import Lock

from huggingface_hub import file_download, hf_hub_download

_callback = ContextVar("studio_hub_progress", default=None)
_original_progress = file_download._get_progress_bar_context


class _Progress:
    def __init__(self, callback, initial, total):
        self.callback, self.n, self.total = callback, initial, total
        self.lock = Lock()

    def __enter__(self):
        self.callback(self.n, self.total)
        return self

    def __exit__(self, *args):
        return False

    def update(self, size):
        with self.lock:
            self.n += size
            self.callback(int(self.n), self.total)


def _progress_factory(**kwargs):
    callback = _callback.get()
    if callback is None or kwargs.get("_tqdm_bar") is not None:
        return _original_progress(**kwargs)
    return _Progress(callback, kwargs.get("initial", 0), kwargs.get("total"))


file_download._get_progress_bar_context = _progress_factory


def download_file(repo_id: str, filename: str, *, revision: str, local_dir, callback, force_download=False) -> str:
    token = _callback.set(callback)
    try:
        return hf_hub_download(repo_id, filename, revision=revision, local_dir=local_dir, force_download=force_download)
    finally:
        _callback.reset(token)
