"""Verify played clocks and finite-audit evidence without running engines. GPL-3.0-or-later."""
import hashlib
import json
import math

import chess

from clock_match import DRAW_RULE, adjudicated_outcome


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def verify_game(recorded, game):
    require(game is not None and not game.errors, 'Missing or malformed PGN')
    opening = recorded['opening'].split()
    nodes = list(game.mainline())
    records = recorded['moves']
    require(len(nodes) == len(opening) + len(records) == recorded['plies'], 'PGN/recorded ply coverage differs')
    require(game.board().fen() == chess.STARTING_FEN, 'Unexpected starting position')
    require([node.move.uci() for node in nodes[:len(opening)]] == opening, 'PGN opening differs')
    require(game.headers['Result'] == recorded['result'], 'PGN/recorded result differs')
    require(game.headers.get('Termination') == recorded['termination'], 'PGN/recorded termination differs')
    base, increment = recorded['base_seconds'], recorded['increment_seconds']
    require(number(base) and base > 0 and number(increment) and increment >= 0, 'Invalid clock settings')
    require([float(value) for value in game.headers['TimeControl'].split('+')] == [base, increment], 'PGN time control differs')
    color = recorded['tested_color']
    require(color in ('white', 'black'), 'Invalid tested color')
    board = game.board()
    for text in opening:
        board.push_uci(text)
    clocks = {'white': base, 'black': base}
    for move, node in zip(records, nodes[len(opening):]):
        active = 'white' if board.turn else 'black'
        require(move['ply'] == board.ply() + 1 and move['color'] == active, 'Nonsequential/incorrect move color')
        require(type(move['tested']) is bool and move['tested'] == (active == color), 'Tested-side flag differs')
        require(move['engine'] == game.headers['White' if board.turn else 'Black'], 'Recorded engine differs')
        require(move['fen_before'] == board.fen(), 'Move position differs')
        require(move['uci'] == node.move.uci() and node.move in board.legal_moves, 'Recorded move differs or is illegal')
        require(move['san'] == board.san(node.move), 'Recorded SAN differs')
        before, elapsed, after = (move[key] for key in ('clock_before_s', 'elapsed_s', 'clock_after_s'))
        require(all(number(value) for value in (before, elapsed, after)), 'Nonfinite clock')
        require(abs(before - clocks[active]) <= 1e-6, 'Recorded clock continuity differs')
        require(0 <= elapsed < before, 'Played move exceeded its clock')
        require(abs(after - (before - elapsed + increment)) <= 1e-6, 'Recorded clock arithmetic differs')
        require(node.clock() is not None and abs(node.clock() - after) <= .00051, 'PGN clock differs beyond rounding')
        require(node.emt() is not None and abs(node.emt() - elapsed) <= .00051, 'PGN elapsed time differs beyond rounding')
        clocks[active] = after
        board.push(node.move)
    require(board.fen() == recorded['final_fen'], 'Final position differs')
    active = 'white' if board.turn else 'black'
    forfeits = ('TIME_FORFEIT', 'ENGINE_ERROR', 'ILLEGAL_MOVE_FORFEIT')
    policy = recorded.get('draw_rule')
    require(policy in (None, DRAW_RULE), 'Unrecognized draw policy')
    require(game.headers.get('DrawRule') == policy, 'PGN draw policy differs')
    outcome = board.outcome(claim_draw=True) if policy is None else adjudicated_outcome(board)
    if recorded['termination'] in forfeits:
        require(outcome is None, 'Forfeit recorded after a natural game ending')
        result = '1/2-1/2' if board.has_insufficient_material(not board.turn) else '0-1' if board.turn else '1-0'
        require(recorded['result'] == result, 'Forfeit awarded to the wrong side')
    elif recorded['termination'] == 'UNFINISHED_PLY_CAP':
        require(recorded['result'] == '*' and outcome is None and board.ply() >= recorded['max_plies'], 'Invalid unfinished game')
    else:
        require(outcome is not None and outcome.result() == recorded['result'] and outcome.termination.name == recorded['termination'], 'Natural game result differs')
    points = None if recorded['result'] == '*' else .5 if recorded['result'] == '1/2-1/2' else int((recorded['result'] == '1-0') == (color == 'white'))
    require(points == recorded['tested_points'], 'Result-to-points differs')
    if 'tested_uci_settings' in recorded:
        require(json.loads(game.headers['TestedOptions']) == recorded['tested_options'], 'PGN engine options differ')
        for settings in (recorded['tested_uci_settings'], recorded['opponent_uci_settings']):
            require(settings.get('Threads') == recorded['threads_each'] == 1 and settings.get('Hash') == recorded['hash_mb_each'], 'Applied engine resources differ')
            require(settings.get('Move Overhead') == recorded['move_overhead_ms_each'] == 30, 'Applied engine clock overhead differs')
        opponent = recorded['opponent_uci_settings']
        require(opponent.get('Skill Level') == 20 and opponent.get('UCI_LimitStrength') is False and opponent.get('SyzygyPath') == '', 'Opponent is not configured at full strength')
        require(all(recorded['tested_uci_settings'].get(key) == value for key, value in recorded['tested_options'].items()), 'Declared experiment option was not applied')
    for color in clocks:
        final = recorded['final_clocks_s'][str(color == 'white')]
        require(number(final) and final >= 0, 'Invalid final clock')
        if recorded['termination'] in forfeits and color == active:
            require(final <= clocks[color] + 1e-6, 'Forfeit increased its clock')
            if recorded['termination'] == 'TIME_FORFEIT':
                require(final == 0, 'Time forfeit has a nonzero clock')
        else:
            require(abs(final - clocks[color]) <= 1e-6, 'Final clock differs')
    return {move['ply']: move for move in records if move['tested']}


