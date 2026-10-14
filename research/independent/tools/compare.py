"""Same-position timed replay of training errors. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--judge', type=Path, required=True)
    p.add_argument('--games', type=Path, required=True)
    p.add_argument('--audits', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=.1)
    args = p.parse_args()
    # Isolate sequential, equally timed searches from host CPU migration.
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    engines = [chess.engine.SimpleEngine.popen_uci(str(path.resolve()), timeout=60)
               for path in (args.baseline, args.candidate, args.judge)]
    rows = []
    try:
        for engine in engines:
            engine.configure({'Threads': 1, 'Hash': 128, 'Move Overhead': 0})
        for file in sorted(args.audits.glob('game-*.json')):
            audit = json.loads(file.read_text())
            assert audit['status'] == 'completed'
            with (args.games / file.with_suffix('.pgn').name).open() as stream:
                game = chess.pgn.read_game(stream)
            positions = {node.ply() + 1: node.board() for node in [game, *game.mainline()]}
            chosen = [row for row in audit['moves'] if row['loss_cp'] >= 50]
            chosen += sorted([row for row in audit['moves'] if row['loss_cp'] < 50], key=lambda r: r['ply'])[:3]
            for item in chosen:
                board = positions[item['ply']]
                assert board.fen() == item['fen']
                answers = {}
                order = [0, 1] if len(rows) % 2 == 0 else [1, 0]
                for slot in order:
                    engine = engines[slot]
                    engine.configure({'Clear Hash': None})
                    started = time.monotonic()
                    result = engine.play(board, chess.engine.Limit(time=args.seconds), game=object(), info=chess.engine.INFO_ALL)
                    assert result.move in board.legal_moves
                    answers['baseline' if slot == 0 else 'candidate'] = {
                        'move': result.move.uci(), 'depth': result.info.get('depth'),
                        'nodes': result.info.get('nodes'), 'elapsed_s': time.monotonic() - started}
                judge = engines[2]
                judge.configure({'Clear Hash': None})
                reference = judge.analyse(board, chess.engine.Limit(nodes=1000000), game=object())['pv'][0]
                roots = {reference, *(chess.Move.from_uci(a['move']) for a in answers.values())}
                values = {move: {} for move in roots}
                if len(roots) == 1:
                    loss = {key: 0 for key in answers}
                    common_depth = None
                else:
                    judge.configure({'Clear Hash': None})
                    with judge.analysis(board, chess.engine.Limit(nodes=2000000 * len(roots)),
                                        multipv=len(roots), root_moves=list(sorted(roots, key=lambda m: m.uci())), game=object()) as analysis:
                        for info in analysis:
                            if not info.get('pv') or 'score' not in info or 'depth' not in info:
                                continue
                            if info.get('lowerbound') or info.get('upperbound'):
                                continue
                            move = info['pv'][0]
                            if move in values:
                                score = info['score'].pov(board.turn)
                                cp = score.score()
                                if cp is None:
                                    cp = 10000 if score.score(mate_score=10000) > 0 else -10000
                                values[move][info['depth']] = cp
                    depths = set.intersection(*(set(v) for v in values.values()))
                    assert depths, ('no common completed depth', board.fen())
                    common_depth = max(depths)
                    best = max(v[common_depth] for v in values.values())
                    loss = {name: max(0, best - values[chess.Move.from_uci(answer['move'])][common_depth])
                            for name, answer in answers.items()}
                row = {'game': file.name, 'ply': item['ply'], 'fen': board.fen(),
                       'training_error_cp': item['loss_cp'], 'judge_reference': reference.uci(),
                       'comparison_depth': common_depth, 'answers': answers, 'loss_cp': loss}
                rows.append(row)
                print(f"{file.stem} ply {item['ply']}: baseline {loss['baseline']}cp, candidate {loss['candidate']}cp", flush=True)
                args.output.write_text(json.dumps({'status': 'running', 'rows': rows}, indent=2) + '\n')
    finally:
        for engine in engines:
            engine.quit()
    totals = {name: {'sum_loss_cp': sum(r['loss_cp'][name] for r in rows),
                     'mistakes': sum(50 <= r['loss_cp'][name] < 200 for r in rows),
                     'blunders': sum(r['loss_cp'][name] >= 200 for r in rows),
                     'median_reported_nodes': sorted(r['answers'][name]['nodes'] or 0 for r in rows)[len(rows)//2]}
              for name in ('baseline', 'candidate')}
    report = {'status': 'completed', 'positions': len(rows), 'search_seconds_each': args.seconds,
              'sha256': {name: fingerprint(path) for name, path in [('baseline', args.baseline), ('candidate', args.candidate), ('judge', args.judge)]},
              'totals': totals, 'rows': rows,
              'limitations': 'Training-position replay only. Finite common-depth judge. Selected errors plus three control moves per game; not an unbiased error rate or proof of stronger match play.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(totals))


if __name__ == '__main__':
    main()
