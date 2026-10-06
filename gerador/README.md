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

## Como funciona

| Etapa | Módulo | O que faz |
|---|---|---|
| sources | `sabia/sources.py` | Extrato do OpenStreetMap e arquivos do IBGE (acima) |
| build | `sabia/osm_reader.py` | Uma passada pelo extrato (pyosmium): lugares, vias com nome ou `ref`, pontos de interesse (pontos, vias e relações); um filtro de chaves no C++ descarta antes do Python o que não interessa |
| build | `sabia/records.py` | Os registros de cada estado, cada um no município cujo polígono contém o ponto dele (`sabia/municipalities.py`) |
| build | `sabia/districts.py` | Os bairros de cada estado e o bairro de cada registro |
| build | `sabia/street_lines.py` | O traçado de cada rua, simplificado a 10 m, para o "que rua é esta?" |

**Registros** (`sabia/records.py`, tipos em `sabia/kinds.py`):

- `place`: cada município do IBGE (`kind` `municipality`, com o nome oficial; a sede é o lugar do OpenStreetMap de
  mesmo nome dentro dele, cidade antes de vila, senão um ponto dentro do polígono) e os lugares com nome (`place=`
  cidade, vila, povoado, bairro, localidade, fazenda, ilha). Um lugar desenhado só como área entra pelo centro dela,
  se não houver um ponto de mesmo nome a até 2 km no município.
- `street` (D5): vias com nome, juntadas por município e nome quando se tocam (nó em comum) ou têm pontas a menos de
  60 m, em cadeia. A posição é o meio do trecho mais central; o `kind` é o do trecho mais importante. Uma rua só de
  vias locais com mais de 3 km de ponta a ponta fica marcada como suspeita de junção errada.
- `road`: uma por `ref` e município, das vias motorway a tertiary (`BR 153` vira `BR-153`; `ref` que não é sigla e
  número, como um CEP, fica de fora).
- `poi` (D7): pontos, vias e relações com `amenity`, `shop`, `tourism`, `leisure`, `craft`, `office`, `healthcare`,
  `emergency` ou `historic` e nome, mais aeroporto, cachoeira, pico, praia, caverna, autódromo, pedágio e áreas de
  descanso; os de viagem (posto, hospital, clínica, polícia, farmácia, recarga, borracharia, oficina, pedágio)
  entram sem nome, com a marca (`brand`) no lugar do nome quando houver.

**Bairros** (`sabia/districts.py`, G4): as áreas de bairro (relações e vias fechadas com `place` suburb, quarter ou
neighbourhood, e limites administrativos de nível 10, bairro, e 9, distrito) e os pontos de bairro sem área de mesmo
nome no município. O bairro de um registro é o do polígono que o contém (bairro antes de vizinhança, vizinhança antes
de distrito; no mesmo nível, o menor polígono); fora de todos, o ponto de bairro mais próximo até 3 km, no mesmo
município. Em Goiás: 3.323 bairros (2.869 com polígono); 63% das ruas e 60% dos pontos de interesse ficam com bairro
(o resto é zona rural ou cidade sem bairro mapeado), e as 23 "Rua 10" de Goiânia ficam em 21 bairros diferentes. No
DF: 622 bairros, 94% das ruas com bairro.

**Traçados** (`sabia/street_lines.py`, G5, D6): cada trecho de rua com nome (e cada trecho sem nome de rodovia)
simplificado a 10 m e cortado em pedaços de até 2 km, cada um com o quadrado do zoom 13 do meio dele. Em Goiás:
142.696 pedaços, 7,2 MB no SQLite, e a medição de 4.000 pontos (meio de trechos de rua, até 12 m para o lado) refeita
com este código acerta a rua de 99,0% deles, procurando só nos 9 quadrados em volta.

Conferido com o extrato do Centro-Oeste de 2026-09-29: Goiás dá 92.131 registros (3.426 lugares, 74.809 ruas, 963
rodovias, 12.933 pontos de interesse), os 246 municípios, e os casos medidos da regra de juntar ruas (Av. Anhanguera
em Goiânia em 5 registros, Av. T-63 e Av. Goiás em 1, Av. Brasil em Anápolis em 7, 163 ruas locais suspeitas); o
DF, 30.847. A leitura do extrato regional (206 MB) leva ~20 s.

## Convenções

Ver a seção "Convenções" do README da raiz: código, módulos, opções de linha de comando e formato dos dados em
inglês; nomes de arquivos de dados, comentários, documentação, logs e commits em português.

## Licença

Código: MIT (`LICENSE` desta pasta). Os pacotes gerados são base derivada do OpenStreetMap, sob a ODbL 1.0 (ver o
README da raiz).
