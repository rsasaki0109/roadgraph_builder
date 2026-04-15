"""Graph node: structural junction/endpoint. Geometry is an attribute."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    """A node in the road graph (intersection, branch, or connectivity point)."""

    id: str
    position: tuple[float, float]
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        x, y = self.position
        out: dict[str, object] = {"id": self.id, "position": {"x": x, "y": y}}
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        return out

    @staticmethod
    def from_dict(data: dict[str, object]) -> "Node":
        pos = data["position"]
        if not isinstance(pos, dict):
            raise TypeError("position must be a dict")
        attrs = data.get("attributes", {})
        if not isinstance(attrs, dict):
            raise TypeError("attributes must be a dict")
        return Node(
            id=str(data["id"]),
            position=(float(pos["x"]), float(pos["y"])),
            attributes={str(k): v for k, v in attrs.items()},
        )
