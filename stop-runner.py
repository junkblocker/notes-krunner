"""Stop all copies of this checkout's runner, including older queued copies."""

import os
import selectors
import signal
import sys
import time
from contextlib import ExitStack
from pathlib import Path


def stop_runner(path):
    expected = [b"/usr/bin/python3", os.fsencode(path), b""]
    with ExitStack() as descriptors, selectors.DefaultSelector() as exited:
        for process in Path("/proc").iterdir():
            if not process.name.isdecimal():
                continue
            command = process / "cmdline"
            try:
                if process.stat().st_uid != os.getuid() or command.read_bytes().split(b"\0") != expected:
                    continue
                # 2026-11-19: Pin the process before signaling so PID reuse is safe.
                descriptor = os.pidfd_open(int(process.name))
                descriptors.callback(os.close, descriptor)
                if command.read_bytes().split(b"\0") != expected:
                    continue
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                continue
            exited.register(descriptor, selectors.EVENT_READ)

        deadline = time.monotonic() + 3
        while exited.get_map():
            for key, _ in exited.select(max(0, deadline - time.monotonic())):
                exited.unregister(key.fd)
            if exited.get_map() and time.monotonic() >= deadline:
                raise SystemExit("Timed out waiting for the runner to stop.")


if __name__ == "__main__":
    stop_runner(Path(sys.argv[1]))
