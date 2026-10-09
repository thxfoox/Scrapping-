"""Geometry of the target sector: the band between Av. Portales (north) and Av. Sur (south).

Both avenues run roughly east-west and parallel (~250-400 m apart), so "Av. Sur con Av. Portales"
is a corridor, not a corner. Distances are measured to that band; inside it the distance is 0.
Points were read off Google Maps (street pins, bus stops and numbered addresses on each avenue).
"""

import math

# west -> east, (lat, lng)
AV_PORTALES = [(-33.5201, -70.7962), (-33.5182, -70.7789), (-33.5167, -70.7593)]
AV_SUR = [(-33.5224, -70.7966), (-33.5216, -70.7787), (-33.5206, -70.7624)]

# heart of the corridor: midpoint between both avenues at Av. 3 Poniente
CENTER = (-33.5199, -70.7788)

KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LNG = 111.32 * math.cos(math.radians(33.52))


def _xy(lat, lng):
    return (lng - CENTER[1]) * KM_PER_DEG_LNG, (lat - CENTER[0]) * KM_PER_DEG_LAT


def _seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1e-12)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _poly_dist(p, line):
    pts = [_xy(*q) for q in line]
    return min(_seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _interp_lat(line, lng):
    for (la1, ln1), (la2, ln2) in zip(line, line[1:]):
        if ln1 <= lng <= ln2:
            t = (lng - ln1) / (ln2 - ln1)
            return la1 + t * (la2 - la1)
    return None


def band_distance_km(lat: float, lng: float) -> float:
    """0 inside the band between both avenues, else distance to the nearest avenue (km)."""
    north, south = _interp_lat(AV_PORTALES, lng), _interp_lat(AV_SUR, lng)
    if north is not None and south is not None and south <= lat <= north:
        return 0.0
    p = _xy(lat, lng)
    return min(_poly_dist(p, AV_PORTALES), _poly_dist(p, AV_SUR))


def center_distance_km(lat: float, lng: float) -> float:
    x, y = _xy(lat, lng)
    return math.hypot(x, y)


# search centers along the corridor, then the neighbouring villas north and south
SEARCH_POINTS = {
    "centro": CENTER,
    "oeste": (-33.5212, -70.7905),
    "este": (-33.5190, -70.7665),
    "norte": (-33.5125, -70.7790),
    "sur": (-33.5280, -70.7790),
    "noroeste": (-33.5140, -70.7930),
    "noreste": (-33.5115, -70.7650),
    "suroeste": (-33.5290, -70.7930),
    "sureste": (-33.5275, -70.7650),
}
