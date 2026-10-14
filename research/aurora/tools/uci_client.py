"""Small, dependency-free UCI client for protocol tests."""

from __future__ import annotations

import queue
import subprocess
import threading
import time
from pathlib import Path


class UCIClient:
    def __init__(self, executable: str | Path, timeout: float = 10.0):
        self.timeout = timeout
        self.process = subprocess.Popen(
            [str(Path(executable).resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.transcript: list[str] = []
        self.errors: list[str] = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._read_errors, daemon=True)
        self.reader.start()
        self.error_reader.start()

    def _read(self):
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line.rstrip("\r\n"))
        self.lines.put(None)

    def _read_errors(self):
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.errors.append(line.rstrip("\r\n"))

    def send(self, line: str):
        if self.process.poll() is not None:
            raise RuntimeError(f"Engine exited ({self.process.returncode}): {self.errors[-10:]}")
        assert self.process.stdin is not None
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def wait(self, prefix: str, timeout: float | None = None) -> list[str]:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        received = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Waiting for {prefix!r}; output: {self.transcript[-20:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"Waiting for {prefix!r}; output: {self.transcript[-20:]}") from None
            if line is None:
                raise RuntimeError(f"Engine closed output ({self.process.poll()}): {self.errors[-10:]}")
            self.transcript.append(line)
            received.append(line)
            if line.startswith(prefix):
                return received

    def ready(self):
        self.send("isready")
        return self.wait("readyok")

    def inspect(self) -> tuple[str, set[str]]:
        self.send("d")
        lines = self.wait("info string legal")
        fen = next(line.removeprefix("info string fen ") for line in lines if line.startswith("info string fen "))
        legal = set(lines[-1].split()[3:])
        return fen, legal

    def search(self, command: str = "go depth 5") -> tuple[str, list[str]]:
        self.send(command)
        lines = self.wait("bestmove ")
        return lines[-1].split()[1], lines

    def close(self):
        if self.process.poll() is None:
            try:
                self.send("quit")
                self.process.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.error_reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        if self.process.returncode:
            raise RuntimeError(f"Engine failed ({self.process.returncode}): {self.errors[-20:]}")

    def __enter__(self):
        self.send("uci")
        self.wait("uciok")
        self.ready()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

