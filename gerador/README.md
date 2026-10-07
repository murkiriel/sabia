# Gerador do Sabiá

Código que gera os bancos de busca por estado, a base nacional e o `catalogo.json` a partir do extrato do Brasil no
OpenStreetMap e dos municípios do IBGE.

## Requisitos

- Python 3.10+ (testado com 3.12)
- `pip install -r requirements.txt`: `osmium` (pyosmium, leitura do extrato), `shapely` (município e bairro de cada
  registro), `zstandard` (compactação) e `pyarrow` (os lugares da Overture, GeoParquet no S3). Num Python sem venv
  (a distribuição "embeddable" do Windows), use `pip install --target .pylib -r requirements.txt`; o `generate.py`
  põe `.pylib/` no caminho de import.
- Para conferir o código: `ruff` e `mypy` (configurados no `pyproject.toml`).

## Como rodar

Da pasta `gerador/`:

```
python scripts/install_sqlite.py        # uma vez: o SQLite 3.22 da trava G7e, em data/tools/
python generate.py                      # geração completa em data/dist/
python generate.py --states DF,GO       # só esses estados
python generate.py --from validate      # só as travas (e o catálogo) sobre os bancos já gerados
python scripts/publish.py               # confere a geração (não publica nada)
python scripts/publish.py --release     # sobe os pacotes numa release e grava o catalogo.json na raiz
python scripts/due.py                   # está na hora de gerar de novo? (só responde; não gera)
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
| Base de Localidades do IBGE (2022, GeoPackage num zip, ~6 MB) | `ibge_localidades.zip` | Povoados, vilas, aldeias, quilombos e outras localidades (HS1) |
| Postos da PRF (ANTT, dados abertos, conjunto "PRF", JSON, ~50 kB) | `antt_postos_prf.json` | As unidades da Polícia Rodoviária Federal nas rodovias concedidas (HS2) |
| CNES (Ministério da Saúde, CSV nacional num zip, ~56 MB, refeito todo dia) | `cnes_estabelecimentos.zip` | Hospitais, UPAs e prontos-socorros abertos 24 horas (HS3) |
| Overture Maps, lugares (versão mais nova pela listagem do S3 público; recorte do Brasil, ~190 MB, ~6 min daqui) | `overture_lugares.parquet` | Comércio e serviços que faltam no OpenStreetMap (HS4) |

Os dois arquivos do IBGE são conferidos no cache e no download (JSON, as 27 UFs, pelo menos 5.570 municípios): uma
API pode responder 200 com uma página de erro. Com resposta ruim (status de erro ou conteúdo que não passa), são até
3 tentativas, com 60 s e depois 120 s de espera; cada uma vai para o log com o status, o `Content-Type`, o tamanho e
o começo do corpo, e o corpo fica em `data/raw/<arquivo>.<tentativa>.invalido` (o workflow leva esses arquivos para o
artefato). No Actions, os dois arquivos ficam no cache, um por mês. A lista de nomes tinha 5.571 municípios em
2026-10-05 e a malha 5.570: Boa Esperança do Norte (MT), criado em 2025, ainda não tem polígono; os registros do
território dele caem nos municípios de onde ele saiu, até a malha trazer o polígono.

As fontes novas (Parte 9 da pesquisa) são baixadas e conferidas do mesmo jeito que os arquivos do IBGE, cada uma com
a sua regra (formato, colunas, um mínimo de registros). A data de cada fonte conferida (o `Last-Modified` do site;
sem ele, o dia do download) fica ao lado do arquivo, em `data/raw/<arquivo>.fonte.json`; a etapa sources junta todas,
com a data do extrato, em `data/build/fontes.json`, e o registro da geração (`data/dist/geracao.json`) as leva em
`sources`.

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
| build | `sabia/database.py` | Os bancos SQLite (FTS4, tabelas de busca de `sabia/search_rules.py`, `meta`) e a compactação zstd 19; formato em [`docs/FORMATO.md`](../docs/FORMATO.md) |
| build | `sabia/build.py` | A etapa inteira: lê o extrato uma vez, grava os bancos em `data/build/` e os pacotes e o `pacotes.json` em `data/dist/` |
| validate | `sabia/validation.py` | As travas (abaixo) e o `data/dist/relatorio.json` |
| catalog | `sabia/catalog.py` | O `data/dist/catalogo.json`: tamanho, sha256, retângulo e contagens de cada pacote |

Cada geração grava `data/dist/geracao.json` (`sabia/run_record.py`): minutos de cada etapa, pico de disco em `data/`
e o resultado. Enquanto roda, existe a marca `data/dist/GERACAO_EM_ANDAMENTO`; se ela sobrar, a geração caiu no meio e
a publicação recusa. Geração completa aqui (DF e GO, extrato do Centro-Oeste, `--osm-file`): 0,8 min, pico de 0,26 GB
em `data/`.

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

**Fontes novas** (Parte 9 da pesquisa): cada uma num módulo próprio, juntada aos registros depois dos do
OpenStreetMap e antes dos bairros (ganha bairro como os outros). O município é o do ponto, pela malha
(`sabia/merge.py`); o que repete um registro já existente a até o raio medido da fonte não entra.

| Fonte | Módulo | O que entra | Sem repetir |
|---|---|---|---|
| Localidades do IBGE | `sabia/localities.py` | `place` `ibge=<categoria>`, sem as sedes | Mesmo nome no mesmo município a até 3 km |
| Postos da PRF (ANTT) | `sabia/prf.py` | `poi` `amenity=police`, "PRF - Polícia Rodoviária Federal, BR-060 km 182", só os ativos | Posto de polícia da PRF (pelo nome) ou sem nome a até 250 m: em GO e no DF, 14 das 16 unidades já estão no OpenStreetMap, a 4 a 202 m |
| Overture Maps | `sabia/overture.py` | `poi` com o `kind` do OpenStreetMap quando a categoria tem um que a busca usa (posto, hospital, farmácia, hotel, restaurante, oficina, borracharia...), senão `overture=<categoria>`; só confiança de 0,6 ou mais, com categoria, sem lugares naturais e marcos (ficam com o OpenStreetMap) e sem o que vem da Foursquare | Lugar ou ponto de interesse de nome parecido (as palavras de um contidas nas do outro, ou metade em comum) a até 300 m, ou sem nome e do mesmo `kind` |
| CNES (Ministério da Saúde) | `sabia/cnes.py` | `poi` `amenity=hospital`: hospital geral ou especializado, unidade mista, pronto-socorro e UPA com atendimento 24 horas, sem desativação, com o ponto no município que o cadastro declara; nome fantasia em caixa de título | Registro de saúde (hospital, clínica, consultório, `healthcare=*`) a até 500 m sem nome ou com uma palavra do nome em comum (fora as genéricas) |

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

**Pacotes** (`sabia/database.py`, G6), gerados aqui com o extrato do Centro-Oeste em 2026-10-05 (`--states DF,GO`,
51 s ao todo, 25 s de leitura):

| Pacote | Registros | Banco | Compactado (zstd 19) |
|---|---:|---:|---:|
| DF | 30.934 | 7,4 MB | 1,5 MB |
| GO | 92.760 | 23,8 MB | 6,2 MB |
| Base (5.570 municípios, 23 rodovias federais de DF e GO) | 5.593 | 1,1 MB | 0,3 MB |

O banco de Goiás inclui 142.696 pedaços de traçado e 3.323 bairros. Os pacotes são reproduzíveis: o mesmo extrato dá
o mesmo arquivo, byte a byte (ordem fixa, compactação sem threads).

Conferido com o extrato do Centro-Oeste de 2026-09-29: Goiás dá 92.131 registros (3.426 lugares, 74.809 ruas, 963
rodovias, 12.933 pontos de interesse), os 246 municípios, e os casos medidos da regra de juntar ruas (Av. Anhanguera
em Goiânia em 5 registros, Av. T-63 e Av. Goiás em 1, Av. Brasil em Anápolis em 7, 163 ruas locais suspeitas); o
DF, 30.847. A leitura do extrato regional (206 MB) leva ~20 s.

## Travas (G7)

A etapa `validate` não deixa montar o catálogo se:

- **(a) buscas de verdade:** algum caso de [`buscas.json`](buscas.json) não traz o resultado esperado até a posição
  `top` (nome igual ou contido, município, bairro e/ou um ponto com raio), pela busca de referência
  (`sabia/search.py`, as regras de [`docs/CONSUMO.md`](../docs/CONSUMO.md)). Hoje: 49 casos de Goiás (as 50 buscas da
  medição, menos a PUC, escrita "universidadfe" no OpenStreetMap) e 20 do DF; outros estados entram quando houver
  casos para eles;
- **(b) cobertura:** falta no banco do estado algum município do IBGE com polígono, ou falta ponto na base para um
  município de estado gerado;
- **(e) SQLite antigo:** o esquema usa algo que o SQLite 3.22 (o do Android 10) não tem (FTS5, R-Tree, STRICT,
  WITHOUT ROWID, coluna gerada), o banco não passa no `integrity_check` do 3.22, ou alguma busca dá outro resultado no
  3.22 que no SQLite do Python. O 3.22 vem de `scripts/install_sqlite.py` (no Linux, compilado do código oficial só
  com FTS3 e FTS4, como o Android; no Windows, a DLL oficial); sem ele, a trava falha.

E registra no `relatorio.json`:

- **(d) ruas locais longas:** as ruas só de vias locais juntadas com mais de 3 km de ponta a ponta, suspeitas de
  junção errada (não travam; confira as que mudarem de uma geração para outra);
- o resultado de cada busca e os problemas.

A **(c) queda de registros** em relação à geração publicada (mais de 5% no total de um estado, ou numa classe com pelo
menos 1.000 registros, ou um estado que sumiu) é conferida na publicação, contra o `catalogo.json` publicado
(`validation.drops`).

Medido aqui (DF e GO, extrato do Centro-Oeste de 2026-09-29): 69 de 69 buscas, 0 problemas, as buscas iguais no
SQLite 3.22, 184 ruas locais suspeitas (163 em GO, 21 no DF); a etapa leva ~4 s.

## Publicação (G8)

`scripts/publish.py` (a lógica em `sabia/publishing.py`, o mesmo molde de release com rascunho e retomada) não
publica se:

- a geração ainda roda ou caiu no meio (marca `GERACAO_EM_ANDAMENTO`),
- o formato do catálogo não é o do gerador (`database.FORMAT_VERSION`),
- a geração foi feita de um extrato local (`--osm-file`, `osm.url` = `local`),
- a geração não passou nas travas (`data/dist/relatorio.json` com problemas, ou sem ele),
- algum pacote falta, não bate o sha256 ou passa do limite do GitHub Releases,
- algum estado sumiu ou perdeu mais de 5% dos registros em relação ao `catalogo.json` publicado, no total ou numa
  classe com 1.000 registros ou mais (`--accept-drop` para passar),
- a geração usa um OpenStreetMap mais antigo que o da publicada (`--accept-older`),
- já existe uma release PUBLICADA com o mesmo `build_id`,
- com `--commit`, o git do repositório não está com o e-mail anônimo do GitHub (`…@users.noreply.github.com`).

A release sobe como rascunho, sem arquivos; cada pacote que ainda não está lá (ou está com outro tamanho) sobe; só
com todos presentes e do tamanho certo ela é publicada. Se a subida cair no meio, rodar o mesmo comando retoma do que
falta. Só depois o `catalogo.json` e a tabela "Baixar por estado" do README da raiz mudam, no mesmo commit; com
`--push`, as releases antigas são apagadas no fim (ficam 3 gerações, `SABIA_KEEP_GENERATIONS` muda;
`python scripts/publish.py --prune --dry-run` mostra o que seria apagado). O repositório das releases é `SABIA_REPO`,
senão o do Actions (`GITHUB_REPOSITORY`), senão `Murkiriel/sabia`.

## Agendamento (G9)

A geração inteira roda no Actions, no workflow `gerar` (`.github/workflows/gerar.yml`), **a cada 29 dias**: ele
dispara todo dia às 03:47 e às 09:47 de Brasília, o job `interval` pergunta ao `scripts/due.py` (lógica em
`sabia/schedule.py`) se a geração publicada (`built_at` do `catalogo.json`) já tem 29 dias, e só então a geração roda
e publica. Se falhar, o disparo seguinte tenta de novo. Dois horários, fora da hora cheia, porque o GitHub atrasa ou
pula disparos agendados sem avisar. Disparado à mão, gera na hora e só publica com `publish` marcado. **Num fork, o
agendamento não gera** (`github.repository == 'Murkiriel/sabia'`).

Para uma geração fora do intervalo sem disparar à mão, a variável `GENERATE_FROM` do job `interval` marca um dia
(`AAAA-MM-DD`, UTC): a partir dele, o agendamento gera se a geração publicada for de antes desse dia.

O job da geração liga 8 GB de swap, instala as dependências e o SQLite 3.22 (compilado), gera o Brasil inteiro (sem
`--osm-file` nem `--states`), guarda como artefato os logs, o `relatorio.json` das travas, o `geracao.json` e as
medições de memória, swap e disco a cada 30 s, e publica pelo `scripts/publish.py --release --commit --push`. O
repositório das releases é o do próprio Actions (`GITHUB_REPOSITORY`). **Ainda não rodou no Actions** (fase V1, que
precisa do repositório no GitHub).

## Convenções

Ver a seção "Convenções" do README da raiz: código, módulos, opções de linha de comando e formato dos dados em
inglês; nomes de arquivos de dados, comentários, documentação, logs e commits em português.

## Licença

Código: MIT (`LICENSE` desta pasta). Os pacotes gerados são base derivada do OpenStreetMap, sob a ODbL 1.0 (ver o
README da raiz).
