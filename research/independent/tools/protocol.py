"""Asynchronous UCI lifecycle checks. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import hashlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import chess


class Client:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.log = []
        def read():
            for line in self.process.stdout:
                self.lines.put(line.strip())
        threading.Thread(target=read, daemon=True).start()

    def send(self, command):
        self.log.append('> ' + command)
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()

    def until(self, prefix, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                break
            self.log.append('< ' + line)
            if line.startswith(prefix):
                return line
        raise AssertionError(f'Missing {prefix!r}: {self.log[-12:]}')

    def no_bestmove(self, seconds=.2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                return
            self.log.append('< ' + line)
            assert not line.startswith('bestmove'), self.log[-10:]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    c = Client(args.engine.resolve())
    cases = []
    try:
        c.send('uci'); c.until('uciok')
        c.send('isready'); c.until('readyok')
        for i in range(15):
            c.send('position startpos')
            c.send('go infinite nodes 1000')
            c.no_bestmove()
            c.send('isready'); c.until('readyok')
            started = time.monotonic()
            c.send('stop')
            line = c.until('bestmove')
            assert chess.Move.from_uci(line.split()[1]) in chess.Board().legal_moves
            assert time.monotonic() - started < .5
        cases.append('15 infinite+node-limit/stop/isready cycles')
        c.send('position startpos')
        c.send('go ponder depth 3 wtime 1000 btime 1000')
        c.no_bestmove()
        c.send('ponderhit'); c.until('bestmove')
        cases.append('ponder holds completed result until ponderhit')
        c.send('setoption name Hash value 8')
        c.send('ucinewgame')
        c.send('position startpos moves e2e4 e7e5 g1f3')
        c.send('go depth 4')
        line = c.until('bestmove')
        b = chess.Board()
        for move in ['e2e4', 'e7e5', 'g1f3']:
            b.push_uci(move)
        assert chess.Move.from_uci(line.split()[1]) in b.legal_moves
        cases.append('new game, hash resize, position history and depth search')
        c.send('position fen 7k/6Q1/5K2/8/8/8/8/8 b - - 100 1')
        c.send('go depth 4')
        assert c.until('bestmove') == 'bestmove 0000'
        cases.append('checkmate with halfmove clock 100')
        c.send('position startpos')
        c.send('go infinite')
        c.no_bestmove(.05)
        c.send('quit')
        c.process.wait(timeout=2)
        assert c.process.returncode == 0
        cases.append('quit during active search')
    finally:
        if c.process.poll() is None:
            c.process.kill()
            c.process.wait()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'status': 'passed', 'engine_sha256': hashlib.sha256(args.engine.read_bytes()).hexdigest(), 'cases': cases, 'log': c.log}, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'cases': cases}))


if __name__ == '__main__':
    main()
