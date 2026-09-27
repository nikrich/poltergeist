"""A connector CLI whose every account failed exits 1 cleanly (no traceback)."""
from __future__ import annotations

import pytest

from ghostbrain import accounts_health


class _AllFail:
    def health_check(self) -> bool:
        return True

    def _get_last_run(self):
        return None

    def fetch(self, since):
        raise accounts_health.AllAccountsFailedError("all gmail accounts failed: a@x.com: error (boom)")

    def run(self) -> int:
        return len(self.fetch(None))


@pytest.mark.parametrize("argv", [["ghostbrain-gmail-fetch"], ["ghostbrain-gmail-fetch", "--dry-run"]])
def test_gmail_main_exits_1_when_every_account_failed(monkeypatch, argv):
    from ghostbrain.connectors.gmail import __main__ as gmail_main
    from ghostbrain.connectors.gmail import runner

    audits: list[tuple] = []
    monkeypatch.setattr(runner, "_build", lambda routing, queue, state: _AllFail())
    monkeypatch.setattr(gmail_main, "audit_log",
                        lambda event, name, **kw: audits.append((event, name, kw)))
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        gmail_main.main()
    assert exc.value.code == 1
    assert audits == [("connector_health_failed", "gmail",
                       {"error": "all gmail accounts failed: a@x.com: error (boom)"})]
