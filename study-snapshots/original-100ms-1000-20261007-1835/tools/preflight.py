"""Input-integrity fixtures and actual100ms legality/protocol checks. GPL-3.0-or-later."""
import argparse
import copy
import json
import os
import random
import tempfile
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from common import DRAW_RULE, digest, load, require, write
from evidence import batch_evidence, verify_both_audit, verify_fixed_game


def fixtures(plan):
    with tempfile.TemporaryDirectory(prefix='wetmeat-100ms-fixtures-') as folder:
        directory = Path(folder)
        game = chess.pgn.Game()
        game.headers.update(White='WetMeat fixture', Black='Stockfish19 fixture', Result='0-1',
                            Termination='CHECKMATE', FixedMoveTimeMS='100', TimeControl='100ms/move',
                            CPU='0', Round='1', OpeningPair='1', StudyPhase='training', DrawRule=DRAW_RULE)
        board, node, rows = chess.Board(), game, []
        traces = {'wetmeat': [], 'stockfish': []}
        for text in ['f2f3','e7e5','g2g4','d8h4']:
            side = 'wetmeat' if board.turn else 'stockfish'
            history = ' '.join(m.uci() for m in board.move_stack)
            traces[side].extend(['position startpos' + (' moves ' + history if history else ''), 'go movetime 100'])
            move = board.parse_uci(text)
            rows.append({'ply': board.ply()+1, 'color': 'white' if board.turn else 'black',
                         'engine': game.headers['White' if board.turn else 'Black'], 'tested': board.turn,
                         'fen_before': board.fen(), 'uci': text, 'san': board.san(move), 'elapsed_s': .1,
                         'requested_movetime_ms':100, 'reported_search_s':.1, 'clock_before_s':.1,
                         'depth':12, 'nodes':50000, 'score_cp_mover':0, 'mate_mover':None, 'pv':[text]})
            board.push(move); node=node.add_variation(move); node.set_emt(.1)
        config={'round':1,'pair':1,'opening':'','tested_sha':plan['stable_sha256'],
                'opponent_sha':plan['opponent_sha256'],'movetime_ms':100,'cpu':0,'common_uci':plan['common_uci'],
                'max_plies':1000,'phase':'training','variant':'baseline','options':{},'tested_color':True}
        record={'schema':'fixed-movetime-v1','round':1,'pair':1,'opening':'','phase':'training','variant':'baseline',
                'tested_binary_sha256':config['tested_sha'],'opponent_binary_sha256':config['opponent_sha'],
                'requested_movetime_ms':100,'cpu':0,'threads_each':1,'hash_mb_each':128,'move_overhead_ms_each':30,
                'max_plies':1000,'tested_options':{},'draw_rule':DRAW_RULE,'tested_color':'white','result':'0-1',
                'termination':'CHECKMATE','tested_points':0,'engine_error':None,'plies':4,'moves':rows,
                'final_fen':board.fen(),'sent_uci':traces,
                'tested_uci_settings':{**plan['common_uci'],'Ponder':False},
                'opponent_uci_settings':{**plan['common_uci'],'Ponder':False}}
        source=directory/'game-0001.json';pgn=source.with_suffix('.pgn');write(pgn,str(game)+'\n\n');write(source,record)
        moves=verify_fixed_game(record,pgn,config)
        tests=['valid full-history fixed100ms game']
        changes=[('reduced skill',lambda r:r['opponent_uci_settings'].update({'Skill Level':19})),
                 ('Elo limit',lambda r:r['opponent_uci_settings'].update({'UCI_LimitStrength':True})),
                 ('unequal hash',lambda r:r['tested_uci_settings'].update({'Hash':64})),
                 ('different binary',lambda r:r.update(tested_binary_sha256='0'*64)),
                 ('different search limit',lambda r:r['sent_uci']['stockfish'].__setitem__(1,'go movetime 99')),
                 ('missing full history',lambda r:r['sent_uci']['wetmeat'].__setitem__(2,'position startpos')),
                 ('illegal recorded move',lambda r:r['moves'][0].update(uci='e2e5')),
                 ('wrong owner',lambda r:r['moves'][1].update(tested=True))]
        for name,change in changes:
            wrong=copy.deepcopy(record);change(wrong)
            try:verify_fixed_game(wrong,pgn,config)
            except ValueError:tests.append('rejected '+name)
            else:raise AssertionError('Accepted '+name)
        audit_rows=[]
        for row in rows:
            loss=100 if row['ply']==1 else 250 if row['ply']==3 else 0
            best='e2e4' if row['ply']==1 else 'g2g3' if row['ply']==3 else row['uci']
            audit_rows.append({'ply':row['ply'],'engine':row['engine'],'tested':row['tested'],'fen':row['fen_before'],
                'played':row['uci'],'played_nodes':row['nodes'],'played_depth':row['depth'],
                'audit_budget_nodes_per_search':1000000,'loss_cp':loss,
                'category':'blunder' if loss>=200 else 'mistake' if loss>=50 else 'acceptable',
                'best':best,'best_evaluation':{'depth':12,'value':loss,'pv':[best]},
                'played_evaluation':{'depth':12,'value':0,'pv':[row['uci']]},
                'initial_loss_cp':loss,'refined':bool(loss),'refined_budget_nodes_per_search':4000000,
                'oracle_depth_below_played':False})
        audit={'status':'completed','scope':'both-engines','settings':plan['audit_settings'],
               'source_sha256':digest(source),'moves':audit_rows}
        verify_both_audit(audit,source,record,moves,plan);tests.append('both-engine common-depth and error evidence')
        for name,change in [
            ('stale source',lambda a:a.update(source_sha256='0'*64)),
            ('opponent omitted',lambda a:a.update(moves=[x for x in a['moves'] if x['tested']])),
            ('wrong scope',lambda a:a.update(scope='tested-engine-only')),
            ('unequal depths',lambda a:a['moves'][0]['played_evaluation'].update(depth=13)),
            ('wrong category',lambda a:a['moves'][0].update(category='acceptable')),
            ('missing refinement',lambda a:a['moves'][0].update(refined=False))]:
            wrong=copy.deepcopy(audit);change(wrong)
            try:verify_both_audit(wrong,source,record,moves,plan)
            except ValueError:tests.append('rejected '+name)
            else:raise AssertionError('Accepted '+name)
        fake_plan=copy.deepcopy(plan);fake_plan['pairs_per_batch']=1
        book=directory/'book.json';write(book,{'pairs':[{'pair':1,'opening':''}]});fake_plan['training_openings']=str(book)
        partial=batch_evidence(fake_plan,directory)
        require(all(x['mistake_rate'] is None and x['blunder_rate'] is None for x in partial['by_engine'].values()),'Partial rates leaked')
        tests.append('partial BOTH-engine rates suppressed')
        return tests


