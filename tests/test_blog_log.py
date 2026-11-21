"""Blog chronicle: markdown, one block per turn (see burt/blog_log.py)."""
from __future__ import annotations

from datetime import datetime

from burt.blog_log import BlogLog, split_narrative
from burt.trace import Trace

FIXED = datetime(2026, 11, 22, 22, 54, 21)


def _blog(tmp_path, **kwargs):
    params = dict(trace=Trace(session_uuid="blog-session"), clock=lambda: FIXED)
    params.update(kwargs)
    return BlogLog(tmp_path / "blog.md", **params)


def _read(log) -> str:
    return log.path.read_text(encoding="utf-8")


STATUS = (
    "[STATE]\nHP: 5/10 | MP: 3/3\nLevel: 1 | XP: 5/10\n"
    "Fed: no (hungry)\nDate: 1 day\n\n"
    "[LOCATION]\nRiver\nExits: north, south\n\n"
    "[HANDS]\nBread — 2pcs\n\n[WALLET]\n50 coin\n\n[SKILLS]\nempty"
)


# ─── helpers ───────────────────────────────────────────────


class TestSplitNarrative:
    def test_choice_is_separated(self):
        text, choice = split_narrative(
            "I walk north.\n\nCHOICE: 1"
        )
        assert text == "I walk north."
        assert choice == "1"

    def test_no_choice(self):
        text, choice = split_narrative("Just words.")
        assert text == "Just words."
        assert choice == ""

    def test_empty(self):
        assert split_narrative("") == ("", "")


class TestCompact:
    def test_only_state_lines(self):
        from burt.blog_log import _compact

        line = _compact(STATUS)
        assert line.startswith("HP: 5/10 | MP: 3/3")
        assert "Date: 1 day" in line
        assert "Bread" not in line      # inventory is not status
        assert "River" not in line      # location has its own heading
        assert "[STATE]" not in line


# ─── header ───────────────────────────────────────────────


class TestStart:
    def test_header_written_once(self, tmp_path):
        log = _blog(tmp_path)
        log.start(life=1, max_steps=150, model="local-model")
        log.start(life=1, max_steps=150)
        text = _read(log)
        assert text.startswith("# BURT — run 2026-11-22 22:54:21")
        assert text.count("# BURT") == 1
        assert "- life: **1**" in text
        assert "planned steps: 150" in text
        assert "blog-session" in text

    def test_parent_dirs_created(self, tmp_path):
        log = BlogLog(tmp_path / "nested" / "blog.md")
        log.start(life=1)
        assert (tmp_path / "nested" / "blog.md").is_file()


# ─── turn ─────────────────────────────────────────────────


class TestTurn:
    def test_turn_block(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=8, mode="exploring", location="River",
            status_before=STATUS, status_after=STATUS,
            response="The ground feels firm.\n\nCHOICE: 1",
            action_key="go_forward", action_label="Go forward",
            event="You hit a fallen log.",
        )
        text = _read(log)
        assert "## 2026-11-22 22:54:21 · day 1 · step 8 · River" in text
        assert "**Status:** HP: 5/10 | MP: 3/3" in text
        assert "**Event:** You hit a fallen log." in text
        assert "> The ground feels firm." in text
        assert "**Choice:** `go_forward` — Go forward" in text
        assert "**Model said:** `1`" in text
        assert "**After:** HP: 5/10" in text
        # the CHOICE line is not quoted as narrative
        assert "> CHOICE" not in text

    def test_combat_mode_in_heading(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=2, mode="combat", location="Thicket",
            status_before=STATUS, status_after=STATUS,
            response="I strike.\nCHOICE: 0",
            action_key="attack_young_goblin_1",
            action_label="Attack young goblin",
        )
        assert "· Thicket · COMBAT" in _read(log)

    def test_tool_is_folded(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=2, mode="exploring", location="River",
            status_before=STATUS, status_after=STATUS,
            response="I check my things.\nCHOICE: 4",
            action_key="inventory", action_label="Inventory",
            folded=True,
        )
        text = _read(log)
        assert "**Action:** _checked his belongings_" in text
        assert "**Choice:**" not in text

    def test_multi_line_narrative_is_quoted(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=1, mode="exploring", location="Field",
            status_before=STATUS, status_after=STATUS,
            response="First line.\nSecond line.\nCHOICE: 1",
            action_key="go_north", action_label="Go north",
        )
        text = _read(log)
        assert "> First line.\n> Second line." in text

    def test_no_event_no_combat_lines(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=1, mode="exploring", location="Field",
            status_before=STATUS, status_after=STATUS,
            response="I walk.\nCHOICE: 1",
            action_key="go_north", action_label="Go north",
        )
        text = _read(log)
        assert "**Event:**" not in text
        assert "**Combat:**" not in text


