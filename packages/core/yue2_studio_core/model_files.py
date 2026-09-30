"""File leases coordinate model consumers and deletion without CUDA imports."""
from contextlib import ExitStack, contextmanager
import hashlib
from pathlib import Path

from .store import Store, file_lock


@contextmanager
def model_file_leases(store: Store, references: list[str], *, shared: bool = True, blocking: bool = True):
    # Sorted acquisition avoids deadlocks when model/VAE pairs share directories.
    paths = sorted({str(Path(ref).resolve()) for ref in references if Path(ref).is_absolute() or Path(ref).is_dir()})
    with ExitStack() as stack:
        for path in paths:
            key = hashlib.sha256(path.encode()).hexdigest()
            stack.enter_context(file_lock(store.root / "model-files" / f"{key}.lock", shared=shared, blocking=blocking))
        yield
