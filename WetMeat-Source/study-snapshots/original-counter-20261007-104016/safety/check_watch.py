"""Check exact guard identity and orphan scope. GPL-3.0-or-later."""
from watch import observe

root = {'pid': 10, 'birth': '100', 'command': ['python', 'counter_queue.py']}
child = {'pid': 11, 'birth': '101', 'command': ['python', 'trial_clock.py']}
table = {
    10: {'birth': '100', 'args': root['command'], 'ppid': 1},
    11: {'birth': '101', 'args': child['command'], 'ppid': 10},
    12: {'birth': '102', 'args': ['stockfish'], 'ppid': 11},
    99: {'birth': '200', 'args': ['stockfish'], 'ppid': 1},
}
known = {}
assert observe(table, root, {'child': child}, [child['command']], known) == {10, 11, 12}
assert 99 not in known
orphaned = {12: dict(table[12], ppid=1), 99: table[99]}
assert observe(orphaned, root, {}, [], known) == {12}
reused = {12: dict(table[12], birth='new'), 99: table[99]}
assert not observe(reused, root, {}, [], known)
assert not observe(table, dict(root, command=['unrelated']), {}, [], {})
print('4 exact-identity/orphan/unrelated-process scope checks passed; no engines launched.')
