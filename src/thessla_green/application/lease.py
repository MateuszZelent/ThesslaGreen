"""Process-level ownership lease for one Modbus endpoint."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from thessla_green.domain.models import TransportEndpoint


class EndpointLeaseBusy(RuntimeError):
    """Raised when another local process already owns the endpoint lease."""


class EndpointLease:
    """Hold a recoverable OS lock for the lifetime of one gateway.

    The lock file is intentionally not deleted: the advisory lock belongs to
    the open descriptor and is released by the OS when the process exits. A
    stable filename lets every gateway instance contend for the same endpoint
    without putting a lock file next to a user-owned serial device.
    """

    def __init__(self, endpoint: TransportEndpoint, *, directory: str | Path | None = None) -> None:
        digest = hashlib.sha256(endpoint.key.encode("utf-8")).hexdigest()[:24]
        root = Path(directory) if directory is not None else Path(tempfile.gettempdir())
        self.path = root / f"thessla-green-{digest}.lock"
        self.endpoint = endpoint
        self._descriptor: int | None = None

    @property
    def acquired(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> None:
        if self._descriptor is not None:
            return
        if os.name != "posix":
            # The supported deployment targets are POSIX hosts. Keep the
            # gateway usable on other platforms; their serial driver remains
            # responsible for any native exclusivity mechanism.
            self._descriptor = -1
            return

        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise EndpointLeaseBusy(
                f"endpoint is already owned by another local gateway: {self.endpoint.key}"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None or descriptor < 0:
            return
        if os.name == "posix":
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
