"""Graph edge: structural connection; centerline polyline is geometry attribute."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edge:
    """An edge connecting two nodes; polyline describes lane/road segment shape."""

    id: str
    start_node_id: str
    end_node_id: str
    polyline: list[tuple[float, float]]
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        pl = [{"x": x, "y": y} for x, y in self.polyline]
        return {
            "id": self.id,
            "start_node_id": self.start_node_id,
            "end_node_id": self.end_node_id,
            "polyline": pl,
            "attributes": dict(self.attributes),
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> "Edge":
        raw_pl = data["polyline"]
        if not isinstance(raw_pl, list):
            raise TypeError("polyline must be a list")
        polyline: list[tuple[float, float]] = []
        for p in raw_pl:
            if not isinstance(p, dict):
                raise TypeError("polyline entries must be objects")
            polyline.append((float(p["x"]), float(p["y"])))
        attrs = data.get("attributes", {})
        if not isinstance(attrs, dict):
            raise TypeError("attributes must be a dict")
        return Edge(
            id=str(data["id"]),
            start_node_id=str(data["start_node_id"]),
            end_node_id=str(data["end_node_id"]),
            polyline=polyline,
            attributes={str(k): v for k, v in attrs.items()},
        )