# ─── combat / death / epitaph / diary ─────────────────────


class TestSpecialBlocks:
    def test_combat_start_ambush(self, tmp_path):
        log = _blog(tmp_path)
        log.combat_start(
            ambush=True, enemies="young goblin", initiative="enemy",
            status=STATUS,
        )
        text = _read(log)
        assert "### ⚔ Combat — ambush" in text
        assert "enemies: young goblin" in text
        assert "initiative: enemy" in text
        assert "- status: HP: 5/10" in text

    def test_combat_start_encounter(self, tmp_path):
        log = _blog(tmp_path)
        log.combat_start(ambush=False, enemies="wolf", initiative="burt",
                         status=STATUS)
        assert "### ⚔ Combat — encounter" in _read(log)

    def test_death(self, tmp_path):
        log = _blog(tmp_path)
        log.death(life=1, day=1, step=8, cause="hunger", location="River")
        text = _read(log)
        assert "## ☠ Death — life 1 · day 1 · step 8" in text
        assert "- cause: **hunger**" in text
        assert "- location: River" in text

    def test_epitaph_is_quoted(self, tmp_path):
        log = _blog(tmp_path)
        log.epitaph(life=1, days=1, cause="hunger",
                    text="I carried bread and did not eat it.")
        text = _read(log)
        assert "### 🪦 Epitaph — life 1 (1 days, hunger)" in text
        assert "> I carried bread and did not eat it." in text

    def test_diary_is_quoted(self, tmp_path):
        log = _blog(tmp_path)
        log.diary(day=3, text="I walked all day.")
        text = _read(log)
        assert "### 📖 Diary — day 3" in text
        assert "> I walked all day." in text

    def test_resurrection_and_new_life(self, tmp_path):
        log = _blog(tmp_path)
        log.resurrection(hp=2)
        log.new_life(life=2, memory="I learned.")
        text = _read(log)
        assert "### ✨ Resurrected" in text
        assert "- HP: 2" in text
        assert "## 🔄 New life — 2" in text
        assert "- memory: **yes**" in text

    def test_new_life_without_memory(self, tmp_path):
        log = _blog(tmp_path)
        log.new_life(life=2, memory=None)
        assert "- memory: **no**" in _read(log)


# ─── robustness ───────────────────────────────────────────


class TestRobustness:
    def test_close_stops_writing(self, tmp_path):
        log = _blog(tmp_path)
        log.turn(
            day=1, step=1, mode="exploring", location="Field",
            status_before=STATUS, status_after=STATUS,
            response="x\nCHOICE: 1", action_key="go_north",
            action_label="Go north",
        )
        before = _read(log)
        log.close()
        log.diary(day=1, text="after close")
        assert _read(log) == before

    def test_unwritable_path_does_not_raise(self, tmp_path):
        # A directory where the file should be: OSError is swallowed.
        bad = tmp_path / "blog.md"
        bad.mkdir()
        log = BlogLog(bad)
        log.start(life=1)   # must not raise
