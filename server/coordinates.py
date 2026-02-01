"""Coordinate conversion: touch panel pixels to geographic lat/long.

Uses equirectangular (Plate Carree) projection where the conversion is linear.
"""

import logging

logger = logging.getLogger(__name__)


class CoordinateConverter:
    def __init__(self, config: dict):
        # Touch panel range
        self.touch_min_x = config.get("touch_min_x", 0)
        self.touch_max_x = config.get("touch_max_x", 1024)
        self.touch_min_y = config.get("touch_min_y", 0)
        self.touch_max_y = config.get("touch_max_y", 600)

        # Map geographic bounds
        self.map_north = config.get("map_north", 90)
        self.map_south = config.get("map_south", -90)
        self.map_west = config.get("map_west", -180)
        self.map_east = config.get("map_east", 180)

    def pixel_to_latlon(self, x: int, y: int) -> tuple[float, float]:
        """Convert touch pixel coordinates to (latitude, longitude).

        Returns (lat, lon) where lat is in [-90, 90] and lon is in [-180, 180].
        """
        touch_width = self.touch_max_x - self.touch_min_x
        touch_height = self.touch_max_y - self.touch_min_y

        # Normalize to [0, 1]
        norm_x = (x - self.touch_min_x) / touch_width
        norm_y = (y - self.touch_min_y) / touch_height

        # Clamp to valid range
        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))

        # Map to geographic coordinates
        # X axis: west to east (left to right)
        longitude = self.map_west + norm_x * (self.map_east - self.map_west)
        # Y axis: north to south (top to bottom)
        latitude = self.map_north - norm_y * (self.map_north - self.map_south)

        logger.debug("Pixel (%d, %d) -> (%.4f, %.4f)", x, y, latitude, longitude)
        return latitude, longitude
