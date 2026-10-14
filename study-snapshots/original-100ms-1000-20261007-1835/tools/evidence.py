"""Verify and compare BOTH engines in the new fixed-time study. GPL-3.0-or-later."""
import argparse
import datetime as dt
import math
from pathlib import Path

import chess
import chess.pgn

from common import DRAW_RULE, adjudicated_outcome, digest, game_config, load, require, verify_audit, write


def verify_fixed_game(record, pgn_path, config):
    with Path(pgn_path).open() as stream:
        game = chess.pgn.read_game(stream)
    require(game is not None and not game.errors, 'Invalid PGN')
    expected = {'schema': 'fixed-movetime-v1', 'phase': config['phase'], 'variant': config['variant'],
                'round': config['round'], 'pair': config['pair'], 'opening': config['opening'],
                'tested_binary_sha256': config['tested_sha'], 'opponent_binary_sha256': config['opponent_sha'],
                'requested_movetime_ms': config['movetime_ms'], 'cpu': config['cpu'], 'threads_each': 1,
                'hash_mb_each': config['common_uci']['Hash'], 'move_overhead_ms_each': config['common_uci']['Move Overhead'],
                'max_plies': config['max_plies'], 'tested_options': config['options'], 'draw_rule': DRAW_RULE,
                'tested_color': 'white' if config['tested_color'] else 'black'}
    require(all(record.get(k) == v for k, v in expected.items()), 'Frozen game identity/resources/options differ')
    require(game.headers['Result'] == record['result'] and game.headers['Termination'] == record['termination'],
            'PGN/result mismatch')
    require(game.headers.get('FixedMoveTimeMS') == str(config['movetime_ms']), 'Wrong PGN move limit')
    require(game.headers.get('TimeControl')==f"{config['movetime_ms']}ms/move" and
            game.headers.get('Round')==str(config['round']) and game.headers.get('OpeningPair')==str(config['pair']),
            'Wrong PGN time control or paired game identity')
    require(game.headers.get('CPU') == str(config['cpu']) and game.headers.get('StudyPhase') == config['phase'],
            'Wrong PGN CPU/phase')
    require(game.headers.get('DrawRule') == DRAW_RULE, 'Wrong PGN draw policy')
    for side in ('tested_uci_settings', 'opponent_uci_settings'):
        require(all(record[side].get(k) == v for k, v in config['common_uci'].items()),
                'Applied full-strength settings/resources differ')
        require(record[side].get('Ponder') is False, 'Ponder must be off')
    board = game.board()
    require(board.fen() == chess.STARTING_FEN, 'Unexpected start position')
    opening = config['opening'].split()
    nodes = list(game.mainline())
    require(len(nodes) == record['plies'] == len(opening) + len(record['moves']), 'Missing/duplicate recorded ply')
    require([n.move.uci() for n in nodes[:len(opening)]] == opening, 'Opening history differs')
    for text in opening:
        board.push_uci(text)
    history = opening.copy()
    positions = {'wetmeat': [], 'stockfish': []}
    for row, node in zip(record['moves'], nodes[len(opening):]):
        side = 'wetmeat' if board.turn == config['tested_color'] else 'stockfish'
        positions[side].append('position startpos' + (' moves ' + ' '.join(history) if history else ''))
        require(row['ply'] == board.ply() + 1 and row['color'] == ('white' if board.turn else 'black'), 'Move ordering differs')
        require(type(row['tested']) is bool and row['tested'] == (side == 'wetmeat'), 'Wrong engine owner')
        require(row['engine'] == game.headers['White' if board.turn else 'Black'], 'Wrong recorded engine')
        require(row['fen_before'] == board.fen() and row['uci'] == node.move.uci() and node.move in board.legal_moves,
                'Illegal/different recorded move or position')
        require(row['san'] == board.san(node.move), 'SAN differs')
        require(row['requested_movetime_ms'] == config['movetime_ms'], 'Move received a different limit')
        require(isinstance(row['elapsed_s'], (float, int)) and math.isfinite(row['elapsed_s']) and row['elapsed_s'] >= 0,
                'Invalid measured wall time')
        require(node.emt() is not None and abs(node.emt() - row['elapsed_s']) <= .00051, 'PGN elapsed time differs')
        require(row['clock_before_s'] == config['movetime_ms'] / 1000, 'Wrong per-move budget metadata')
        if row['reported_search_s'] is not None:
            require(row['reported_search_s'] >= 0 and math.isfinite(row['reported_search_s']), 'Invalid search time')
        history.append(row['uci'])
        board.push(node.move)
    require(board.fen() == record['final_fen'], 'Final board differs')
    outcome = adjudicated_outcome(board)
    if record['engine_error']:
        require(record['termination'] in ('ENGINE_ERROR', 'ILLEGAL_MOVE_FORFEIT') and outcome is None, 'Invalid engine fault')
        text = '1/2-1/2' if board.has_insufficient_material(not board.turn) else '0-1' if board.turn else '1-0'
        require(record['result'] == text, 'Fault awarded to wrong side')
        side = 'wetmeat' if board.turn == config['tested_color'] else 'stockfish'
        positions[side].append('position startpos' + (' moves ' + ' '.join(history) if history else ''))
    elif record['result'] == '*':
        require(outcome is None and board.ply() >= config['max_plies'] and record['termination'] == 'UNFINISHED_PLY_CAP',
                'Incorrect incomplete game')
    else:
        require(outcome is not None and outcome.result() == record['result'] and outcome.termination.name == record['termination'],
                'Incorrect natural outcome')
    points = None if record['result'] == '*' else .5 if record['result'] == '1/2-1/2' else int((record['result'] == '1-0') == config['tested_color'])
    require(points == record['tested_points'], 'Wrong score conversion')
    for side, expected_positions in positions.items():
        trace = record['sent_uci'][side]
        require([line for line in trace if line.startswith('position ')] == expected_positions, 'Engine did not receive exact full history')
        require([line for line in trace if line.startswith('go')] == [f"go movetime {config['movetime_ms']}"] * len(expected_positions),
                'Wrong UCI search limits, nodes/depth limit or ponder search')
    return {row['ply']: row for row in record['moves']}


