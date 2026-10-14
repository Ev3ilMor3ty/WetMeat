"""Create an offline, interactive report from real timed games and audits.

SPDX-License-Identifier: GPL-3.0-or-later.
"""
import argparse
import json
from pathlib import Path

import chess
import chess.pgn
import chess.svg


def main():
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=project/'results/rapid-study')
    parser.add_argument('--output', type=Path, default=project.parent/'wetmeat-rapid-study.html')
    args = parser.parse_args()
    games = []
    totals = {}
    for stage in ('training','validation'):
        for path in sorted((args.study/stage).glob('game-*.json')):
            record = json.loads(path.read_text())
            audit_path = args.study/(stage+'-audit')/path.name
            audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
            audited = {row['ply']: row for row in audit['moves']} if audit else {}
            with path.with_suffix('.pgn').open() as stream:
                pgn = chess.pgn.read_game(stream)
            assert pgn and not pgn.errors
            board = pgn.board()
            clocks = {'white':record['base_seconds'],'black':record['base_seconds']}
            played = {row['ply']:row for row in record['moves']}
            frames = []
            def snapshot(move=None,san=None):
                ply = len(board.move_stack)
                frames.append({'pieces':{chess.square_name(s):p.symbol() for s,p in board.piece_map().items()},
                               'fen':board.fen(),'san':san,'uci':move.uci() if move else None,
                               'check':chess.square_name(board.king(board.turn)) if board.is_check() else None,
                               'clocks':dict(clocks),'audit':audited.get(ply),
                               'book':0<ply<=int(pgn.headers['OpeningPlies'])})
            snapshot()
            for move in pgn.mainline_moves():
                assert move in board.legal_moves
                san=board.san(move)
                board.push(move)
                if len(board.move_stack) in played:
                    row=played[len(board.move_stack)]
                    clocks[row['color']]=row['clock_after_s']
                    if row['tested']:
                        stats=totals.setdefault(row['engine'],{'moves':0,'audited':0,'mistakes':0,'blunders':0,'loss_cp_sum':0})
                        stats['moves']+=1
                        inspected=audited.get(row['ply'])
                        if inspected:
                            stats['audited']+=1
                            stats['mistakes']+=inspected['category']=='mistake'
                            stats['blunders']+=inspected['category']=='blunder'
                            stats['loss_cp_sum']+=inspected['loss_cp']
                snapshot(move,san)
            assert board.fen()==record['final_fen']
            if record['termination']=='TIME_FORFEIT':
                frames[-1]['clocks']={'white':record['final_clocks_s']['True'],
                                     'black':record['final_clocks_s']['False']}
            games.append({'stage':stage,'variant':record.get('variant','baseline'),
                          'round':record['round'],'headers':record['headers'],'result':record['result'],
                          'termination':record['termination'],'frames':frames,
                          'pgn':path.with_suffix('.pgn').read_text(),'source':str(path),
                          'tested_sha':record['tested_binary_sha256'],'opponent_sha':record['opponent_binary_sha256']})
    validation_path=args.study/'validation/summary.json'
    decision=args.study/'decision.json'
    report={'games':games,'rates':totals,
            'validation':json.loads(validation_path.read_text()) if validation_path.exists() else None,
            'decision':json.loads(decision.read_text()) if decision.exists() else None,
            'protocol':json.loads((args.study/'protocol.json').read_text()),
            'pieces':{s:chess.svg.piece(chess.Piece.from_symbol(s)) for s in 'KQRBNPkqrbnp'}}
    template=Path(__file__).with_name('study.template.html').read_text()
    embedded=json.dumps(report,ensure_ascii=False).replace('<','\\u003c')
    args.output.write_text(template.replace('__STUDY_DATA__',embedded))
    args.output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'report':str(args.output),'games':len(games),'rates':totals}))


if __name__=='__main__':
    main()
