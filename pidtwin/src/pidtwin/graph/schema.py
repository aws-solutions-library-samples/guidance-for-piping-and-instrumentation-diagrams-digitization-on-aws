"""Canonical plant graph built from digitized P&ID sheets.

Convention:
- Nodes are physical things: equipment, valves, instruments, fittings, tees, off-page connectors,
  open line ends, and pipe segments. A pipe segment runs between two adjacent non-pipe nodes, so
  every run is cut at each inline component and at each tee.
- Edges are direct contact. kind "process" = piping, "impulse" = instrument tubing (physical),
  "signal" = information only.
- Nodes carry bbox in sheet coords 0-1000. source "scene" and position (x, y, z in metres) are kept
  so a graph built from a 3D scan can use the same schema.
"""
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["equipment", "valve", "instrument", "fitting", "offpage", "tee", "end", "pipe"]
EdgeKind = Literal["process", "impulse", "signal"]
PHYSICAL = ("process", "impulse")


class Node(BaseModel):
    id: str
    category: Category
    dexpi_class: str | None = None
    type: str | None = None          # free-text kind from the digitizer / detector
    tag: str | None = None
    text: str | None = None
    line_number: str | None = None
    nominal_size: str | None = None  # e.g. '6"'
    service: str | None = None
    sheet: str | None = None
    bbox: list[float] | None = None
    position: list[float] | None = None
    confidence: float | None = None
    attrs: dict = Field(default_factory=dict)


class Edge(BaseModel):
    src: str
    dst: str
    kind: EdgeKind = "process"
    src_port: str | None = None
    dst_port: str | None = None
    run: str | None = None


class Graph(BaseModel):
    schema_version: str = "1.0"
    source: Literal["pid", "scene"] = "pid"
    sheets: list[dict] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def by_id(self):
        return {n.id: n for n in self.nodes}

    def adjacency(self, kinds=PHYSICAL):
        """Undirected neighbour sets over edges of the given kinds (self-loops dropped)."""
        adj = defaultdict(set)
        for n in self.nodes:
            adj[n.id]
        for e in self.edges:
            if e.kind in kinds and e.src != e.dst:
                adj[e.src].add(e.dst)
                adj[e.dst].add(e.src)
        return adj

    def save(self, path):
        from pathlib import Path
        Path(path).write_text(self.model_dump_json(indent=2, exclude_none=True))

    @classmethod
    def load(cls, path):
        from pathlib import Path
        return cls.model_validate_json(Path(path).read_text())
