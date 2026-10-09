"""Search configuration for the Maipú leads scraper."""

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

# Search points along the corridor live in geo.py.
SEARCH_ZOOM = 16
MAX_RESULTS_PER_SEARCH = 60
TARGET_QUALITY_LEADS = 100
