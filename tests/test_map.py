"""Player map (spec 17): layout, fog, quest marks, current node."""
from __future__ import annotations

from burt import map as map_mod


def _node(node_type, entered, **exits):
    full = {d: None for d in map_mod.DIRECTIONS}
    full.update(exits)
    return {"type": node_type, "entered": entered, "exits": full}


def _state(graph, current="start", quests=None):
    return {"hidden": {
        "location_graph": graph,
        "current_node_id": current,
        "quests_raw": quests or [],
    }}


def _start_graph():
    return {
        "start": _node("crossroads", True,
                       north="road", east="thicket",
                       south="forest", west="river"),
        "road": _node("road", True, south="start"),
        "thicket": _node("thicket", False, west="start"),
        "forest": _node("forest", False, north="start"),
        "river": _node("river", False, east="start"),
    }


class TestLayout:
    def test_start_is_origin(self):
        pos = map_mod.layout(_start_graph())
        assert pos["start"] == (0, 0)
        assert pos["road"] == (0, -1)
        assert pos["thicket"] == (1, 0)
        assert pos["forest"] == (0, 1)
        assert pos["river"] == (-1, 0)

    def test_missing_start(self):
        assert map_mod.layout({}) == {}

    def test_no_collisions(self):
        graph = _start_graph()
        graph["road"]["exits"]["east"] = "n2"
        graph["n2"] = _node("field", True, west="road")
        pos = map_mod.layout(graph)
        assert len(pos) == len(graph)
        assert len(set(pos.values())) == len(pos)


class TestQuestMarks:
    def test_active_completed_failed(self):
        hidden = {"quests_raw": [
            {"tag": "Q1", "giver_node": "road", "status": "active"},
            {"tag": "Q2", "giver_node": "road", "status": "completed"},
            {"tag": "Q3", "giver_node": "forest", "status": "failed"},
        ]}
        marks = map_mod.quest_marks(hidden)
        assert marks["road"] == ["Q1", "Q2v"]
        assert marks["forest"] == ["Q3x"]

    def test_entries_without_tag_or_node_are_skipped(self):
        hidden = {"quests_raw": [
            {"giver_node": "road"},
            {"tag": "Q9"},
            "junk",
        ]}
        assert map_mod.quest_marks(hidden) == {}


class TestRender:
    def test_header_and_legend(self):
        text = map_mod.render_ascii(_state(_start_graph()))
        assert text.startswith("[MAP]")
        assert "you are here" in text
        assert "unexplored" in text

    def test_current_node_marker(self):
        text = map_mod.render_ascii(_state(_start_graph()))
        assert "<CR>" in text
        text = map_mod.render_ascii(_state(_start_graph(), current="road"))
        assert "<RD>" in text
        assert "<CR>" not in text

    def test_unvisited_nodes_are_fog(self):
        text = map_mod.render_ascii(_state(_start_graph()))
        assert "[??]" in text          # thicket / forest / river
        assert "[TH]" not in text

    def test_visited_node_is_shown(self):
        text = map_mod.render_ascii(_state(_start_graph()))
        assert "[RD]" in text

    def test_quest_tag_on_the_node(self):
        quests = [{"tag": "Q1", "giver_node": "road", "status": "active",
                   "title": "Into the Forest"}]
        text = map_mod.render_ascii(_state(_start_graph(), quests=quests))
        assert "[RD](Q1)" in text
        assert "Q1 Into the Forest -- taken at Road" in text

    def test_links_are_drawn(self):
        text = map_mod.render_ascii(_state(_start_graph()))
        assert "|" in text
        assert "-" in text

    def test_no_graph(self):
        assert map_mod.render_ascii({"hidden": {}}) == "[MAP]\nNo map yet.\n"

    def test_distant_unvisited_node_is_hidden(self):
        graph = _start_graph()
        graph["road"]["exits"]["north"] = "far"
        graph["far"] = _node("dungeon", False, south="road")
        text = map_mod.render_ascii(_state(graph))
        assert "[DG]" not in text      # not visited: only its box is fog
        assert text.count("[??]") >= 1
