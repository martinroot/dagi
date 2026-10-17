"""Exclusive process ownership for one Dagi home directory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class RuntimeLease:
    """Hold an OS file lock while this process owns an application's state."""

    def __init__(self, home: Path):
        home = Path(home).expanduser()
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = home / "runtime.lock"
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(self.path, 0o600)
            self.file: BinaryIO = os.fdopen(descriptor, "r+b")
            self.file.seek(0, os.SEEK_END)
            if self.file.tell() == 0:
                self.file.write(b"\0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            try:
                self.file.close()
            except (AttributeError, OSError):
                os.close(descriptor)
            raise ValueError(
                "another Dagi runtime owns this DAGI_HOME; use its API or a different home"
            ) from exc

    def close(self) -> None:
        if self.file.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
