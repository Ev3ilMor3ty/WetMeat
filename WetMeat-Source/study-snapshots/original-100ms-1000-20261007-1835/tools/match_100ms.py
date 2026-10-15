"""Paired fixed-movetime games, with full histories and UCI evidence. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import os
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from common import DRAW_RULE, adjudicated_outcome, game_config, load, require, write
from pipelined_clock_match import run_pipelined


class RecordedProtocol(chess.engine.UciProtocol):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send_line(self, line):
        self.sent.append(line)
        super().send_line(line)


def start_engine(path, settings):
    item = chess.engine.SimpleEngine.popen(RecordedProtocol, path, timeout=10)
    try:
        for name in settings:
            require(name in item.options, 'Required option unsupported: ' + name)
        item.configure(settings)
        item.ping()
        return item
    except BaseException:
        item.close()
        raise


def effective_settings(item):
    settings = dict(item.protocol.config)
    settings['Ponder'] = settings.get('Ponder', False)
    return settings


def run_game(config):
    path = Path(config['output'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_locked(config)


def run_locked(config):
    os.sched_setaffinity(0, {config['cpu']})
    path = Path(config['output'])
    journal = path.parent / 'live' / (path.name + '.jsonl')
    journal.parent.mkdir(exist_ok=True)
    if path.with_suffix('.json').exists():
        from evidence import verify_fixed_game
        saved = load(path.with_suffix('.json'))
        verify_fixed_game(saved, path.with_suffix('.pgn'), config)
        require(saved['tested_points'] is not None and not saved['engine_error'],
                'An incomplete or faulted game is never resumed')
        return saved
    require(not journal.exists() and not path.with_suffix('.pgn').exists(),
            'Interrupted game preserved; new authorization/data required, clocks never resume')

    def event(kind, **payload):
        with journal.open('a') as stream:
            stream.write(json.dumps({'kind': kind, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                                     **payload}, separators=(',', ':')) + '\n')

    tested = opponent = None
    moves = []
    try:
        tested = start_engine(config['engine'], config['common_uci'])
        opponent = start_engine(config['opponent'], config['common_uci'])
        tested.configure(config['options'])
        board, game = chess.Board(), chess.pgn.Game()
        node = game
        for text in config['opening'].split():
            move = board.parse_uci(text)
            node = node.add_variation(move)
            board.push(move)
        tested_color = config['tested_color']
        game.headers.update({'Event': 'WetMeat 1000-game fixed-movetime study', 'Site': 'local',
            'Date': dt.datetime.now(dt.timezone.utc).strftime('%Y.%m.%d'),
            'Round': str(config['round']), 'OpeningPair': str(config['pair']),
            'White': (tested if tested_color else opponent).id['name'],
            'Black': (opponent if tested_color else tested).id['name'],
            'TimeControl': f"{config['movetime_ms']}ms/move", 'FixedMoveTimeMS': str(config['movetime_ms']),
            'OpeningPlies': str(board.ply()), 'CPU': str(config['cpu']),
            'StudyPhase': config['phase'], 'TestedOptions': json.dumps(config['options'], sort_keys=True),
            'DrawRule': DRAW_RULE})
        event('start', headers=dict(game.headers), opening=config['opening'],
              movetime_ms=config['movetime_ms'], tested_binary_sha256=config['tested_sha'],
              opponent_binary_sha256=config['opponent_sha'], cpu=config['cpu'])
        token = object()
        termination, error, winner = None, None, None
        while adjudicated_outcome(board) is None and board.ply() < config['max_plies']:
            color = board.turn
            active = tested if color == tested_color else opponent
            active.timeout = 2.0
            event('thinking', ply=board.ply() + 1, color='white' if color else 'black',
                  fen=board.fen(), requested_movetime_ms=config['movetime_ms'])
            started = time.monotonic()
            try:
                result = active.play(board, chess.engine.Limit(time=config['movetime_ms'] / 1000),
                                     game=token, info=chess.engine.INFO_ALL, ponder=False)
            except (TimeoutError, chess.engine.EngineError) as exc:
                termination = 'ENGINE_ERROR'
                error = f'{type(exc).__name__}: {exc}'
                winner = None if board.has_insufficient_material(not color) else not color
                event('fault', termination=termination, engine_error=error, elapsed_s=time.monotonic()-started)
                break
            elapsed = time.monotonic() - started
            if result.move is None or result.move not in board.legal_moves:
                termination = 'ILLEGAL_MOVE_FORFEIT'
                error = f'Illegal bestmove {result.move} at {board.fen()}'
                winner = None if board.has_insufficient_material(not color) else not color
                event('fault', termination=termination, engine_error=error, elapsed_s=elapsed)
                break
            score = result.info.get('score')
            row = {'ply': board.ply() + 1, 'color': 'white' if color else 'black',
                   'engine': active.id['name'], 'tested': color == tested_color,
                   'fen_before': board.fen(), 'uci': result.move.uci(), 'san': board.san(result.move),
                   'elapsed_s': elapsed, 'requested_movetime_ms': config['movetime_ms'],
                   'reported_search_s': result.info.get('time'),
                   'clock_before_s': config['movetime_ms'] / 1000,
                   'depth': result.info.get('depth'), 'nodes': result.info.get('nodes'),
                   'score_cp_mover': score.pov(color).score() if score else None,
                   'mate_mover': score.pov(color).mate() if score else None,
                   'pv': [m.uci() for m in result.info.get('pv', [])]}
            board.push(result.move)
            node = node.add_variation(result.move)
            node.set_emt(elapsed)
            if score:
                node.set_eval(score, depth=result.info.get('depth'))
            moves.append(row)
            event('move', **row, fen_after=board.fen())
        if termination is None:
            outcome = adjudicated_outcome(board)
            termination = outcome.termination.name if outcome else 'UNFINISHED_PLY_CAP'
            winner = outcome.winner if outcome else None
            result_text = outcome.result() if outcome else '*'
        else:
            result_text = '1/2-1/2' if winner is None else '1-0' if winner else '0-1'
        game.headers.update(Result=result_text, Termination=termination)
        report = {'schema': 'fixed-movetime-v1', 'variant': config['variant'], 'phase': config['phase'],
                  'round': config['round'], 'pair': config['pair'], 'opening': config['opening'],
                  'tested_color': 'white' if tested_color else 'black', 'result': result_text,
                  'termination': termination, 'tested_points': None if result_text == '*' else
                      .5 if winner is None else int(winner == tested_color),
                  'headers': dict(game.headers), 'plies': board.ply(), 'moves': moves,
                  'final_fen': board.fen(), 'tested_engine': tested.id, 'opponent': opponent.id,
                  'tested_binary_sha256': config['tested_sha'], 'opponent_binary_sha256': config['opponent_sha'],
                  'requested_movetime_ms': config['movetime_ms'], 'cpu': config['cpu'], 'threads_each': 1,
                  'hash_mb_each': config['common_uci']['Hash'], 'move_overhead_ms_each': config['common_uci']['Move Overhead'],
                  'max_plies': config['max_plies'], 'tested_options': config['options'], 'draw_rule': DRAW_RULE,
                  'tested_uci_settings': effective_settings(tested), 'opponent_uci_settings': effective_settings(opponent),
                  'sent_uci': {'wetmeat': tested.protocol.sent, 'stockfish': opponent.protocol.sent},
                  'engine_error': error, 'live_journal': str(journal),
                  'time_rule': 'UCI go movetime100 for both sides; record wall time and reported search time. No accumulated game clock, increment or artificial 100ms-overhead forfeits.'}
        from evidence import verify_fixed_game
        write(path.with_suffix('.pgn'), str(game) + '\n\n')
        verify_fixed_game(report, path.with_suffix('.pgn'), config)
        write(path.with_suffix('.json'), report)
        event('finished', result=result_text, termination=termination, engine_error=error, plies=board.ply())
        print(f"Finished {config['round']}: {result_text} ({termination})", flush=True)
        require(not error and result_text != '*', 'Protocol fault/unfinished game preserved; stop for review')
        return report
    finally:
        for item in (tested, opponent):
            if item:
                try:
                    item.quit()
                except (TimeoutError, chess.engine.EngineError):
                    item.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--first-pair', type=int, required=True)
    parser.add_argument('--pairs', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = load(args.plan)
    jobs = []
    for pair in range(args.first_pair, args.first_pair + args.pairs):
        for white in (True, False):
            row = game_config(plan, pair)
            number = 2 * pair - int(white)
            row.update(round=number, tested_color=white, cpu=((pair - 1) % 2) ^ int(not white),
                       output=str(args.output / f'game-{number:04d}'))
            jobs.append(row)
    run_pipelined(jobs, 2, play_game=run_game)


if __name__ == '__main__':
    main()
