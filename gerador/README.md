# Gerador do Sabiá

Código que gera os bancos de busca por estado, a base nacional e o `catalogo.json` a partir do extrato do Brasil no
OpenStreetMap e dos municípios do IBGE.

## Requisitos

- Python 3.10+ (testado com 3.12)
- `pip install -r requirements.txt`: `osmium` (pyosmium, leitura do extrato), `shapely` (município e bairro de cada
  registro) e `zstandard` (compactação). Num Python sem venv (a distribuição "embeddable" do Windows), use
  `pip install --target .pylib -r requirements.txt`; o `generate.py` põe `.pylib/` no caminho de import.
- Para conferir o código: `ruff` e `mypy` (configurados no `pyproject.toml`).

## Como rodar

Da pasta `gerador/`:

```
python generate.py                      # geração completa em data/dist/
python generate.py --states DF,GO       # só esses estados
python -m unittest discover -s tests -t .
python -m ruff check .
python -m mypy .
```

`--osm-file` usa um extrato já baixado (um regional, por exemplo) no lugar do do Brasil; a data da geração vem do
cabeçalho do arquivo, e o catálogo sai com `osm.url` = `local` (não serve para publicar).

## Fontes

| Fonte | Arquivo em `data/raw/` | Para quê |
|---|---|---|
| Extrato do Brasil no OpenStreetMap (openstreetmap.fr, ~2,3 GB) | `brazil-latest.osm.pbf` | Todos os registros. Só é baixado de novo quando há versão nova (md5 publicado ao lado); o md5 é conferido |
| Malha municipal do IBGE (API de malhas v3, qualidade intermediária, ~12 MB) | `ibge_malha_municipios.json` | O município de cada registro, por polígono |
| Municípios do IBGE (API de localidades, ~2 MB) | `ibge_municipios.json` | Nome oficial e UF de cada município; é a lista dos municípios |

Os dois arquivos do IBGE são conferidos no cache e no download (JSON, as 27 UFs, pelo menos 5.570 municípios): uma
API pode responder 200 com uma página de erro. A lista de nomes tinha 5.571 municípios em 2026-10-05 e a malha 5.570:
Boa Esperança do Norte (MT), criado em 2025, ainda não tem polígono; os registros do território dele caem nos
municípios de onde ele saiu, até a malha trazer o polígono.

Os testes também rodam no GitHub Actions a cada push e pull request (`.github/workflows/testes.yml`), com as
dependências do `requirements.txt` e sem dados baixados.

## Convenções

Ver a seção "Convenções" do README da raiz: código, módulos, opções de linha de comando e formato dos dados em
inglês; nomes de arquivos de dados, comentários, documentação, logs e commits em português.

## Licença

Código: MIT (`LICENSE` desta pasta). Os pacotes gerados são base derivada do OpenStreetMap, sob a ODbL 1.0 (ver o
README da raiz).
