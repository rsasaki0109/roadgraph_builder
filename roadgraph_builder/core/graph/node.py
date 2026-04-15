"""Graph node: structural junction/endpoint. Geometry is an attribute."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Node:
    """A node in the road graph (intersection, branch, or connectivity point)."""

    id: str
    position: tuple[float, float]

    def to_dict(self) -> dict[str, object]:
        x, y = self.position
        return {"id": self.id, "position": {"x": x, "y": y}}

    @staticmethod
    def from_dict(data: dict[str, object]) -> "Node":
        pos = data["position"]
        if not isinstance(pos, dict):
            raise TypeError("position must be a dict")
        return Node(
            id=str(data["id"]),
            position=(float(pos["x"]), float(pos["y"])),
        )
