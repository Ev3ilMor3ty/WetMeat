"""Check replay provenance and heldout separation without engines. GPL-3.0-or-later."""
import copy
import hashlib
import io
import json
import tempfile
from pathlib import Path

import chess
import chess.pgn

from check_report_evidence import fixture
from export_failures import extract, save


def main():
    cases = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        study, output = root / 'study', root / 'review'
        study.mkdir()
        path, record, audit_path, audit = fixture(study, 1, 'baseline', 'white')
        row = audit['moves'][0]
        row.update(best='e2e4', loss_cp=250, category='blunder', initial_loss_cp=250,
                   refined=True, refined_budget_nodes_per_search=9600000)
        row['best_evaluation'].update(value=250, pv=['e2e4', 'e7e5', 'g1f3'])
        row['played_evaluation'].update(value=0, pv=['f2f3', 'e7e5', 'g2g4', 'd8h4'])
        audit_path.write_text(json.dumps(audit))
        report = extract(study)
        assert report['selected_phases'] == ['training'] and not report['cases']
        cases.append('default export excludes heldout failures')
        report = extract(study, include_heldout=True)
        assert len(report['cases']) == 1 and report['contains_heldout_failures']
        assert report['cases'][0]['fresh_heldout_required_if_used_for_tuning']
        cases.append('heldout failures explicitly require fresh validation')
        # A legal opening returns to start for its second occurrence. The FEN
        # alone cannot reconstruct that history, while the exported prefix can.
        opening = ['g1f3', 'g8f6', 'f3g1', 'f6g8']
        game = chess.pgn.Game()
        game.headers.update(White='fixture-white', Black='fixture-black', TimeControl='600+5',
                            StudyPhase='training', Result='0-1', Termination='CHECKMATE', TestedOptions='{}')
        board, node = game.board(), game
        for text in opening:
            move = board.parse_uci(text)
            board.push(move)
            node = node.add_variation(move)
        assert board.is_repetition(2) and not chess.Board(board.fen()).is_repetition(2)
        for move in record['moves']:
            move.update(ply=board.ply() + 1, fen_before=board.fen())
            parsed = board.parse_uci(move['uci'])
            board.push(parsed)
            node = node.add_variation(parsed)
            node.set_clock(move['clock_after_s'])
            node.set_emt(move['elapsed_s'])
        record.update(phase='training', opening=' '.join(opening), plies=board.ply(), final_fen=board.fen())
        raw = json.dumps(record).encode()
        path.write_bytes(raw)
        path.with_suffix('.pgn').write_text(str(game) + '\n')
        originals = {move['ply']: move for move in record['moves']}
        for row in audit['moves']:
            row['ply'] += len(opening)
            row['fen'] = originals[row['ply']]['fen_before']
        audit['source_sha256'] = hashlib.sha256(raw).hexdigest()
        audit_path.write_text(json.dumps(audit))
        report = extract(study)
        assert len(report['cases']) == 1 and report['cases'][0]['complete_history_uci'] == opening
        assert report['cases'][0]['uci_position_command'].endswith(' '.join(opening))
        assert report['cases'][0]['clocks_before_s'] == {'white': 600, 'black': 600}
        cases.append('complete repetition history and original clocks retained')
        save(report, output)
        exported = json.loads((output / 'cases.json').read_text())
        assert exported['cases'][0]['tested_binary_sha256'] == 'baseline'
        pgn = chess.pgn.read_game(io.StringIO((output / 'diagnostics.pgn').read_text()))
        assert pgn is not None and not pgn.errors and pgn.headers['Result'] == '*'
        root_node = next(node for node in pgn.mainline() if node.ply() == 4)
        assert root_node.board().is_repetition(2) and len(root_node.variations) == 2
        assert {node.move.uci() for node in root_node.variations} == {'e2e4', 'f2f3'}
        epd_board = chess.Board()
        operations = epd_board.set_epd((output / 'positions.epd').read_text().strip())
        assert epd_board.fen() == exported['cases'][0]['fen']
        assert operations['bm'] == [chess.Move.from_uci('e2e4')]
        cases.append('legal diagnostic PGN branches and EPD round trip')
        invalid = copy.deepcopy(audit)
        invalid['moves'][0]['best_evaluation']['pv'].append('e1e8')
        audit_path.write_text(json.dumps(invalid))
        try:
            extract(study)
        except ValueError as error:
            assert 'Illegal move' in str(error)
        else:
            raise AssertionError('Illegal recorded judge PV accepted')
        cases.append('invalid judge PV rejected')
    print(json.dumps({'status': 'passed', 'cases': cases, 'engine_searches': 0,
                      'limitations': 'Synthetic evidence only; no measured playing strength.'}))


if __name__ == '__main__':
    main()