def config_for_record(plan, record, path):
    config = game_config(plan, record['pair'])
    white = record['tested_color'] == 'white'
    config.update(round=2 * record['pair'] - int(white), tested_color=white,
                  cpu=((record['pair'] - 1) % 2) ^ int(not white), output=str(path.with_suffix('')))
    return config


def verify_both_audit(audit, path, record, moves, plan, verify_pvs=True):
    require(audit['settings'] == plan['audit_settings'], 'Audit budget/method changed')
    require(audit.get('scope') == 'both-engines' or audit['status'] == 'running', 'Opponent audit missing')
    rows = verify_audit(audit, path.read_bytes(), record, moves)
    require(len(rows) == len(audit['moves']), 'Audit contains unknown move')
    for row in rows:
        require(row['engine'] == moves[row['ply']]['engine'], 'Wrong audited engine label')
        if verify_pvs and not row.get('forced_only_move'):
            for key in ('best_evaluation', 'played_evaluation'):
                board = chess.Board(row['fen'])
                for text in row[key]['pv']:
                    move = chess.Move.from_uci(text)
                    require(move in board.legal_moves, 'Illegal judge principal variation')
                    board.push(move)
    return rows


def empty_stats():
    return {'moves': 0, 'checked_moves': 0, 'mistakes': 0, 'blunders': 0,
            'shallow_judge_moves': 0, 'loss_cp_sum': 0, 'elapsed_s_sum': 0,
            'reported_search_s_sum': 0, 'reported_search_moves': 0}


