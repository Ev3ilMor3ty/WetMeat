"""Paired-opening uncertainty for a complete baseline; no Elo claims. GPL-3.0-or-later."""
import argparse
import os
import random
from pathlib import Path

from common import digest, load, require, write
from evidence import progress


def quantiles(values):
    values.sort();n=len(values)
    return [values[int(.025*(n-1))],values[int(.975*(n-1))]]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args();plan=load(args.plan);root=Path(plan['output']);os.sched_setaffinity(0,{0})
    data=progress(plan)
    require(data['full_1000_game_study_complete'] and data['engine_faults']==0,'Full1000-game audited baseline not complete')
    grouped={letter:[] for letter in 'ABCDE'}
    labels={str(row['pair']):row['eco'][0] for row in load(plan['training_openings'])['pairs']}
    seen=set()
    for manifest in sorted((root/'training').glob('batch-*/batch-evidence.json')):
        batch=load(manifest)
        for files in batch['files']:
            path=Path(files['game']);require(digest(path)==files['game_sha256'],'Completed source changed')
            require(digest(path.with_suffix('.pgn'))==files['pgn_sha256'],'Completed PGN changed')
            require(digest(path.parent/'audit'/path.name)==files['audit_sha256'],'Completed audit changed')
        for pair,row in batch['by_pair'].items():
            require(pair not in seen,'Duplicate opening pair');seen.add(pair)
            require(row['games']==2,'Opening pair incomplete');grouped[labels[pair]].append(row)
    require(sum(len(x) for x in grouped.values())==500,'Incomplete/duplicate paired sample')
    rng=random.Random(202610071002000)
    values={'score':[],'net_win_fraction':[],'mistake_rate_difference':[],'blunder_rate_difference':[]}
    for _ in range(2000):
        points=net=0
        stats={side:{'moves':0,'mistakes':0,'blunders':0} for side in ('wetmeat','stockfish')}
        for group in grouped.values():
            for _ in range(len(group)):
                pair=rng.choice(group);points+=pair['points'];net+=pair['wins']-pair['losses']
                for side in stats:
                    for key in stats[side]:stats[side][key]+=pair[side][key]
        values['score'].append(points/1000);values['net_win_fraction'].append(net/1000)
        for event in ('mistakes','blunders'):
            values[event[:-1]+'_rate_difference'].append(stats['wetmeat'][event]/stats['wetmeat']['moves']-
                                                        stats['stockfish'][event]/stats['stockfish']['moves'])
    intervals={}
    for name,samples in values.items():
        # A degenerate observed distribution cannot certify zero errors/equality.
        intervals[name]=quantiles(samples) if min(samples)!=max(samples) else None
    by=data['by_engine'];comparison={}
    for name in ('mistake','blunder'):
        difference=by['wetmeat'][name+'_rate']-by['stockfish'][name+'_rate']
        comparison[name+'_rate_difference_wetmeat_minus_stockfish']=difference
        comparison['wetmeat_lower_'+name+'_rate_observed']=difference<0
    final={'status':'completed_baseline_training','games':1000,'wins':data['wins'],'draws':data['draws'],'losses':data['losses'],
           'by_engine':by,'observed_more_wins_than_losses':data['wins']>data['losses'],
           'comparison':comparison,'stratified_paired_opening_bootstrap_95':intervals,
           'bootstrap_replicates':2000,'opening_pairs':500,'candidate_adopted':False,'engine_changes':0,
           'limits':'Exploratory TRAINING sample, finite Stockfish-family judgment, possible shared-family bias. Bootstrap resamples whole paired openings within ECO groups; it is conditional on this selected book and cannot measure oracle misses or guarantee future performance. Degenerate intervals are suppressed. No calibrated Elo, superiority, perfect play or validated code improvement. A correction needs fresh frozen candidate+stable-control validation.'}
    write(root/'final-baseline-analysis.json',final)
    write(root/'final-baseline-analysis.md',f"# Complete baseline at100ms per move\n\nWetMeat:{data['wins']}wins,{data['draws']}draws,{data['losses']}losses in1000paired games.\n\n"+
          '\n'.join(f"{side}: {s['checked_moves']}/{s['moves']}moves checked;{s['mistakes']}mistakes,{s['blunders']}blunders,{s['shallow_judge_moves']}shallower judge comparisons." for side,s in by.items())+
          '\n\n'+final['limits']+'\n')
    print({'status':'completed','games':1000,'wins':data['wins'],'draws':data['draws'],'losses':data['losses']})


if __name__=='__main__':main()
