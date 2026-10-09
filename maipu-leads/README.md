# Leads Maipú (Av. Sur con Av. Portales)

Saca negocios de Google Maps con Scrapling, los puntúa y genera `../informe-leads-maipu.html`.

Requiere el entorno de Scrapling (`/root/.venvs/scrapling`) y salida a internet hacia Google
(`*.google.com`, `*.gstatic.com`, `*.googleusercontent.com`). Sin una ruta de navegador propia,
usa el Chromium de `/opt/pw-browsers/chromium` (`SCRAPLING_EXECUTABLE_PATH` la cambia).

```bash
PY=/root/.venvs/scrapling/bin/python3
$PY scrape_maps.py geocode                 # punto exacto de Av. Sur con Av. Portales -> data/center.json
$PY scrape_maps.py search --rings 0        # búsquedas por rubro en el centro (--rings 0,1,2 amplía el radio)
$PY scrape_maps.py details --radius 2.5    # abre cada ficha: contacto, horario, reseñas -> data/places/
$PY photos.py download && $PY photos.py sheets
$PY digest.py --size 10                    # fichas pendientes de análisis, en texto compacto
$PY build_report.py                        # puntúa y escribe el informe HTML
```

- `config.py`: rubros, términos de búsqueda y anillos de búsqueda.
- `data/analysis/*.json`: análisis escrito por IA por ficha (resumen, elogios, reclamos, quién atiende).
- `build_report.py`: reglas de exclusión, asignación de rubro y fórmula de puntuación.
- `template.html`: el dashboard (notas y casillas se guardan en `localStorage` del navegador).