def batch_evidence(plan, directory, require_complete=False, light=False):
    totals = {'wetmeat': empty_stats(), 'stockfish': empty_stats()}
    wins = draws = losses = incomplete = faults = 0
    manifests, failures, pair_rows = [], [], {}
    paths = sorted(Path(directory).glob('game-*.json'))
    if require_complete:
        require(len(paths) == 2 * plan['pairs_per_batch'], 'Batch has missing games')
    rounds = set()
    for path in paths:
        record = load(path)
        require(path.stem==f"game-{record['round']:04d}",'Filename/game identity differs')
        if Path(directory).name.startswith('batch-'):
            index=int(Path(directory).name.removeprefix('batch-'))
            require((index-1)*plan['pairs_per_batch']<record['pair']<=index*plan['pairs_per_batch'],
                    'Game belongs to a different frozen batch')
        require(record['round'] not in rounds, 'Duplicate game')
        rounds.add(record['round'])
        config=config_for_record(plan,record,path)
        if light:
            for key, expected in {'tested_binary_sha256':config['tested_sha'],
                'opponent_binary_sha256':config['opponent_sha'],'phase':'training','variant':'baseline',
                'requested_movetime_ms':100,'cpu':config['cpu'],'opening':config['opening'],
                'round':config['round'],'tested_options':{},'threads_each':1,'hash_mb_each':128}.items():
                require(record.get(key)==expected,'Live metadata identity/resources differ: '+key)
            for side in ('tested_uci_settings','opponent_uci_settings'):
                require(all(record[side].get(k)==v for k,v in plan['common_uci'].items()) and record[side].get('Ponder') is False,
                        'Live full-strength settings differ')
            moves={row['ply']:row for row in record['moves']}
            require(len(moves)==len(record['moves']),'Duplicate live ply')
        else:
            moves = verify_fixed_game(record, path.with_suffix('.pgn'), config)
        if record['tested_points'] is None:
            incomplete += 1
            continue
        faults += bool(record['engine_error'])
        wins += record['tested_points'] == 1
        draws += record['tested_points'] == .5
        losses += record['tested_points'] == 0
        pair = pair_rows.setdefault(str(record['pair']), {'wetmeat': empty_stats(), 'stockfish': empty_stats(),
                                                       'points': 0, 'wins': 0, 'draws': 0, 'losses': 0, 'games': 0})
        pair['games'] += 1; pair['points'] += record['tested_points']
        pair['wins'] += record['tested_points'] == 1; pair['draws'] += record['tested_points'] == .5; pair['losses'] += record['tested_points'] == 0
        audit_path = path.parent / 'audit' / path.name
        rows, complete = [], False
        if audit_path.exists():
            audit = load(audit_path)
            rows = verify_both_audit(audit, path, record, moves, plan,verify_pvs=not light)
            complete = audit['status'] == 'completed' and len(rows) == len(moves)
        if require_complete:
            require(complete, 'Incomplete BOTH-engine move audit')
        for row in record['moves']:
            side = 'wetmeat' if row['tested'] else 'stockfish'
            for stats in (totals[side], pair[side]):
                stats['moves'] += 1; stats['elapsed_s_sum'] += row['elapsed_s']
                if row['reported_search_s'] is not None:
                    stats['reported_search_s_sum'] += row['reported_search_s']; stats['reported_search_moves'] += 1
        for row in rows:
            side = 'wetmeat' if row['tested'] else 'stockfish'
            for stats in (totals[side], pair[side]):
                stats['checked_moves'] += 1; stats['mistakes'] += row['category'] == 'mistake'
                stats['blunders'] += row['category'] == 'blunder'; stats['loss_cp_sum'] += row['loss_cp']
                stats['shallow_judge_moves'] += row.get('oracle_depth_below_played', False)
            if not light and row['category'] != 'acceptable':
                before = record['opening'].split() + [m['uci'] for m in record['moves'] if m['ply'] < row['ply']]
                failures.append({'engine_role': side, 'phase': 'training', 'file': str(path),
                    'game_sha256': digest(path), 'binary_sha256': record['tested_binary_sha256'] if row['tested'] else record['opponent_binary_sha256'],
                    'full_uci_history_before_move': before, 'original': moves[row['ply']], 'judge_evidence': row,
                    'options': record['tested_uci_settings'] if row['tested'] else record['opponent_uci_settings'],
                    'audit_settings': plan['audit_settings'], 'limited_finite_judge': True})
        manifests.append({'game': str(path), 'game_sha256': digest(path), 'pgn_sha256': digest(path.with_suffix('.pgn')),
                          'audit_sha256': digest(audit_path) if audit_path.exists() else None, 'audit_complete': complete})
    coverage = bool(paths) and incomplete == 0 and all(x['audit_complete'] for x in manifests)
    for stats in totals.values():
        stats['mistake_rate'] = stats['mistakes'] / stats['moves'] if coverage and stats['moves'] else None
        stats['blunder_rate'] = stats['blunders'] / stats['moves'] if coverage and stats['moves'] else None
    return {'schema': 'both-engine-batch-v1', 'snapshot_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'phase': 'training', 'requested_movetime_ms': plan['movetime_ms'],
            'stable_sha256': plan['stable_sha256'], 'opponent_sha256': plan['opponent_sha256'],
            'common_uci': plan['common_uci'], 'audit_settings': plan['audit_settings'],
            'completed_games': wins + draws + losses, 'wins': wins, 'draws': draws, 'losses': losses,
            'incomplete_games_excluded': incomplete, 'engine_faults': faults,
            'audit_complete': coverage, 'by_engine': totals, 'by_pair': pair_rows, 'files': manifests,
            'training_failures': failures, 'candidate_adopted': False}


