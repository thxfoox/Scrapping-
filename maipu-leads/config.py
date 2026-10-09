"""Search configuration for the Maipú leads scraper."""

# Av. Sur con Av. Portales, Maipú. Overwritten by `scrape_maps.py geocode`, which
# stores the exact point in data/center.json.
CENTER = {"lat": -33.4995, "lng": -70.7560, "label": "Av. Sur con Av. Portales, Maipú"}

COMUNA = "Maipú"

# Rubro shown in the report -> Google Maps search terms.
RUBROS = {
    "Restaurantes": ["restaurante", "restaurant comida casera"],
    "Pizzerías": ["pizzería"],
    "Sushi": ["sushi"],
    "Comida rápida": ["comida rápida", "completos", "hamburguesas"],
    "Sangucherías": ["sanguchería", "fuente de soda"],
    "Cafeterías": ["cafetería"],
    "Pastelerías": ["pastelería", "tortas"],
    "Panaderías": ["panadería"],
    "Minimarkets": ["minimarket", "almacén"],
    "Botillerías": ["botillería"],
    "Peluquerías": ["peluquería"],
    "Barberías": ["barbería"],
    "Centros de estética": ["centro de estética", "manicure uñas", "depilación"],
    "Tiendas de barrio": ["bazar", "ferretería", "verdulería", "librería", "carnicería"],
}

# Rings of search points around the center, in km. Ring 0 is the center itself;
# later rings are only searched when the closer ones don't give enough leads.
RINGS_KM = [0.0, 0.9, 1.8]
RING_BEARINGS = [0, 90, 180, 270, 45, 135, 225, 315]

SEARCH_ZOOM = 16
MAX_RESULTS_PER_SEARCH = 60
DETAIL_RADIUS_KM = 3.2
TARGET_QUALITY_LEADS = 100
