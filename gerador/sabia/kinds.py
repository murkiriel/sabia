"""O que entra de cada tipo de objeto do OpenStreetMap (decisões D4 e D7) e com que `kind` no banco.

`kind` é a etiqueta do OpenStreetMap que decidiu a entrada ("amenity=fuel", "place=suburb", "highway=primary"); o
município entra como "municipality" e a rodovia por município como "road"."""
from __future__ import annotations

from typing import Mapping, Optional

# Lugares com nome que viram registro. Fora: município, estado e região (vêm do IBGE) e quadra ou lote (city_block,
# plot), que só repetem a rua.
PLACE_KINDS = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter", "locality",
               "isolated_dwelling", "farm", "island", "islet"}
# Ordem de preferência para achar a sede de um município entre os lugares de mesmo nome dentro dele.
SEAT_RANK = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "suburb": 4, "locality": 5}

# Vias que viram rua quando têm nome (as da medição, mais as ligações).
STREET_HIGHWAYS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                   "living_street", "service", "track", "pedestrian", "road", "motorway_link", "trunk_link",
                   "primary_link", "secondary_link", "tertiary_link"}
# Ordem de importância: o `kind` de uma rua juntada é o do trecho mais importante.
HIGHWAY_RANK = {h: i for i, h in enumerate(
    ["motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
     "secondary_link", "tertiary_link", "unclassified", "residential", "living_street", "road", "pedestrian",
     "service", "track"])}
# Vias locais: uma rua só com elas e mais de 3 km de ponta a ponta é suspeita de junção errada (relatório da geração).
LOCAL_HIGHWAYS = {"residential", "living_street", "service", "track", "unclassified", "pedestrian", "road"}
# Vias cuja `ref` vira uma rodovia por município ("BR-153 em Anápolis").
ROAD_HIGHWAYS = {"motorway", "trunk", "primary", "secondary", "tertiary"}

# Chaves de ponto de interesse, na ordem em que decidem o `kind` quando há mais de uma.
POI_KEYS = ("amenity", "shop", "tourism", "leisure", "craft", "office", "healthcare", "emergency", "historic")
# D7: os tipos que faltaram na comparação de 50 buscas (aeroporto, cachoeira, pico, mirante já é tourism, autódromo),
# mais pedágio e áreas de descanso, que valem pela etiqueta exata.
# Tupla, não conjunto: a ordem decide o `kind` e tem de ser a mesma em toda geração.
EXTRA_POI_TAGS = (("aeroway", "aerodrome"), ("aeroway", "heliport"), ("natural", "waterfall"),
                  ("waterway", "waterfall"), ("natural", "peak"), ("natural", "beach"), ("natural", "cave_entrance"),
                  ("highway", "raceway"), ("barrier", "toll_booth"), ("highway", "rest_area"),
                  ("highway", "services"))
# De viagem: entram mesmo sem nome (com a marca no lugar do nome, quando houver).
TRAVEL_POI_TAGS = {("amenity", "fuel"), ("amenity", "hospital"), ("amenity", "clinic"), ("amenity", "police"),
                   ("amenity", "pharmacy"), ("amenity", "charging_station"), ("shop", "tyres"),
                   ("shop", "car_repair"), ("shop", "motorcycle_repair"), ("shop", "motorcycle"),
                   ("barrier", "toll_booth"), ("highway", "rest_area"), ("highway", "services")}
# Valores que nunca são lugar procurado, mesmo com nome.
IGNORED_POI_VALUES = {"bench", "waste_basket", "waste_disposal", "grit_bin", "parking_space", "vending_machine",
                      "bicycle_parking", "motorcycle_parking", "yes", "no"}


def poi_kind(tags: Mapping[str, str]) -> Optional[str]:
    """O `kind` de ponto de interesse das etiquetas, ou None se o objeto não é um."""
    for key, value in EXTRA_POI_TAGS:
        if tags.get(key) == value:
            return f"{key}={value}"
    for key in POI_KEYS:
        found = tags.get(key)
        if found and found not in IGNORED_POI_VALUES:
            return f"{key}={found}"
    return None


def is_travel(kind: str) -> bool:
    key, _, value = kind.partition("=")
    return (key, value) in TRAVEL_POI_TAGS
