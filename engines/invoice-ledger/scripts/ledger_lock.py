"""Windows OS-level lock spans read, validation and atomic save; crash releases the lock."""
from contextlib import contextmanager
from pathlib import Path
@contextmanager
def transaction_lock(directory,enabled=True):
    if not enabled:
        yield;return
    import msvcrt
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    with (root/'_transaction.lock').open('a+b') as f:
        f.seek(0,2)
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as e:raise RuntimeError('另一个进程正在修改台账，请稍后重试') from e
        try:yield
        finally:
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
