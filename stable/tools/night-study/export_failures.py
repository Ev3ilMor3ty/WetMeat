"""Export verified mistake positions with complete history; no searches. GPL-3.0-or-later."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import chess
import chess.pgn

from summarize_study import summarize
from verify_records import require, verify_audit, verify_game


def legal_pv(board, sequence):
    probe = board.copy(stack=True)
    for text in sequence:
        move = chess.Move.from_uci(text)
        require(move in probe.legal_moves, 'Illegal move in recorded judge PV')
        probe.push(move)
    return sequence


def extract(study, include_heldout=False, include_pilot=False):
    summary = summarize(study)
    phases = {'training'}
    if include_heldout:
        phases.add('heldout')
    if include_pilot:
        phases.add('pilot')
    cases = []
    coverage = {}
    for scored in summary['games']:
        if scored['phase'] not in phases or scored['points'] is None:
            continue
        path = Path(scored['file'])
        raw = path.read_bytes()
        record = json.loads(raw)
        with path.with_suffix('.pgn').open() as stream:
            game = chess.pgn.read_game(stream)
        played = verify_game(record, game)
        audit_path = path.parent / 'audit' / path.name
        rows = verify_audit(json.loads(audit_path.read_text()), raw, record, played) if audit_path.exists() else []
        coverage[str(path)] = {'phase': scored['phase'], 'variant': scored['variant'],
                               'own_moves': len(played), 'checked_moves': len(rows)}
        nodes = {node.ply(): node for node in game.mainline()}
        clocks = {'white': record['base_seconds'], 'black': record['base_seconds']}
        clocks_at_ply = {}
        for move in record['moves']:
            clocks_at_ply[move['ply']] = dict(clocks)
            clocks[move['color']] = move['clock_after_s']
        for row in rows:
            if row['category'] not in ('mistake', 'blunder'):
                continue
            board = nodes[row['ply']].parent.board()
            require(board.fen() == row['fen'], 'Historical replay differs from audited position')
            history = [move.uci() for move in board.move_stack]
            best = row['best_evaluation']
            chosen = row['played_evaluation']
            require(row['best'] != row['played'], 'Positive loss recorded for identical root moves')
            best_pv = legal_pv(board, best['pv'])
            played_pv = legal_pv(board, chosen['pv'])
            case_id = f"{path.parent.name}-{path.stem}-{scored['variant']}-ply{row['ply']}"
            original = played[row['ply']]
            cases.append({'id': case_id, 'game': str(path), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'audit': str(audit_path), 'phase': scored['phase'], 'variant': scored['variant'],
                'tested_binary_sha256': record['tested_binary_sha256'],
                'judge_binary_sha256': record['opponent_binary_sha256'],
                'tested_options': record.get('tested_options', {}),
                'hash_mb_each': record['hash_mb_each'], 'threads_each': record['threads_each'],
                'ply': row['ply'], 'fen': board.fen(), 'complete_history_uci': history,
                'uci_position_command': 'position startpos' + (' moves ' + ' '.join(history) if history else ''),
                'played': row['played'], 'judge_preferred': row['best'], 'category': row['category'],
                'estimated_loss_cp': row['loss_cp'], 'judge_best': best, 'judge_played': chosen,
                'judge_best_pv': best_pv, 'judge_played_pv': played_pv,
                'judge_wdl_expectation_loss': row.get('wdl_expectation_loss'),
                'oracle_depth_below_played': row.get('oracle_depth_below_played', False),
                'judge_budget_nodes_per_search': row['audit_budget_nodes_per_search'],
                'refined_budget_nodes_per_search': row.get('refined_budget_nodes_per_search'),
                'original_search_nodes': original['nodes'], 'original_search_depth': original['depth'],
                'original_elapsed_s': original['elapsed_s'], 'clocks_before_s': clocks_at_ply[row['ply']],
                'increment_seconds': record['increment_seconds'],
                'failure_cause': 'unassigned; investigate before changing engine code',
                'fresh_heldout_required_if_used_for_tuning': scored['phase'] == 'heldout'})
    return {'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'study': str(study),
            'selected_phases': sorted(phases), 'coverage': coverage, 'cases': cases,
            'contains_heldout_failures': any(case['phase'] == 'heldout' for case in cases),
            'limitations': ['No exported cases does not mean an incomplete audit found no errors.',
                           'Finite Stockfish-family estimates are not perfect ground truth.',
                           'Use complete history: a FEN alone loses repetitions.',
                           'Cold position replays differ from warm actual games and cannot certify Elo or match gains.',
                           'A move-loss estimate alone does not identify timing, evaluation or search as the cause.',
                           'If heldout failures inform code changes, use fresh heldout validation.']}


def diagnostic_pgn(case):
    board = chess.Board()
    for text in case['complete_history_uci']:
        board.push_uci(text)
    require(board.fen() == case['fen'], 'Exported full history does not reproduce FEN')
    game = chess.pgn.Game.from_board(board)
    game.headers.update(Event='WetMeat finite-audit diagnostic', Site='local',
                        Result='*', Termination='UNSCORED_DIAGNOSTIC', StudyPhase=case['phase'],
                        CaseId=case['id'])
    node = game.end()
    node.comment = (f"{case['category']}; estimated loss {case['estimated_loss_cp']} cp; "
                    f"original depth {case['original_search_depth']}, judge depth {case['judge_best']['depth']}. "
                    'Diagnostic only; full prefix history retained.')
    for label, sequence in [('Judge preferred', case['judge_best_pv']), ('Played move', case['judge_played_pv'])]:
        variation = node
        for index, text in enumerate(sequence):
            variation = variation.add_variation(chess.Move.from_uci(text))
            if index == 0:
                variation.comment = label
    return str(game)


def save(report, output):
    output.mkdir(parents=True, exist_ok=True)
    epd = []
    pgn = []
    for case in report['cases']:
        board = chess.Board(case['fen'])
        epd.append(board.epd(id=case['id'], bm=[chess.Move.from_uci(case['judge_preferred'])],
                            am=[chess.Move.from_uci(case['played'])], ce=case['estimated_loss_cp'],
                            hmvc=board.halfmove_clock, fmvn=board.fullmove_number))
        pgn.append(diagnostic_pgn(case))
    for name, contents in [('cases.json', json.dumps(report, indent=2) + '\n'),
                           ('diagnostics.pgn', '\n\n'.join(pgn) + ('\n' if pgn else '')),
                           ('positions.epd', '\n'.join(epd) + ('\n' if epd else ''))]:
        path = output / name
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(contents)
        temporary.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--include-heldout', action='store_true', help='Label these positions as requiring fresh validation if used to tune')
    p.add_argument('--include-pilot', action='store_true')
    args = p.parse_args()
    study, output = args.study.resolve(), args.output.resolve()
    require(output != study and not output.is_relative_to(study), 'Review output must be outside the frozen study')
    report = extract(study, args.include_heldout, args.include_pilot)
    save(report, output)
    print(json.dumps({'status': 'exported', 'positions': len(report['cases']),
                      'selected_phases': report['selected_phases'], 'coverage': report['coverage'],
                      'contains_heldout_failures': report['contains_heldout_failures'], 'engine_searches': 0}))


if __name__ == '__main__':
    main()