def progress(plan):
    totals = {'wetmeat': empty_stats(), 'stockfish': empty_stats()}
    wins = draws = losses = incomplete = faults = 0
    complete = True
    completed_batches = 0
    for directory in sorted((Path(plan['output']) / 'training').glob('batch-*')):
        manifest = directory / 'batch-evidence.json'
        if manifest.exists():
            checksum = load(directory / 'batch-evidence-ready.json')
            require(digest(manifest) == checksum['sha256'], 'Completed batch evidence changed')
            data = load(manifest)
            require(data['audit_complete'], 'Completed batch has incomplete audit')
            for key in ('stable_sha256','opponent_sha256','common_uci','audit_settings'):
                require(data[key] == plan[key], 'Batch evidence configuration differs')
            completed_batches += 1
        else:
            # Active phases use only small metadata/common-depth checks. Full
            # PGN and legal-PV verification happens after all searches exit.
            data = batch_evidence(plan, directory,light=True)
        wins += data['wins']; draws += data['draws']; losses += data['losses']
        incomplete += data['incomplete_games_excluded']; faults += data['engine_faults']
        if data['completed_games'] or data['incomplete_games_excluded']:
            complete &= data['audit_complete']
        for side, stats in totals.items():
            for key in empty_stats():
                stats[key] += data['by_engine'][side][key]
    games = wins + draws + losses
    for stats in totals.values():
        stats['mistake_rate'] = stats['mistakes'] / stats['moves'] if complete and stats['moves'] else None
        stats['blunder_rate'] = stats['blunders'] / stats['moves'] if complete and stats['moves'] else None
    return {'snapshot_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'planned_games': plan['games'],
            'completed_games': games, 'wins': wins, 'draws': draws, 'losses': losses,
            'completed_audited_batches': completed_batches, 'incomplete_games_excluded': incomplete,
            'engine_faults': faults, 'audit_complete': complete and games > 0, 'by_engine': totals,
            'full_1000_game_study_complete': games == plan['games'] and complete and incomplete == 0,
            'candidate_adopted': False,
            'limits': 'Finite Stockfish-family common-depth judge; possible shared-family bias. Book pairs and moves are correlated. Rates need full current coverage. Training results are not validation of tuned code, superiority, calibrated Elo or perfect play.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--batch', type=Path)
    args = parser.parse_args()
    plan = load(args.plan)
    if args.batch:
        data = batch_evidence(plan, args.batch, require_complete=True)
        write(args.batch / 'training-failures.json', data['training_failures'])
        require(data['engine_faults'] == 0 and data['incomplete_games_excluded'] == 0, 'Fault/unfinished batch preserved; review required')
        data.pop('training_failures')
        write(args.batch / 'batch-evidence.json', data)
        write(args.batch / 'batch-evidence-ready.json', {'sha256': digest(args.batch / 'batch-evidence.json')})
    data = progress(plan)
    write(Path(plan['output']) / 'measured-results.json', data)
    lines = ['# WetMeat versus Stockfish19:100milliseconds per move', '',
             f"Completed: {data['completed_games']}/{plan['games']}; WetMeat W/D/L {data['wins']}/{data['draws']}/{data['losses']}.", '',
             '| Engine | Moves checked/total | Mistakes | Blunders | Shallower judge comparisons |',
             '|---|---|---|---|---|']
    for side, stats in data['by_engine'].items():
        lines.append(f"| {side} | {stats['checked_moves']}/{stats['moves']} | {stats['mistakes']} | {stats['blunders']} | {stats['shallow_judge_moves']} |")
    lines.extend(['', 'Both engines use go movetime100, full skill20, one thread,128MB hash, no ponder/Elo limit/tablebases. '
                  'Book plies are excluded; mistake50..199cp and blunder>=200cp. Interrupted games are excluded and never resumed.', '',
                  'This is the unchanged stable baseline TRAINING study. Corrections need exact failure evidence, isolated frozen candidates, '
                  'and fresh validation with a matched stable control. No C++gain or candidate adoption is established.', '', data['limits'], ''])
    write(Path(plan['output']) / 'measured-results.md', '\n'.join(lines))
    print({k: data[k] for k in ('completed_games','wins','draws','losses','full_1000_game_study_complete')})


if __name__ == '__main__':
    main()
