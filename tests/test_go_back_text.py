"""go_back shows the location name, not an internal id (new_bug §6)."""
from __future__ import annotations

import main
from burt.loop import Action, execute_action


def _state(source: str, node_type: str) -> dict:
    st = main.make_new_state(life=1)
    st["hidden"]["day"] = 2
    st["hidden"]["step"] = 7
    st["hidden"]["current_node_id"] = "micro_1"
    st["hidden"]["micro_location"] = {
        "active": True,
        "source_node": source,
        "target_node": "micro_1",
    }
    st["hidden"]["location_graph"] = {
        source: {
            "type": node_type, "entered": True,
            "exits": {"north": "micro_1", "east": None,
                      "south": None, "west": None},
        },
        "micro_1": {
            "type": "field", "entered": True,
            "exits": {"south": source, "north": None,
                      "east": None, "west": None},
        },
    }
    st["visible"]["date"] = "2 day"
    return st


class TestGoBackText:
    def test_uses_location_name_not_id(self):
        st = _state("start", "crossroads")
        result = execute_action(Action("go_back", "Go back"), st)
        assert result.events[0] == "Return to Crossroads."
        assert "start" not in result.events[0]

    def test_no_node_id_leak(self):
        st = _state("node_5", "forest")
        result = execute_action(Action("go_back", "Go back"), st)
        assert result.events[0] == "Return to Forest."
        assert "node_" not in result.events[0]
        assert st["visible"]["location"]["name"] == "Forest"

    def test_date_is_canonical(self):
        st = _state("start", "crossroads")
        st["visible"]["date"] = "2 day(s)"  # legacy save
        execute_action(Action("go_back", "Go back"), st)
        assert st["visible"]["date"] == "2 day"
