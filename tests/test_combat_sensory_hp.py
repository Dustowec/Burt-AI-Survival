"""Combat sensory report shows Burt's HP and MP (new_bug §5)."""
from __future__ import annotations

import config
import main
from burt import loop, sensory
from burt.bestiary import ENEMIES
from burt.combat import BurtStats, CombatState, EnemyInstance


def _enemy(key: str = "wolf") -> EnemyInstance:
    t = ENEMIES[key]
    return EnemyInstance(
        id=f"{key}_1", key=key,
        hp=t.hp_max, hp_max=t.hp_max,
        mp=t.mp_max, mp_max=t.mp_max, alive=True,
    )


def _burt(hp: int = 6, mp: int = 2) -> BurtStats:
    return BurtStats(hp=hp, hp_max=10, mp=mp, mp_max=3)


def _report(hp: int = 6, mp: int = 2) -> str:
    combat = CombatState(enemies=[_enemy()], initiative="burt")
    return sensory.format_combat_report(combat, _burt(hp, mp))


class TestFormat:
    def test_hp_mp_line_is_second(self):
        lines = _report(6, 2).splitlines()
        assert lines[0] == "[COMBAT]"
        assert lines[1] == "HP: 6/10 | MP: 2/3"

    def test_hp_mp_before_enemy(self):
        out = _report(6, 2)
        assert out.index("HP:") < out.index("Enemy:")

    def test_changes_after_damage(self):
        assert "HP: 6/10" in _report(6, 2)
        assert "HP: 4/10" in _report(4, 2)
        assert "HP: 4/10" not in _report(6, 2)

    def test_mp_always_numbers(self, monkeypatch):
        monkeypatch.setattr(config, "HP_DISPLAY", "qualitative")
        out = _report(2, 1)
        assert "HP: critical" in out
        assert "MP: 1/3" in out


class TestFreeStrike:
    def test_opening_report_reflects_free_strike(self):
        st = main.make_new_state(life=1)
        result = loop._start_combat(
            ["wolf"], "enemy", st["hidden"], st["visible"], lambda: 6,
        )
        joined = "\n".join(result.events)
        hp = st["visible"]["hp"]
        assert hp < st["visible"]["hp_max"]
        assert f"HP: {hp}/{st['visible']['hp_max']}" in joined
        assert f"MP: {st['visible']['mp']}/{st['visible']['mp_max']}" in joined