def verify_audit(audit, raw, recorded, tested):
    require(audit['source_sha256'] == hashlib.sha256(raw).hexdigest(), 'Audit has stale input')
    settings = audit['settings']
    require(settings['judge_sha'] == recorded['opponent_binary_sha256'], 'Audit uses a different judge binary')
    require(settings['method'] in ('completed-common-depth-multipv2-v1', 'completed-common-depth-multipv2-v2-wdl'), 'Unrecognized audit method')
    require(settings['min_nodes'] >= 1000000 and settings['multiplier'] >= 2 and settings['refine_multiplier'] >= 4, 'Audit budget below study minimum')
    require(settings['mistake_cp'] == 50 and settings['blunder_cp'] == 200, 'Audit error definitions differ')
    require(audit['status'] in ('running', 'completed'), 'Invalid audit status')
    rows = audit['moves']
    require(len({row['ply'] for row in rows}) == len(rows), 'Duplicate audited ply')
    all_moves = {move['ply']: move for move in recorded['moves']}
    selected = []
    for row in rows:
        original = all_moves.get(row['ply'])
        require(original is not None, 'Audit ply absent from game')
        require(row['tested'] == original['tested'] and row['played'] == original['uci'] and row['fen'] == original['fen_before'], 'Audit move/side/position differs')
        require(row['played_nodes'] == original['nodes'] and row['played_depth'] == original['depth'], 'Audited original search differs')
        budget = max(settings['min_nodes'], int((original['nodes'] or 0) * settings['multiplier']))
        require(row['audit_budget_nodes_per_search'] >= budget, 'Audited move budget insufficient')
        loss = row['loss_cp']
        require(number(loss) and loss >= 0, 'Invalid audited loss')
        category = 'blunder' if loss >= 200 else 'mistake' if loss >= 50 else 'acceptable'
        require(row['category'] == category, 'Audit category contradicts loss')
        if row.get('forced_only_move'):
            require(chess.Board(row['fen']).legal_moves.count() == 1 and loss == 0, 'Invalid forced-only-move audit')
        else:
            best, played = row['best_evaluation'], row['played_evaluation']
            require(best['depth'] == played['depth'], 'Audit comparison depths differ')
            require(loss == max(0, best['value'] - played['value']), 'Audit loss contradicts evaluations')
            require(best['pv'][0] == row['best'] and played['pv'][0] == row['played'], 'Audit root PV differs')
            require(row['oracle_depth_below_played'] == bool(original['depth'] and best['depth'] < original['depth']), 'Shallow-judge label differs')
            if row['initial_loss_cp'] >= 40:
                require(row['refined'] and row['refined_budget_nodes_per_search'] >= max(budget + 1, int(budget * settings['refine_multiplier'])), 'Flagged move lacks required refinement')
            if row.get('wdl_expectation_loss') is not None:
                require(number(row['wdl_expectation_loss']) and 0 <= row['wdl_expectation_loss'] <= 1, 'Invalid WDL loss')
                if 'wdl' in best and 'wdl' in played:
                    expected = max(0, best['wdl']['expectation'] - played['wdl']['expectation'])
                    require(abs(row['wdl_expectation_loss'] - expected) <= 1e-12, 'WDL loss differs')
        if row['ply'] in tested:
            selected.append(row)
    if audit['status'] == 'completed':
        require({row['ply'] for row in selected} == set(tested), 'Completed audit lacks full tested-move coverage')
    return selected
