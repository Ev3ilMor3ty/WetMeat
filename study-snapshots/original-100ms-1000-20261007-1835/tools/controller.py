"""Finite1000-game queue; findings are preserved, never hidden. GPL-3.0-or-later."""
import queue_runtime as runtime
from evidence import progress

runtime.progress = progress

if __name__ == '__main__':
    runtime.main()
