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
