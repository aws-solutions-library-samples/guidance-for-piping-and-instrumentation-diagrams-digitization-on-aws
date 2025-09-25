"""
Data models and enums for P&ID graph processing.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class GraphNodeType(Enum):
    """Enum for graph node types"""
    SYMBOL = "symbol"
    LINE = "line"
    TEXT = "text"
    JUNCTION = "junction"


class JunctionType(Enum):
    """Enum for junction types"""
    T_JUNCTION = "t_junction"
    CROSS_JUNCTION = "cross_junction"
    L_JUNCTION = "l_junction"
    UNKNOWN = "unknown"


@dataclass
class BoundingBox:
    """Represents a bounding box"""
    topX: float
    topY: float
    bottomX: float
    bottomY: float

    def to_polygon(self):
        """Convert to list of corner points"""
        return [
            [self.topX, self.topY],
            [self.bottomX, self.topY],
            [self.bottomX, self.bottomY],
            [self.topX, self.bottomY]
        ]

    def center(self):
        """Get center point of bounding box"""
        return [(self.topX + self.bottomX) / 2, (self.topY + self.bottomY) / 2]


@dataclass
class Symbol:
    """Represents a symbol detection"""
    id: str
    label: str
    class_name: str
    bbox: BoundingBox
    score: float = 0.9
    text_associated: Optional[str] = None


@dataclass
class LineSegment:
    """Represents a line segment"""
    id: str
    points: List[List[float]]
    text_associated: Optional[str] = None


@dataclass
class TextElement:
    """Represents a text detection"""
    id: str
    text: str
    bbox: BoundingBox
    score: float = 0.9


@dataclass
class ConnectionCandidate:
    """Represents a potential connection between elements"""
    node_type: GraphNodeType
    element_id: str
    distance: float


@dataclass
class Junction:
    """Represents a detected junction point"""
    id: str
    point: Tuple[float, float]  # (x, y) coordinates
    junction_type: JunctionType
    connected_lines: List[str]  # IDs of connected lines
    confidence: float = 1.0
    
    def center(self):
        """Get center point of junction (same as point for junctions)"""
        return list(self.point)
