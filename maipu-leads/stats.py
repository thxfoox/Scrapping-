"""Quick progress stats over the saved fichas."""
import collections
import json

from build_report import DATA, candidates, load_analysis, load_places

places = load_places()
cands, reasons = candidates(places)
done = load_analysis()
print(f"fichas: {len(places)} | con teléfono: {sum(1 for p in places if p.get('phone'))} "
      f"(móvil {sum(1 for p in places if p.get('is_mobile'))}) | vista limitada: {sum(1 for p in places if p.get('limited_view'))} "
      f"| reseñas leídas: {sum(len(p.get('review_items', [])) for p in places)}")
print(f"candidatos: {len(cands)} | analizados: {sum(1 for p in cands if p['key'] in done)} | excluidos: {reasons}")
print("por rubro:", dict(collections.Counter(p["rubro"] for p in cands).most_common()))
