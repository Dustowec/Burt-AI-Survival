"""§33: the faith status in the sensory report (neutral is hidden)."""
from __future__ import annotations

from burt import faith
import main
from burt import sensory


def _visible():
    st = main.make_new_state(life=1)
    return st["visible"]


class TestFaithStatusLine:
    def test_neutral_is_hidden(self):
        report = sensory.format_sensory_report(_visible())
        assert "Faith:" not in report

    def test_paladin_is_visible(self):
        st = main.make_new_state(life=1)
        faith.set_status(st, faith.STATUS_PALADIN)
        report = sensory.format_sensory_report(st["visible"])
        assert "Faith: paladin" in report

    def test_killer_is_visible(self):
        st = main.make_new_state(life=1)
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_HERETIC)
        report = sensory.format_sensory_report(st["visible"])
        assert "Faith: killer" in report
        faith_line = next(
            line for line in report.splitlines() if line.startswith("Faith:")
        )
        assert faith_line == "Faith: killer"

    def test_heretic_is_visible(self):
        st = main.make_new_state(life=1)
        faith.set_status(st, faith.STATUS_HERETIC)
        report = sensory.format_sensory_report(st["visible"])
        assert "Faith: heretic" in report