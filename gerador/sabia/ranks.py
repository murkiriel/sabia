"""A importância de cada registro, de 0 a 255 (coluna `item.rank`): puxa para cima na ordenação da busca e decide a
ordem dos ids no banco (do mais importante ao menos), que é a ordem em que o FTS devolve e corta (LIMIT) uma busca.

A conta vem do Organic Maps (seção rank do .mwm): com população, `ln(população) / ln(1,1)` (1.000 habitantes dão 72;
100 mil, 121; 1,5 milhão, 149). Sem população, um valor fixo pelo tipo, na mesma escala: o lugar pelo tamanho, a via
pela classe, o ponto de interesse pelo quanto serve de referência numa viagem. O que vem da Overture (comércio que
falta no mapa, sem conferência) fica abaixo do mesmo tipo do mapa.
"""
from __future__ import annotations

import math

from .records import Item

MAX_RANK = 255

# Lugares sem população: os valores de uma cidade de ~30 mil (city), ~2 mil (village), ~200 (hamlet)...
PLACE_RANKS = {
    "place=city": 110, "municipality": 75, "place=town": 85, "place=village": 60, "place=suburb": 55,
    "place=quarter": 50, "place=neighbourhood": 45, "place=island": 45, "place=hamlet": 35, "place=locality": 25,
    "place=islet": 25, "place=isolated_dwelling": 15, "place=farm": 15,
}
IBGE_PLACE_RANK = 30           # localidades da Base de Localidades do IBGE (povoado, vila, aldeia...)
OTHER_PLACE_RANK = 20

STREET_RANKS = {"motorway": 70, "trunk": 65, "primary": 55, "secondary": 45, "tertiary": 35, "motorway_link": 30,
                "trunk_link": 30, "primary_link": 28, "secondary_link": 26, "tertiary_link": 24}
OTHER_STREET_RANK = 20
ROAD_RANK = 60

# Pontos de interesse que servem de referência; os outros do mapa ficam em DEFAULT_POI_RANK.
POI_RANKS = {
    "aeroway=aerodrome": 60, "amenity=bus_station": 60, "shop=mall": 55, "amenity=university": 55,
    "amenity=hospital": 55, "leisure=stadium": 55, "tourism=attraction": 50, "tourism=museum": 45,
    "natural=waterfall": 45, "waterway=waterfall": 45, "natural=peak": 40, "natural=beach": 45,
    "boundary=national_park": 50, "leisure=park": 40, "tourism=viewpoint": 40, "amenity=college": 40,
    "barrier=toll_booth": 40, "highway=rest_area": 35, "highway=services": 35, "amenity=police": 35,
    "amenity=fuel": 30, "amenity=clinic": 30, "amenity=pharmacy": 28, "tourism=hotel": 30, "amenity=school": 28,
    "amenity=place_of_worship": 28, "shop=supermarket": 28, "amenity=marketplace": 28,
    "highway=milestone": 10,
}
DEFAULT_POI_RANK = 20
OVERTURE_PENALTY = 8           # o mesmo tipo vindo da Overture
OVERTURE_ONLY_RANK = 12        # categoria que só a Overture tem (overture=beauty_salon)


def population_rank(population: int) -> int:
    return min(MAX_RANK, round(math.log(population) / math.log(1.1))) if population > 1 else 0


def rank(item: Item) -> int:
    """A importância do registro (ver o cabeçalho do módulo)."""
    if item.population > 1 and item.cls == "place":
        return population_rank(item.population)
    if item.cls == "place":
        if item.kind.startswith("ibge="):
            return IBGE_PLACE_RANK
        return PLACE_RANKS.get(item.kind, OTHER_PLACE_RANK)
    if item.cls == "street":
        return STREET_RANKS.get(item.kind.removeprefix("highway="), OTHER_STREET_RANK)
    if item.cls == "road":
        return ROAD_RANK
    if item.kind.startswith("overture="):
        return OVERTURE_ONLY_RANK
    value = POI_RANKS.get(item.kind, DEFAULT_POI_RANK)
    return max(1, value - OVERTURE_PENALTY) if item.origin == "overture" else value
