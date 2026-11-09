"""Client for one long-lived Django process in the web container.

Booting Django per `docker exec ... manage.py` costs 230 to 500ms; this keeps
a single process (django_shell_server.py) per pytest process and sends it
management commands and code snippets over stdin, one JSON line each.
"""
import atexit
import json
import os
import select
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

_SERVER_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "django_shell_server.py")
_START_TIMEOUT = 60


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


class DjangoShell:
    def __init__(self, container: str):
        self.container = container
        self._proc = None
        self._buffer = b""
        self._lock = threading.Lock()
        self._log = tempfile.TemporaryFile()
        atexit.register(self.stop)

    def request(self, *, argv: list = None, code: str = None, timeout: float = 60) -> Result:
        """Run a management command (argv as after `manage.py`) or a code snippet.

        @param argv    command name and arguments, e.g. ["delete_user", email, "--yes"]
        @param code    Python source run in a fresh namespace, alternative to argv
        @param timeout seconds before the process is killed and TimeoutExpired is raised
        @return Result with the CLI-like returncode and the captured stdout and stderr
        """
        payload = {"argv": list(argv)} if argv is not None else {"code": code}
        with self._lock:
            if not self._alive():
                self._start()
            try:
                self._send(payload)
            except (BrokenPipeError, OSError):
                self._start()
                self._send(payload)
            try:
                reply = self._read_line(timeout)
            except subprocess.TimeoutExpired:
                self.stop()
                raise
            if reply is None:
                log = self._log_tail()
                self.stop()
                return Result(1, "", f"Django shell process died:\n{log}")
            return Result(**json.loads(reply))

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self._buffer = b""
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        self.stop()
        with open(_SERVER_SOURCE) as f:
            source = f.read()
        self._log.seek(0)
        self._log.truncate()
        self._proc = subprocess.Popen(
            ["docker", "exec", "-i", self.container, "python", "-c", source],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log, bufsize=0,
        )
        try:
            ready = self._read_line(_START_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.stop()
            raise
        if ready is None:
            log = self._log_tail()
            self.stop()
            raise RuntimeError(f"Django shell process failed to start:\n{log}")

    def _send(self, payload: dict) -> None:
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())

    def _read_line(self, timeout: float):
        """Next reply line, None on EOF; raises TimeoutExpired."""
        deadline = time.monotonic() + timeout
        fd = self._proc.stdout.fileno()
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("django shell", timeout)
            if not select.select([fd], [], [], remaining)[0]:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                return None
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode()

    def _log_tail(self) -> str:
        self._log.seek(0)
        return self._log.read()[-4000:].decode(errors="replace")
