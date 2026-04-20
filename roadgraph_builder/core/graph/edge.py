"""Graph edge: structural connection; centerline polyline is geometry attribute."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edge:
    """An edge connecting two nodes; polyline describes lane/road segment shape.

    ``polyline`` stores 2-tuples ``(x, y)``.  When 3D data is present the
    corresponding z-values are stored in ``attributes["polyline_z"]`` as a
    plain list of floats (one per polyline vertex) so all 2D consumers remain
    byte-identical.
    """

    id: str
    start_node_id: str
    end_node_id: str
    polyline: list[tuple[float, float]]
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        pl: list[dict[str, object]] = []
        pz: list[float] | None = None
        raw_pz = self.attributes.get("polyline_z")
        if isinstance(raw_pz, list) and len(raw_pz) == len(self.polyline):
            pz = [float(v) for v in raw_pz]
        for i, (x, y) in enumerate(self.polyline):
            pt: dict[str, object] = {"x": x, "y": y}
            if pz is not None:
                pt["z"] = pz[i]
            pl.append(pt)
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
        pz_vals: list[float] = []
        has_z = False
        for p in raw_pl:
            if not isinstance(p, dict):
                raise TypeError("polyline entries must be objects")
            polyline.append((float(p["x"]), float(p["y"])))
            if "z" in p:
                pz_vals.append(float(p["z"]))
                has_z = True
            else:
                pz_vals.append(0.0)
        attrs = data.get("attributes", {})
        if not isinstance(attrs, dict):
            raise TypeError("attributes must be a dict")
        attrs_out = {str(k): v for k, v in attrs.items()}
        if has_z:
            attrs_out["polyline_z"] = pz_vals
        return Edge(
            id=str(data["id"]),
            start_node_id=str(data["start_node_id"]),
            end_node_id=str(data["end_node_id"]),
            polyline=polyline,
            attributes=attrs_out,
        )
