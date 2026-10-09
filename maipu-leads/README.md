# Leads Maipú (Av. Portales, Av. Sur y Nueva San Martín)

Saca negocios de Google Maps con Scrapling, los puntúa y genera `../informe-leads-maipu.html`.

## Instalación (una vez)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "scrapling[all]>=0.4.8" pillow
scrapling install    # descarga el navegador; solo hace falta para scrapear
```

Usa el navegador de Scrapling; `SCRAPLING_EXECUTABLE_PATH` apunta a otro Chromium si hace falta.

Los datos (`data/`) y el informe no están en git: el repo es público y contienen teléfonos.
Para seguir en otro equipo, copia la carpeta `data/` dentro de `maipu-leads/`.

## Flujo

```bash
python scrape_maps.py search --points centro,oeste,este   # búsquedas por rubro -> data/places_index.json
python scrape_maps.py details --radius 0.15               # abre cada ficha cercana -> data/places/
python scrape_maps.py details --keys KEY1,KEY2            # relee fichas concretas
python scrape_maps.py photos                              # foto principal de las fichas que no la tienen
python stats.py                                           # avance: fichas, candidatos y analizados
python digest.py --size 12                                # siguiente tanda sin analizar, en texto compacto
python photos.py batch                                    # hoja de fotos de esa tanda -> data/sheets/current.jpg
python save_batch.py tanda.json                           # guarda el análisis de la tanda -> data/analysis/
python pitch.py digest --size 45                          # siguientes negocios sin frase de entrada para el guion
python pitch.py save tanda.json                           # guarda esas frases -> data/pitch/
python build_report.py                                    # puntúa y escribe el informe HTML
```

- `config.py`: rubros y términos de búsqueda.
- `geo.py`: el sector (de Av. Portales a Nueva San Martín, hasta El Carmen) y los puntos de búsqueda.
- `data/analysis/*.json`: análisis escrito por IA para cada ficha (resumen, elogios, reclamos, quién atiende).
- `build_report.py`: exclusiones, rubro y puntuación; `--candidates` lista lo que falta analizar.
  También decide qué ofrecerle a cada negocio (ficha de Google, redes o web) según lo que le falta a su ficha.
- `data/pitch/*.json`: frase de entrada y propuesta escritas por IA para el guion de cada negocio.
- `template.html`: el dashboard (casillas y notas se guardan en el `localStorage` del navegador).
