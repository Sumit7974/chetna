"""Safe-route planning interface for B2 Day 3/4 integration."""

from abc import ABC, abstractmethod
from typing import List, Tuple

class RouteService(ABC):
    """Abstract interface for safe routing requests."""

    @abstractmethod
    def find_safe_route(
        self,
        start_coord: Tuple[float, float],
        end_coord: Tuple[float, float],
        avoid_polygons: List[List[Tuple[float, float]]]
    ) -> List[Tuple[float, float]]:
        """
        Calculate a route avoiding specified hazard polygons.
        Returns a list of coordinates (lat, lon) forming the path.
        """
        pass

class BasicRouter(RouteService):
    """Basic fallback router (no complex A* implementation yet)."""

    def find_safe_route(
        self,
        start_coord: Tuple[float, float],
        end_coord: Tuple[float, float],
        avoid_polygons: List[List[Tuple[float, float]]]
    ) -> List[Tuple[float, float]]:
        # Placeholder: Return direct line between start and end
        return [start_coord, end_coord]
