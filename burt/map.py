"""Player map of the current life -- spec 17.

Burt remembers only what he has seen, so the map shows visited nodes and
one ring of fog (`??`) around them. The current node is marked <..>.

Quest marks come from the quest journal: a node where a quest was taken
carries its tag, e.g. `[RD](Q1)`. No target hints, no giver roles.

Pure core: reads state, returns a string. No I/O, no asyncio, no LLM.
"""
from __future__ import annotations

from collections import deque

DIRECTIONS = ("north", "east", "south", "west")
_DELTA = {
    "north": (0, -1),
    "east": (1, 0),
    "south": (0, 1),
    "west": (-1, 0),
}

# Two letters per location type: a map must stay narrow.
SHORT = {
    "crossroads": "CR",
    "road": "RD",
    "thicket": "TH",
    "forest": "FR",
    "field": "FL",
    "steppe": "ST",
    "swamp": "SW",
    "river": "RV",
    "village": "VL",
    "temple": "TP",
    "dungeon": "DG",
}


def layout(graph: dict, start: str = "start") -> dict[str, tuple[int, int]]:
    """Grid coordinates: start is (0, 0), north is (0, -1).

    Exits are absolute compass directions and links are symmetric, so a
    node is only created in a free direction: two nodes can never land on
    the same cell. Unreachable nodes are left out.
    """
    if start not in graph:
        return {}
    pos: dict[str, tuple[int, int]] = {start: (0, 0)}
    queue = deque([start])
    while queue:
        node_id = queue.popleft()
        x, y = pos[node_id]
        exits = (graph.get(node_id) or {}).get("exits") or {}
        for direction, (dx, dy) in _DELTA.items():
            neighbour = exits.get(direction)
            if not neighbour or neighbour in pos or neighbour not in graph:
                continue
            pos[neighbour] = (x + dx, y + dy)
            queue.append(neighbour)
    return pos


def quest_marks(hidden: dict) -> dict[str, list[str]]:
    """node_id -> [Q1, Q2, ...] from the quest journal."""
    marks: dict[str, list[str]] = {}
    for entry in hidden.get("quests_raw") or []:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag")
        node = entry.get("giver_node")
        if not tag or not node:
            continue
        status = entry.get("status")
        if status == "completed":
            tag = tag + "v"
        elif status == "failed":
            tag = tag + "x"
        marks.setdefault(node, []).append(tag)
    return marks


def _label(node: dict, current: bool, marks: list[str],
           explored: bool = True) -> str:
    """One cell. An unexplored node is fog: its type stays a secret."""
    node_type = node.get("type")
    short = SHORT.get(node_type or "", "??") if explored else "??"
    cell = f"<{short}>" if current else f"[{short}]"
    if marks:
        cell += "(" + ",".join(marks) + ")"
    return cell


def _place_name(graph: dict, node_id: str) -> str:
    """Human name of a node for the legend (Road, River, ...)."""
    node_type = (graph.get(node_id) or {}).get("type")
    if not node_type:
        return node_id
    return node_type.capitalize()


def _linked(graph: dict, at: dict, a: tuple, b: tuple) -> bool:
    """Are two adjacent grid cells joined by an exit?"""
    na = at.get(a)
    nb = at.get(b)
    if na is None or nb is None:
        return False
    exits = (graph.get(na) or {}).get("exits") or {}
    return nb in exits.values()


def render_ascii(state: dict) -> str:
    """The player map: visited nodes, one ring of fog, quest tags."""
    hidden = state.get("hidden", {})
    graph = hidden.get("location_graph") or {}
    current = hidden.get("current_node_id", "start")
    marks = quest_marks(hidden)

    pos = layout(graph, current if current in graph else "start")
    if not pos:
        return "[MAP]\nNo map yet.\n"

    # Visited nodes plus one ring of fog around them.
    visible: set[str] = set()
    for node_id, node in graph.items():
        if node_id not in pos or not node.get("entered"):
            continue
        visible.add(node_id)
        for direction in DIRECTIONS:
            neighbour = (node.get("exits") or {}).get(direction)
            if neighbour and neighbour in pos:
                visible.add(neighbour)
    if current in pos:
        visible.add(current)

    at: dict[tuple, str] = {pos[nid]: nid for nid in visible}
    grid: dict[tuple, str] = {}
    for node_id in visible:
        node = graph.get(node_id) or {}
        grid[pos[node_id]] = _label(
            node, node_id == current, marks.get(node_id, []),
            explored=bool(node.get("entered")),
        )

    xs = [x for x, _ in grid]
    ys = [y for _, y in grid]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    width: dict[int, int] = {}
    for x in range(x0, x1 + 1):
        column = [len(grid[(x, y)]) for y in range(y0, y1 + 1)
                  if (x, y) in grid]
        width[x] = max(column) if column else 4

    lines = ["[MAP]"]
    for y in range(y0, y1 + 1):
        row = ""
        for x in range(x0, x1 + 1):
            row += grid.get((x, y), "").ljust(width[x])
            if x < x1:
                row += "-" if _linked(graph, at, (x, y), (x + 1, y)) else " "
        lines.append(row.rstrip())
        if y < y1:
            row = ""
            for x in range(x0, x1 + 1):
                if _linked(graph, at, (x, y), (x, y + 1)):
                    # keep the line under the box, marks hang to the right
                    row += "|".center(4) + " " * (width[x] - 4)
                else:
                    row += " " * width[x]
                if x < x1:
                    row += " "
            lines.append(row.rstrip())

    lines.append("")
    lines.append("<..> you are here   [..] visited   [??] unexplored")
    for entry in hidden.get("quests_raw") or []:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag")
        node_id = entry.get("giver_node")
        if not tag or not node_id:
            continue
        title = entry.get("title", entry.get("id", "?"))
        status = entry.get("status")
        suffix = ""
        if status and status != "active":
            suffix = f" [{status}]"
        lines.append(
            f"{tag} {title} -- taken at {_place_name(graph, node_id)}{suffix}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    from pathlib import Path

    state_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state.json")
    print(render_ascii(json.loads(state_path.read_text(encoding="utf-8"))))
