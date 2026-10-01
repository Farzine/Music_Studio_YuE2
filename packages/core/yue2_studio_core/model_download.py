"""Download state and byte accounting, independent of Hugging Face or the UI."""
from .errors import ValidationError

ACTIVE_DOWNLOAD_STATES = {"queued", "downloading", "verifying", "registering"}
DOWNLOAD_DISK_RESERVE_BYTES = 2**30
_TRANSITIONS = {
    "queued": {"downloading", "failed"}, "downloading": {"verifying", "failed"},
    "verifying": {"registering", "failed"}, "registering": {"complete", "failed"},
    "failed": {"queued"}, "complete": set(),
}


def transition_download(job: dict, status: str) -> None:
    if status not in _TRANSITIONS.get(job["status"], set()):
        raise ValidationError(f"Invalid download transition: {job['status']} → {status}.")
    job["status"] = status


def download_progress(job: dict) -> dict:
    files = job.get("files") or []
    total = sum(f["bytes"] for f in files) if files and all(f.get("bytes") is not None for f in files) else None
    downloaded = sum(f.get("downloaded_bytes", 0) for f in files)
    current = next((f for f in files if f["name"] == job.get("current_file")), {})
    speed = job.get("bytes_per_second") if job["status"] == "downloading" else None
    percent = downloaded / total * 100 if total else None
    return dict(total_bytes=total, downloaded_bytes=downloaded, percentage=percent,
                current_file_bytes=current.get("downloaded_bytes", 0), current_file_total_bytes=current.get("bytes"),
                current_file_percentage=current.get("downloaded_bytes", 0) / current["bytes"] * 100 if current.get("bytes") else None,
                bytes_per_second=speed,
                eta_seconds=max(0, total - downloaded) / speed if total is not None and speed and speed > 0 else None)
