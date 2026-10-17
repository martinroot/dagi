import os
import stat

import pytest

from dagi_core.runtime import RuntimeLease


def test_runtime_lease_is_exclusive_until_closed(tmp_path):
    home = tmp_path / "dagi-home"
    first = RuntimeLease(home)
    try:
        with pytest.raises(ValueError, match="another Dagi runtime"):
            RuntimeLease(home)
    finally:
        first.close()

    second = RuntimeLease(home)
    second.close()


def test_runtime_lock_file_is_owner_only_on_posix(tmp_path):
    lease = RuntimeLease(tmp_path / "dagi-home")
    try:
        if os.name == "posix":
            assert stat.S_IMODE(lease.path.stat().st_mode) == 0o600
    finally:
        lease.close()
