"""Stamp every line a local-fleet role prints with its UTC emission time.

`scripts/local_production.py` puts this directory first on the roles'
`PYTHONPATH`, so Python imports it at startup, before the role's own code.
Render stamped every log line; the fleet writes raw stdout to a file, and on
2026-10-02 only 1.5-2.6% of worker lines carried any time of their own, which
left `scripts/render_logs.py --local` guessing. Each line now starts with
`2026-10-02T14:36:49.123Z ` -- the exact prefix `render_logs` treats as EXACT.

Done INSIDE the role and not with a pipe through the supervisor on purpose:
roles can outlive a supervisor crash (`down` reaps them as orphans), and a
pipe would turn that crash into a broken-pipe error on the role's next print
-- killing an in-flight sim. Here the role keeps writing to its own file.

Only writes through `sys.stdout` / `sys.stderr` are stamped (print, logging,
tracebacks). Bytes written to `.buffer` or straight to fd 1 by a non-Python
child are not, and `render_logs` reads those as APPROXIMATE, never as exact.

This shadows the distro's own `sitecustomize` (Ubuntu's apport hook) for the
roles only. Off switch: `SYNDICATE_LOCAL_LOG_TIMESTAMPS=0`, read here AND by
the supervisor.
"""

from __future__ import annotations

import datetime as _dt
import os as _os
import sys as _sys
import threading as _threading


class StampedStream:
    """A text stream that writes `<UTC ISO>Z ` at the start of every line."""

    def __init__(self, stream, clock=None) -> None:
        self._stream = stream
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._lock = _threading.Lock()
        self._at_line_start = True

    def _stamp(self) -> str:
        return self._clock().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z "

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            out = []
            for piece in text.splitlines(keepends=True):
                if self._at_line_start:
                    out.append(self._stamp())
                out.append(piece)
                self._at_line_start = piece.endswith(("\n", "\r"))
            self._stream.write("".join(out))
        return len(text)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name):
        # fileno, isatty, encoding, buffer, reconfigure ... -> the real stream.
        return getattr(self._stream, name)


def _feeds_a_parent(stream) -> bool:
    """True when the stream is a pipe or socket, i.e. a parent is reading it.

    The stamp is for LOG FILES. Every Python child inherits this PYTHONPATH, so
    without this check a child whose stdout a parent captures and parses as data
    got stamped too: measured 2026-10-02, `live_refresh_loop`'s MLB live probe
    logged `bad_json:'2026-10-02T21:32:52.433Z {"live_game_pks": []}'` 79 times and
    reported MLB never live, and every odds run file lost its parsed result. Roles
    write to a file the supervisor opened (`stdout=handle`), so they keep their
    stamps; a captured child's lines reach the log through its parent, which
    stamps them as it echoes them. Unknown (no fileno) counts as not a pipe.
    """
    import stat as _stat

    try:
        mode = _os.fstat(stream.fileno()).st_mode
    except Exception:
        return False
    return _stat.S_ISFIFO(mode) or _stat.S_ISSOCK(mode)


def install() -> bool:
    if _os.environ.get("SYNDICATE_LOCAL_LOG_TIMESTAMPS", "1").strip() == "0":
        return False
    for name in ("stdout", "stderr"):
        stream = getattr(_sys, name, None)
        if stream is not None and not isinstance(stream, StampedStream) and not _feeds_a_parent(stream):
            setattr(_sys, name, StampedStream(stream))
    return True


install()