def engine_checks(path, plan):
    from match_100ms import start_engine
    engine=start_engine(path,plan['common_uci'])
    rows=[]
    try:
        generator=random.Random(61007100)
        board=chess.Board()
        for i in range(100):
            if board.is_game_over() or board.ply()>35:board=chess.Board()
            started=time.monotonic()
            result=engine.play(board,chess.engine.Limit(time=.1),game=object(),info=chess.engine.INFO_ALL,ponder=False)
            require(result.move in board.legal_moves,'Illegal100ms move')
            rows.append({'position':board.fen(),'move':result.move.uci(),'wall_s':time.monotonic()-started,
                         'reported_search_s':result.info.get('time')})
            board.push(generator.choice(list(board.legal_moves)))
        for fen in ['6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1',
                    '7k/6pp/5KQ1/8/8/8/8/8 w - - 0 1']:
            board=chess.Board(fen);require(board.is_valid(),'Invalid tactical fixture')
            result=engine.play(board,chess.engine.Limit(time=.1),game=object(),ponder=False)
            require(result.move in board.legal_moves,'Illegal tactical move');board.push(result.move)
            require(board.is_checkmate(),'Missed elementary mate in one at100ms')
        board=chess.Board()
        with engine.analysis(board) as analysis:
            time.sleep(.03);analysis.stop();analysis.wait()
        engine.ping()
        result=engine.play(chess.Board(),chess.engine.Limit(time=.1),game=object(),ponder=False)
        require(result.move in chess.Board().legal_moves,'Bad context after infinite-stop')
        fixed=[line for line in engine.protocol.sent if line.startswith('go movetime')]
        require(fixed==['go movetime 100']*103,'Incorrect actual UCI limit')
        require(engine.protocol.config.get('Ponder',False) is False,'Ponder leaked')
        return {'name':engine.id['name'],'legality_positions':100,'elementary_tactics':2,
                'infinite_stop_newgame_context':True,'fixed100ms_go_commands':len(fixed),'positions':rows}
    finally:engine.quit()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--fixtures-only',action='store_true');args=parser.parse_args();plan=load(args.plan)
    tests=fixtures(plan)
    report={'status':'passed','metadata_checks':tests,'metadata_check_count':len(tests),'engine_checks':[],'engine_strength_gain':False}
    if not args.fixtures_only:
        os.sched_setaffinity(0,{0})
        for path in (plan['engine'],plan['opponent']):report['engine_checks'].append(engine_checks(path,plan))
    write(Path(plan['output'])/'preflight-results.json',report)
    print({'status':'passed','metadata_checks':len(tests),'engines_checked':len(report['engine_checks'])})


if __name__=='__main__':main()
