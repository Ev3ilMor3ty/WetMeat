"""Black-box tests: protocol, search, clocks and multithreading; stdlib only."""

import argparse
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient

ENGINE = Path("build/aurora")


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.engine = UCIClient(ENGINE)
        self.engine.__enter__()

    def tearDown(self):
        self.engine.close()

    def test_handshake_and_starting_moves(self):
        self.assertTrue(any(line.startswith("id name Aurora") for line in self.engine.transcript))
        fen, moves = self.engine.inspect()
        self.assertEqual(len(moves), 20)
        self.assertIn("e2e4", moves)
        self.assertEqual(fen, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def test_fixed_depth_and_principal_variation(self):
        _, legal = self.engine.inspect()
        best, lines = self.engine.search("go depth 6")
        self.assertIn(best, legal)
        self.assertTrue(any(line.startswith("info depth 6 ") for line in lines))
        self.assertTrue(any(" pv " in line and " nodes " in line for line in lines))

    def test_stop_and_ready_during_search(self):
        self.engine.send("go infinite")
        self.engine.wait("info depth 3 ")
        started = time.monotonic()
        self.engine.ready()
        self.assertLess(time.monotonic() - started, 1.0)
        self.engine.send("stop")
        lines = self.engine.wait("bestmove ", timeout=2)
        self.assertNotEqual(lines[-1], "bestmove 0000")
        self.assertLess(time.monotonic() - started, 2.0)
        self.engine.ready()

    def test_movetime(self):
        self.engine.send("setoption name Move Overhead value 0")
        started = time.monotonic()
        best, _ = self.engine.search("go movetime 120")
        elapsed = time.monotonic() - started
        self.assertNotEqual(best, "0000")
        self.assertGreater(elapsed, 0.05)
        self.assertLess(elapsed, 1.0)

    def test_low_clock_and_node_limit(self):
        best, _ = self.engine.search("go wtime 1 btime 1 winc 0 binc 0")
        self.assertNotEqual(best, "0000")
        started = time.monotonic()
        best, _ = self.engine.search("go nodes 500")
        self.assertNotEqual(best, "0000")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_searchmoves(self):
        best, _ = self.engine.search("go searchmoves e2e4 depth 4")
        self.assertEqual(best, "e2e4")
        best, _ = self.engine.search("go depth 4 searchmoves d2d4 g1f3")
        self.assertIn(best, {"d2d4", "g1f3"})

    def test_mate_and_stalemate(self):
        self.engine.send("position fen 7k/6Q1/6K1/8/8/8/8/8 b - - 100 51")
        best, lines = self.engine.search("go depth 4")
        self.assertEqual(best, "0000")
        self.assertTrue(any("score mate 0" in line for line in lines))
        self.engine.send("position fen 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        best, lines = self.engine.search("go depth 4")
        self.assertEqual(best, "0000")
        self.assertTrue(any("score cp 0" in line for line in lines))

    def test_forced_mate(self):
        self.engine.send("position fen 2r3k1/5ppp/4p3/3pP3/3P4/2R2N2/5PPP/6K1 w - - 0 1")
        best, lines = self.engine.search("go mate 1")
        self.assertEqual(best, "c3c8")
        self.assertTrue(any("score mate 1" in line for line in lines))

    def test_invalid_position_is_transactional(self):
        self.engine.send("position startpos moves e2e4 e7e5")
        before, _ = self.engine.inspect()
        for command in ("position startpos moves e2e5", "position fen 8/8/8/8/8/8/8/8 w - - 0 1"):
            self.engine.send(command)
            self.engine.wait("info string Fehler:")
            after, _ = self.engine.inspect()
            self.assertEqual(before, after)

    def test_invalid_options_do_not_break_engine(self):
        for command in ("setoption name Threads value -1", "setoption name Hash value nonsense", "go depth -1", "go searchmoves e2e5"):
            self.engine.send(command)
            self.engine.wait("info string Fehler:")
        self.engine.ready()
        best, _ = self.engine.search("go depth 3")
        self.assertNotEqual(best, "0000")

    def test_hash_threads_and_repeated_searches(self):
        self.engine.send("setoption name Threads value 3")
        self.engine.send("setoption name Hash value 1")
        for _ in range(8):
            self.engine.send("setoption name Clear Hash")
            self.engine.send("position startpos moves e2e4 c7c5 g1f3")
            _, legal = self.engine.inspect()
            best, _ = self.engine.search("go depth 5")
            self.assertIn(best, legal)
        self.engine.send("ucinewgame")
        fen, moves = self.engine.inspect()
        self.assertTrue(fen.endswith("w KQkq - 0 1"))
        self.assertEqual(len(moves), 20)

    def test_ponderhit(self):
        self.engine.send("go ponder depth 3 wtime 1000 btime 1000")
        self.engine.wait("info depth 3 ")
        self.engine.ready()
        self.assertFalse(any(line.startswith("bestmove ") for line in self.engine.transcript))
        self.engine.send("ponderhit")
        self.assertNotEqual(self.engine.wait("bestmove ")[-1], "bestmove 0000")

    def test_ponder_node_limit_waits_for_hit(self):
        self.engine.send("go ponder nodes 512 wtime 1000 btime 1000")
        self.engine.wait("info depth 2 ")
        with self.assertRaises(TimeoutError):
            self.engine.wait("bestmove ", timeout=0.15)
        self.engine.ready()
        self.engine.send("ponderhit")
        self.assertNotEqual(self.engine.wait("bestmove ")[-1], "bestmove 0000")

    def test_infinite_node_limit_waits_for_stop(self):
        self.engine.send("go infinite nodes 512")
        self.engine.wait("info depth 2 ")
        with self.assertRaises(TimeoutError):
            self.engine.wait("bestmove ", timeout=0.15)
        self.engine.ready()
        self.engine.send("stop")
        self.assertNotEqual(self.engine.wait("bestmove ")[-1], "bestmove 0000")

    def test_perft_extension(self):
        self.engine.send("go perft 3")
        lines = self.engine.wait("info string nodes ")
        self.assertTrue(lines[-1].startswith("info string nodes 8902 "))

    def test_eof_and_cli(self):
        result = subprocess.run([str(ENGINE.resolve()), "--perft", "3"], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("nodes 8902 ", result.stdout)
        result = subprocess.run([str(ENGINE.resolve())], input="uci\nposition startpos\ngo infinite\n", text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn("uciok", result.stdout)
        self.assertIn("bestmove ", result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=ENGINE)
    args, remaining = parser.parse_known_args()
    ENGINE = args.engine
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
