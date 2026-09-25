"""Run-loop helpers for the macOS front-end tests."""

from Foundation import NSDate, NSRunLoop


def spin(seconds: float) -> None:
    """Run the main run loop so WebKit and timers make progress."""

    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def wait_for(predicate, timeout: float = 5.0) -> bool:
    waited = 0.0
    while not predicate():
        if waited >= timeout:
            return False
        spin(0.05)
        waited += 0.05
    return True


class FakeApp:
    def __init__(self):
        self.opened = []
        self.closed = []

    def open_path(self, path):
        self.opened.append(path)

    def window_closed(self, window):
        self.closed.append(window)
