"""Freeze a fresh1000-game baseline and unused validation pool. GPL-3.0-or-later."""
import csv
import datetime as dt
import io
import json
import random
import shutil
import sys
from pathlib import Path

import chess
import chess.pgn

from common import DRAW_RULE, NIGHT, digest, load, position_key, require, write

PYTHON='/workspace/aurora-chess/.venv/bin/python'
OLD=Path('/workspace/aurora-stockfish/results/original-counter-ongoing-20261007-1557')
ROOT=Path(__file__).resolve().parents[1]


def previous_positions():
    forbidden=set()
    from match import OPENINGS
    for line in OPENINGS+load(OLD/'fresh-training-openings.json')['openings']:
        board=chess.Board()
        for move in line.split():board.push_uci(move)
        forbidden.add(position_key(board))
    files=[]
    for path in Path('/workspace/aurora-stockfish/results').glob('**/game-*.json'):
        if ROOT in path.parents:continue
        record=load(path)
        if 'tested_binary_sha256' not in record or 'opening' not in record or 'final_fen' not in record:continue
        files.append({'file':str(path),'sha256':digest(path)})
        board=chess.Board()
        for text in record['opening'].split():
            board.push_uci(text);forbidden.add(position_key(board))
        for row in record['moves']:
            if 'fen_before' in row:forbidden.add(position_key(chess.Board(row['fen_before'])))
        forbidden.add(position_key(chess.Board(record['final_fen'])))
    return forbidden,files


def prepare_openings():
    forbidden,previous=previous_positions()
    groups={key:[] for key in 'ABCDE'}
    for letter in groups:
        path=ROOT/'openings-source'/f'{letter.lower()}.tsv'
        for row in csv.DictReader(path.open(),delimiter='\t'):
            game=chess.pgn.read_game(io.StringIO(row['pgn']))
            require(game is not None and not game.errors,'Malformed named opening source')
            moves=list(game.mainline_moves());board=game.end().board()
            if not (8<=len(moves)<=16) or not board.is_valid() or board.is_game_over():continue
            key=position_key(board)
            if key in forbidden:continue
            groups[letter].append({'eco':row['eco'],'name':row['name'],'source_pgn':row['pgn'],
                                  'opening':' '.join(m.uci() for m in moves),'position_key':key})
    rng=random.Random(20261007100)
    for rows in groups.values():
        rows.sort(key=lambda row:(row['eco'],row['name'],row['opening']));rng.shuffle(rows)
    selected=[];seen=set()
    while len(selected)<750:
        advanced=False
        for letter,rows in groups.items():
            while rows:
                row=rows.pop()
                if row['position_key'] in seen:continue
                seen.add(row['position_key']);selected.append(row);advanced=True;break
            if len(selected)==750:break
        require(advanced,'Insufficient unique fresh named opening endpoints')
    for name,rows in [('training-openings.json',selected[:500]),('reserved-validation-openings.json',selected[500:])]:
        pairs=[{'pair':i+1,**row} for i,row in enumerate(rows)]
        write(ROOT/name,{'schema':'paired-named-openings-v1','seed':20261007100,'pairs':pairs,
                         'selection':'Deterministic round-robin ECO groups, legal8..16ply endpoints; exact prior positions and reserved rapid opening endpoints excluded. No evaluation, score or error based selection.',
                         'source_license':'CC0/public-domain lichess-org/chess-openings; README and original TSV files preserved.'})
    write(ROOT/'observations/opening-novelty.json',{'excluded_prior_position_keys':len(forbidden),
          'training_pairs':500,'unused_validation_pairs':250,'all750endpoints_unique':True,
          'prior_source_files':previous,'prior_games_used_only_to_exclude_position_reuse':True,
          'scores_or_heldout_failure_evidence_used_for_selection':False})


