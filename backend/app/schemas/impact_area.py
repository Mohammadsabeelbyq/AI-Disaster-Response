"""Validation and response schemas for incident impact areas."""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings

Position = tuple[
    Annotated[float, Field(ge=-180, le=180)],
    Annotated[float, Field(ge=-90, le=90)],
]
Ring = Annotated[list[Position], Field(min_length=4, max_length=501)]


def _orientation(a: Position, b: Position, c: Position) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Position, b: Position, point: Position) -> bool:
    return (min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= point[1] <= max(a[1], b[1]))


def _segments_intersect(a: Position, b: Position, c: Position, d: Position) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    if ((ab_c > 0 > ab_d or ab_d > 0 > ab_c)
            and (cd_a > 0 > cd_b or cd_b > 0 > cd_a)):
        return True
    return ((ab_c == 0 and _on_segment(a, b, c))
            or (ab_d == 0 and _on_segment(a, b, d))
            or (cd_a == 0 and _on_segment(c, d, a))
            or (cd_b == 0 and _on_segment(c, d, b)))


def _rings_intersect(first: Ring, second: Ring) -> bool:
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in zip(first, first[1:])
        for c, d in zip(second, second[1:])
    )


def _point_in_ring(point: Position, ring: Ring) -> bool:
    inside = False
    x, y = point
    for first, second in zip(ring, ring[1:]):
        if _on_segment(first, second, point) and _orientation(first, second, point) == 0:
            return False
        if (first[1] > y) != (second[1] > y):
            crossing_x = (second[0] - first[0]) * (y - first[1]) / (second[1] - first[1])
            if x < crossing_x:
                inside = not inside
    return inside


class PolygonGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Polygon"]
    coordinates: list[Ring] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_polygon(self):
        if sum(len(ring) for ring in self.coordinates) > 1000:
            raise ValueError("polygon must contain at most 1000 positions")
        for ring in self.coordinates:
            if ring[0] != ring[-1]:
                raise ValueError("each polygon ring must be closed")
            if len(set(ring[:-1])) < 3:
                raise ValueError("each polygon ring must contain at least three distinct points")
            area = sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(ring, ring[1:])
            )
            if area == 0:
                raise ValueError("polygon rings must enclose a non-zero area")
            edge_count = len(ring) - 1
            for first_index in range(edge_count):
                for second_index in range(first_index + 1, edge_count):
                    if second_index in {first_index, first_index + 1}:
                        continue
                    if first_index == 0 and second_index == edge_count - 1:
                        continue
                    if _segments_intersect(
                        ring[first_index], ring[first_index + 1],
                        ring[second_index], ring[second_index + 1],
                    ):
                        raise ValueError("polygon rings must not cross or touch themselves")

        exterior = self.coordinates[0]
        for index, ring in enumerate(self.coordinates[1:], start=1):
            if _rings_intersect(exterior, ring) or not _point_in_ring(ring[0], exterior):
                raise ValueError("polygon holes must be fully inside the exterior ring")
            for other in self.coordinates[1:index]:
                if (_rings_intersect(other, ring) or _point_in_ring(ring[0], other)
                        or _point_in_ring(other[0], ring)):
                    raise ValueError("polygon holes must not overlap")
        return self


class ImpactAreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry_type: Literal["RADIUS", "POLYGON"]
    radius_m: float | None = Field(default=None, gt=0)
    polygon: PolygonGeometry | None = None

    @field_validator("radius_m")
    @classmethod
    def validate_radius_limit(cls, value):
        if value is not None and value > get_settings().impact_max_radius_metres:
            raise ValueError(
                f"radius_m cannot exceed {get_settings().impact_max_radius_metres} metres")
        return value

    @model_validator(mode="after")
    def validate_geometry_selection(self):
        if self.geometry_type == "RADIUS" and (self.radius_m is None or self.polygon is not None):
            raise ValueError("RADIUS impact areas require radius_m and must not include polygon")
        if self.geometry_type == "POLYGON" and (self.polygon is None or self.radius_m is not None):
            raise ValueError("POLYGON impact areas require polygon and must not include radius_m")
        return self


class ImpactAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    geometry_type: Literal["RADIUS", "POLYGON"]
    radius_m: float | None
    polygon: PolygonGeometry | None
    updated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
