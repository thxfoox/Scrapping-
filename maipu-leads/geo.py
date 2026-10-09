"""Geometry of the target sector in Maipú.

Av. Portales, Av. Sur and Nueva San Martín run roughly east-west and parallel, ~300-400 m apart,
so "Av. Sur con Av. Portales" is a corridor, not a corner. The sector is the band from Av. Portales
(north) to Nueva San Martín (south), from the west end of Av. Sur to El Carmen, where the corner
of Av. Sur with El Carmen (Empanadas con Amor) sits. Inside the band the distance is 0.
Polylines come from geocoded addresses on each avenue (Google Maps listings).
"""

import math

# west -> east, (lat, lng)
AV_PORTALES = [(-33.5198, -70.7953), (-33.5192, -70.7901), (-33.5185, -70.7856), (-33.5184, -70.7794),
               (-33.5179, -70.7767), (-33.5179, -70.7663), (-33.5175, -70.7645), (-33.5172, -70.7631),
               (-33.5160, -70.7595)]
AV_SUR = [(-33.5224, -70.7966), (-33.5218, -70.7871), (-33.5216, -70.7806), (-33.5217, -70.7748),
          (-33.5215, -70.7695), (-33.5209, -70.7616)]
NUEVA_SAN_MARTIN = [(-33.5250, -70.7978), (-33.5250, -70.7921), (-33.5246, -70.7883), (-33.5249, -70.7822),
                    (-33.5247, -70.7750), (-33.5245, -70.7729), (-33.5251, -70.7656), (-33.5255, -70.7637),
                    (-33.5258, -70.7595)]

NORTH, SOUTH = AV_PORTALES, NUEVA_SAN_MARTIN

# heart of the sector: Av. Sur with Av. 3 Poniente, halfway between Portales and Nueva San Martín
CENTER = (-33.5215, -70.7788)
CARMEN_CORNER = (-33.5210, -70.7640)  # Av. Sur con El Carmen

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
    """0 inside the band Av. Portales - Nueva San Martín, else distance to its edge (km)."""
    north, south = _interp_lat(NORTH, lng), _interp_lat(SOUTH, lng)
    if north is not None and south is not None and south <= lat <= north:
        return 0.0
    p = _xy(lat, lng)
    edges = [_poly_dist(p, NORTH), _poly_dist(p, SOUTH)]
    # beyond the west/east ends, the closing sides of the band count as edges too
    for i in (0, -1):
        edges.append(_seg_dist(p, _xy(*NORTH[i]), _xy(*SOUTH[i])))
    return min(edges)


def center_distance_km(lat: float, lng: float) -> float:
    x, y = _xy(lat, lng)
    return math.hypot(x, y)


# search centers inside the sector, then the neighbouring villas
SEARCH_POINTS = {
    "centro": (-33.5199, -70.7788),
    "oeste": (-33.5212, -70.7905),
    "este": (-33.5190, -70.7665),
    "carmen": (-33.5222, -70.7650),
    "nsm_centro": (-33.5240, -70.7790),
    "nsm_oeste": (-33.5240, -70.7910),
    "norte": (-33.5125, -70.7790),
    "sur": (-33.5300, -70.7790),
}