def prepare():
    require(not (ROOT/'ready.json').exists(),'Study already frozen; do not prepare/reselect again')
    require(shutil.disk_usage(ROOT).free>=2*1024**3,'Insufficient free space for1000full histories/audits')
    old=load(OLD/'plan.json')
    prepare_openings()
    fixed=dict(old['frozen_sha256'])
    for path,expected in fixed.items():require(digest(path)==expected,'Preserved old frozen input changed: '+path)
    dependencies=['clock_match.py','match.py','pipelined_clock_match.py','pipelined_analyse_games.py',
                  'verify_records.py','cutoff_watch_multi.py','continue_original.py']
    for name in dependencies:
        path=Path(NIGHT)/name;fixed[str(path)]=digest(path)
    for path in list((ROOT/'tools').glob('*.py'))+list((ROOT/'safety').glob('*.py'))+list((ROOT/'openings-source').iterdir())+[ROOT/'training-openings.json',ROOT/'reserved-validation-openings.json',ROOT/'Copying.txt',ROOT/'README.md']:
        fixed[str(path)]=digest(path)
    require(digest('/workspace/aurora-stockfish/bin/wetmeat-linux-avx512')==old['stable_binary_sha256'],'Stable binary changed')
    require(digest('/workspace/scratch/stockfish-19-source/src/stockfish-19-native')==old['judge_sha256'],'Opponent binary changed')
    locks=[str(ROOT/'runner.lock')]+old['lock_paths']
    stages=[{'name':'preflight','command':[PYTHON,str(ROOT/'tools/preflight.py'),'--plan',str(ROOT/'plan.json')],
             'safe_boundary_after':True}]
    for batch in range(1,51):
        directory=ROOT/'training'/f'batch-{batch:03d}'
        directory.mkdir(exist_ok=True)
        stages.extend([
          {'name':f'batch{batch:03d}_games','command':[PYTHON,str(ROOT/'tools/match_100ms.py'),'--plan',str(ROOT/'plan.json'),
             '--first-pair',str((batch-1)*10+1),'--pairs','10','--output',str(directory)],'safe_boundary_after':False},
          {'name':f'batch{batch:03d}_both_audits','command':[PYTHON,str(Path(NIGHT)/'pipelined_analyse_games.py'),
             '--games',str(directory),'--judge','/workspace/scratch/stockfish-19-source/src/stockfish-19-native',
             '--workers','2','--min-nodes','1000000','--multiplier','2','--refine-multiplier','4',
             '--mistake-cp','50','--blunder-cp','200','--hash','512','--output',str(directory/'audit')],
             'safe_boundary_after':False},
          {'name':f'batch{batch:03d}_verify_export','command':[PYTHON,str(ROOT/'tools/evidence.py'),
             '--plan',str(ROOT/'plan.json'),'--batch',str(directory)],'safe_boundary_after':True}])
    stages.append({'name':'final_baseline_comparison','command':[PYTHON,str(ROOT/'tools/final_analysis.py'),
                   '--plan',str(ROOT/'plan.json')],'safe_boundary_after':True})
    plan={'schema':'wetmeat100ms1000v1','output':str(ROOT),'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
          'authorization':'User requests1000paired games at100milliseconds per move, BOTH-engine mistake/blunder comparison, then evidence-based improvements and fresh validation. Automatic messages disabled; no fixed cutoff.',
          'deadline_utc':None,'no_fixed_user_cutoff':True,'games':1000,'pairs':500,'pairs_per_batch':10,
          'movetime_ms':100,'max_plies':1000,'engine':'/workspace/aurora-stockfish/bin/wetmeat-linux-avx512',
          'opponent':'/workspace/scratch/stockfish-19-source/src/stockfish-19-native',
          'stable_sha256':old['stable_binary_sha256'],'opponent_sha256':old['judge_sha256'],
          'judge_sha256':old['judge_sha256'],'common_uci':dict(old['common_uci_settings']),
          'audit_settings':dict(old['audit_settings']),'training_openings':str(ROOT/'training-openings.json'),
          'unused_validation_openings':str(ROOT/'reserved-validation-openings.json'),
          'training_only':True,'full_audit_scope':'both-engines','draw_rule':DRAW_RULE,'stages':stages,
          'lock_paths':locks,'frozen_sha256':fixed,'poll_seconds':30,'engine_source_changes':0,'candidate_adopted':False,
          'phase_policy':'Initial1000games are a stable baseline TRAINING study. Review full histories/common-depth failures, pause safely before isolated C++ changes. A frozen correction needs fresh reserved250opening4-game paired validation (candidate+unchanged control) in a separate plan; heldout results never tune this baseline or its selection.',
          'preserved_rapid_root':str(OLD),'old247andall_releases_GPL_NNUE_preserved':True,
          'limits':'No promised lower error rate, net wins, Stockfish superiority, Elo or perfect play. Judges are finite and shared-family; paired openings/moves are correlated.'}
    write(ROOT/'plan.json',plan)
    return plan


def finalize_ready(plan):
    digest_plan=digest(ROOT/'plan.json')
    write(ROOT/'ready.json',{'status':'frozen_baseline_training','plan_sha256':digest_plan,
          'source_sha256':{k:v for k,v in plan['frozen_sha256'].items() if k.endswith('.py')},'frozen_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
          'engine_changes':0,'candidate_adopted':False,'automatic_messages_enabled':False})
    watch_paths=[ROOT/'safety/watch.py',Path(NIGHT)/'cutoff_watch_multi.py',Path(NIGHT)/'continue_original.py']
    write(ROOT/'watch-ready.json',{'plan_sha256':digest_plan,'no_fixed_user_cutoff':True,
          'source_sha256':{str(p):digest(p) for p in watch_paths}})
if __name__=='__main__':
    plan=prepare();finalize_ready(plan)
