"""Watch one file for changes, including editors that replace it on save.

A background thread waits on kqueue for events on the file and on its parent
directory (which reports the renames and creations of an atomic save), then
reports on the main thread.  Bursts are not coalesced here; the window
debounces them, as the GTK front end does.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import select
import threading

from PyObjCTools import AppHelper

_FILE_EVENTS = (
    select.KQ_NOTE_WRITE
    | select.KQ_NOTE_EXTEND
    | select.KQ_NOTE_ATTRIB
    | select.KQ_NOTE_DELETE
    | select.KQ_NOTE_RENAME
    | select.KQ_NOTE_REVOKE
)
_GONE = select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE
# How often the thread checks whether it has been stopped.
_POLL_SECONDS = 0.5


def _open(path: Path) -> int | None:
    try:
        return os.open(path, os.O_EVTONLY)
    except OSError:
        return None


def _signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size


class FileWatcher:
    """Call on_change on the main thread whenever path may have changed."""

    def __init__(self, path: Path, on_change: Callable[[], None]):
        self._path = path
        self._on_change = on_change
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"mdprev-watch {path.name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop reporting at once; the thread exits within _POLL_SECONDS."""

        self._stopped.set()

    def _deliver(self) -> None:
        if not self._stopped.is_set():
            self._on_change()

    def _watch(self, kq: select.kqueue, fd: int | None, events: int) -> None:
        if fd is not None:
            kq.control(
                [select.kevent(
                    fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=events,
                )],
                0,
            )

    def _run(self) -> None:
        kq = select.kqueue()
        dir_fd = _open(self._path.parent)
        file_fd = _open(self._path)
        self._watch(kq, dir_fd, select.KQ_NOTE_WRITE)
        self._watch(kq, file_fd, _FILE_EVENTS)
        last = _signature(self._path)
        try:
            while not self._stopped.is_set():
                events = kq.control(None, 8, _POLL_SECONDS)
                if not events:
                    continue
                changed = False
                reopen = file_fd is None
                for event in events:
                    if event.ident == file_fd:
                        changed = True
                        reopen = reopen or bool(event.fflags & _GONE)
                current = _signature(self._path)
                # A directory event matters only when it touched this file:
                # created, replaced, or removed.
                if current != last:
                    changed = True
                    if current is None or last is None or current[:2] != last[:2]:
                        reopen = True
                last = current
                if reopen:
                    # Closing the descriptor also removes its kqueue event.
                    if file_fd is not None:
                        os.close(file_fd)
                    file_fd = _open(self._path)
                    self._watch(kq, file_fd, _FILE_EVENTS)
                if changed:
                    AppHelper.callAfter(self._deliver)
        finally:
            for fd in (file_fd, dir_fd):
                if fd is not None:
                    os.close(fd)
            kq.close()
