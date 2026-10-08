"""Tudo o que muda o resultado de uma geração, num lugar só."""
from __future__ import annotations

import os
from pathlib import Path

GENERATOR_DIR = Path(__file__).resolve().parent.parent
REPO = GENERATOR_DIR.parent
DATA = GENERATOR_DIR / "data"
RAW = DATA / "raw"        # extrato do OpenStreetMap e arquivos do IBGE
BUILD = DATA / "build"    # bancos descompactados desta geração e o relatório
DIST = DATA / "dist"      # pacotes .sqlite.zst e o catalogo.json desta geração

USER_AGENT = "sabia-gerador/1 (+https://github.com/Murkiriel/sabia)"

# Onde o pyosmium guarda as coordenadas dos nós durante a leitura do extrato. "flex_mem" (na memória) serve para um
# extrato regional; o Brasil inteiro pode pedir um arquivo em disco ("sparse_file_array,<caminho>").
# SABIA_NODE_STORAGE muda.
NODE_STORAGE = os.environ.get("SABIA_NODE_STORAGE") or "flex_mem"

# De quantos em quantos dias o agendamento gera de novo (sabia/schedule.py, scripts/due.py).
GENERATION_INTERVAL_DAYS = 29

# Quantas gerações ficam nas releases: a do catálogo publicado e as anteriores mais recentes. As demais são apagadas
# no fim de cada publicação. 0 = não apaga nenhuma. SABIA_KEEP_GENERATIONS muda.
KEEP_GENERATIONS = int(os.environ.get("SABIA_KEEP_GENERATIONS") or 3)

# O repositório das releases: SABIA_REPO, senão o do GitHub Actions (GITHUB_REPOSITORY, que ele define sozinho),
# senão o público. Assim um repositório de teste publica e aponta os links para ele mesmo.
GITHUB_REPO = os.environ.get("SABIA_REPO") or os.environ.get("GITHUB_REPOSITORY") or "Murkiriel/sabia"
RELEASE_URL = "https://github.com/" + GITHUB_REPO + "/releases/download/{tag}/"

# Marca que o gerador cria em DIST ao começar e apaga ao terminar: se ela existe, a geração caiu no meio.
IN_PROGRESS_MARKER = "GERACAO_EM_ANDAMENTO"

STATES = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
          "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
          "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
          "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
          "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
          "TO": "Tocantins"}

# Código IBGE da UF (os dois primeiros dígitos do código do município) -> sigla.
IBGE_STATE_CODES = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
                    "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
                    "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
                    "51": "MT", "52": "GO", "53": "DF"}

# Extrato do Brasil: o mesmo arquivo que os tiles de rota feitos do OpenStreetMap costumam usar, para a rota nunca
# apontar para uma rua que a busca não conhece. O openstreetmap.fr recorta pelo polígono do país e publica a data e o
# md5 ao lado. Trocado uma vez por dia (por volta de 01:00 UTC).
OSM_PBF_URL = "https://download.openstreetmap.fr/extracts/south-america/brazil-latest.osm.pbf"
OSM_STATE_URL = "https://download.openstreetmap.fr/extracts/south-america/brazil.state.txt"
OSM_MD5_URL = "https://download.openstreetmap.fr/extracts/south-america/brazil.osm.pbf.md5"

# Malha municipal do Brasil (API de malhas do IBGE, v3, qualidade intermediária, ~12 MB): o município de cada registro.
IBGE_MESH_URL = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
                 "?formato=application/vnd.geo%2Bjson&intrarregiao=municipio&qualidade=intermediaria")
# Nomes oficiais e UF de cada município (API de localidades do IBGE). É a lista dos municípios: em 2026-10-05 tinha
# 5.571, um a mais que a malha (Boa Esperança do Norte, MT, criado em 2025, ainda sem polígono).
IBGE_NAMES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
# Menos que isso na malha ou na lista é resposta quebrada da API, não o Brasil.
MIN_MUNICIPALITIES = 5570

# Base de Localidades do IBGE (2022): povoados, vilas, aldeias, quilombos e outras localidades, com ponto (HS1).
IBGE_LOCALITIES_URL = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/"
                       "Localidades_do_Brasil/2022/Localidades_Brasil_gpkg.zip")

# Postos e unidades da Polícia Rodoviária Federal nas rodovias concedidas (ANTT, dados abertos, conjunto "PRF"; JSON
# atualizado todo mês; licença Creative Commons Atribuição) (HS2).
PRF_URL = ("https://dados.antt.gov.br/dataset/87c613a5-af73-445f-bc35-5fe816e70935/resource/"
           "1e409dae-301a-4b54-a873-0becba08050f/download/informaes-sobre-os-postos-da-prfs.json")

# Cadastro Nacional de Estabelecimentos de Saúde (Ministério da Saúde, dados abertos): o CSV nacional num zip (~56 MB),
# refeito todo dia (HS3).
CNES_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos_csv.zip"

# Lugares da Overture Maps (HS4): a listagem das versões no S3 público e o balde (lido pelo pyarrow, sem conta).
OVERTURE_LISTING_URL = ("https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/"
                        "?list-type=2&prefix=release/&delimiter=/")
OVERTURE_BUCKET = "overturemaps-us-west-2"

# Sistema Nacional de Viação do DNIT (HS6): a camada de rodovias do serviço WFS do DNITGeo, consultada pela versão em
# vigor no dia (sabia/snv.py monta a consulta).
SNV_WFS_URL = "https://servicos.dnit.gov.br/dnitgeo/geoserver/ows"
SNV_LAYER = "vgeo:vw_snv_rod"

# Aeródromos públicos e privados (ANAC, dados abertos, JSON) (HS8).
_ANAC = "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/"
ANAC_PUBLIC_URL = (_ANAC + "Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/"
                   "AerodromosPublicos.json")
ANAC_PRIVATE_URL = (_ANAC + "Aer%C3%B3dromos%20Privados/Lista%20de%20aer%C3%B3dromos%20privados/"
                    "Aerodromos%20Privados/AerodromosPrivados.json")

# GeoNames (CC BY 4.0): os lugares do Brasil e os nomes alternativos; Wikidata (CC0): a consulta SPARQL (HS9).
GEONAMES_PLACES_URL = "https://download.geonames.org/export/dump/BR.zip"
GEONAMES_NAMES_URL = "https://download.geonames.org/export/dump/alternatenames/BR.zip"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

# API de revendedores da ANP (sem conta): os postos de combustível em operação, com a posição geográfica (HS10).
ANP_API_URL = "https://revendedoresapi.anp.gov.br/v1/combustivel"

ATTRIBUTION = ("© colaboradores do OpenStreetMap (ODbL 1.0); municípios, limites municipais e localidades: IBGE; "
               "postos da PRF: ANTT; hospitais, UPAs e prontos-socorros: CNES (Ministério da Saúde); "
               "lugares: Overture Maps Foundation (CDLA Permissive 2.0); "
               "quilômetros das rodovias federais: DNIT (SNV); aeródromos: ANAC; "
               "nomes alternativos e pontos turísticos: GeoNames (CC BY 4.0) e Wikidata (CC0); "
               "postos de combustível: ANP")
SEARCH_CASES = GENERATOR_DIR / "buscas.json"

# O GitHub Releases recusa arquivo a partir de 2 GiB; esta é a trava, com folga.
MAX_ASSET_BYTES = 1_900_000_000
