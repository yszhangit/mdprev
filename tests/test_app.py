import mdprev.app as app_module


def test_main_forwards_process_arguments(monkeypatch):
    received = []

    class FakeApplication:
        def run(self, argv):
            received.extend(argv)
            return 0

    monkeypatch.setattr(app_module, "MdPrevApplication", FakeApplication)
    monkeypatch.setattr(app_module.sys, "argv", ["mdprev", "/tmp/example.md"])

    assert app_module.main() == 0
    assert received == ["mdprev", "/tmp/example.md"]
