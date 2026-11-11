# Conformidade da busca

A busca descrita em [`CONSUMO.md`](CONSUMO.md) tem uma versão de referência em Python
([`gerador/sabia/search.py`](../gerador/sabia/search.py), com `search_rules.py`, `text.py` e `ranks.py`). Quem a
porta para outra linguagem (Kotlin num aplicativo Android, JavaScript na web) precisa conferir que o porte dá os
mesmos resultados. Para isso, cada geração publica um **conjunto de conformidade**: casos com a entrada (o texto
digitado, a posição, o banco) e a saída da referência (os primeiros resultados, com a nota e os critérios da ordem de
cada um), em JSON, independente de linguagem. Um verificador roda os casos no porte e compara.

| O quê | Onde |
|---|---|
| O conjunto de cada geração | Na release da geração: `sabia-conformidade.json.zst`, com o sha256 em `sabia-conformidade.json.zst.sha256` (formato do `sha256sum`) |
| Um exemplo pequeno, sem baixar nada | [`gerador/conformidade-exemplo.json`](../gerador/conformidade-exemplo.json): todas as funções puras e 12 buscas da base, de GO e do DF |
| Quem gera | [`gerador/scripts/build_conformance.py`](../gerador/scripts/build_conformance.py) e a etapa `conformance` da geração ([`gerador/sabia/conformance.py`](../gerador/sabia/conformance.py)) |
| O verificador de referência | [`gerador/scripts/check_conformance.py`](../gerador/scripts/check_conformance.py): roda o próprio `search.py` contra o conjunto (passa 100%) e é o modelo do verificador de um porte |

O arquivo da release ainda **não está no `catalogo.json`**: o endereço é o `release_url` do catálogo mais o nome fixo
(`<release_url>sabia-conformidade.json.zst`). Ver [O catálogo](#o-catálogo) no fim.

## O conjunto é de uma geração

As notas e a ordem dependem dos registros do banco (a importância, os nomes, os ids que desempatam), então o conjunto
vale só para os bancos da geração em que foi feito: ele traz o `build_id`, o `format_version` e o sha256 de cada
pacote usado. Um caso de um banco de outra geração (ou ausente) é **pulado**, com aviso, nunca comparado. As funções
puras (`unit`) não dependem do banco e valem para qualquer geração do mesmo `conformance_version`.

## O arquivo (versão 1)

JSON em UTF-8 (no `.zst`, compactado com zstd 19). Campos do topo:

| Campo | O que é |
|---|---|
| `conformance_version` | A versão deste formato (1). **Recuse uma maior** que a que o seu verificador conhece |
| `build_id`, `format_version` | A geração e o formato dos bancos (`meta.build_id`, `meta.format_version`) |
| `generator_commit` | O commit do gerador que fez o conjunto |
| `reference` | O arquivo da busca de referência (`gerador/sabia/search.py`) |
| `unicode_version` | A versão do Unicode do Python que fez o conjunto (a de `unicodedata`): a decomposição e as classes de caractere dependem dela |
| `limit` | Quantos resultados cada busca pede (10) |
| `states`, `packages` | As UFs e os pacotes usados: `{"GO": {"file": "sabia-GO.sqlite.zst", "sha256": "..."}, "base": {...}}` |
| `constants` | As constantes que o porte escreve no código (não estão no banco): palavras vazias, palavras que levam número no nome, os pesos `W_*`, `MAX_COMBINATIONS`, `MAX_ROWS`, `CATEGORY_RINGS`, `MAX_STREET_DISTANCE_M`, as casas da nota... Confira as suas com estas |
| `rules` | As tabelas de regras dos pacotes (`word_form`, `category`, `brand`), iguais em todos os bancos da geração (a geração confere): servem às funções puras sem banco |
| `unit_fixtures` | Um vocabulário (`vocab`: palavra, registros) e uma lista de municípios (id, nome) pequenos, para `correct` e `parse` sem banco |
| `unit` | Os casos das funções puras |
| `search` | Os casos de busca |
| `which_street` | Os casos de "que rua é esta?" |

### `unit`: as funções puras

`{"id": "fold-07", "fn": "fold", "args": {"text": "𝐆𝐨𝐢𝐚̂𝐧𝐢𝐚"}, "expected": "Goiania", "note": "matemático negrito"}`.
`tol` (quando há) é a diferença máxima dos números com vírgula (relativa acima de 1, absoluta abaixo); `informative:
true` marca um caso de Unicode raro em que um porte bem-feito pode diferir por causa da biblioteca de Unicode da
plataforma: a diferença vira aviso, não falha. Os resultados são valores JSON (tuplas viram listas; `null` é "nenhum").

| `fn` | `args` | `expected` | Na referência |
|---|---|---|---|
| `fold` | `text` | texto dobrado | `text.fold` |
| `index_text` | `name` | o nome como vai para o índice, com a outra forma dos números | `database.index_text` (o critério 1 da ordem casa com ele) |
| `edit_distance` | `a`, `b` | inteiro | `search.edit_distance` |
| `max_errors` | `length` | erros aceitos pelo tamanho | `search.max_errors` |
| `same_sound` | `a`, `b` (uma letra) | booleano | `search._same_sound` |
| `house_number_in` | `words` | `{"number", "words"}` ou `null` | `search.house_number_in` |
| `options` | `word`, `last` | `[[termo, inteiro?], ...]`, na ordem | `_Rules.options` (com `rules`) |
| `name_score` | `words`, `name`, `prefix_last` | 0 a 3 | `search.name_score` |
| `name_cover` | `words`, `name`, `prefix_last` | 0 a 1 | `search.name_cover` |
| `name_hits` | `words`, `name`, `last_word` | inteiro | `search._name_hits` |
| `parse` | `folded` (já corrigido) | `{"words", "text", "kinds", "category_words", "municipality", "municipality_words"}` | `search._parse` (com `rules` e os municípios de `unit_fixtures`) |
| `correct` | `word`, `prefix`, `force` | a palavra (trocada ou não) | `_Rules.correct` (com `rules` e o `vocab` de `unit_fixtures`) |
| `ladder_position` | `rungs` (inteiros de 5 em 5, como `house_number.rungs`), `number` | `[lat, lng]` ou `null` | `search.ladder_position` |
| `cell` | `lat`, `lng` | inteiro | `geo.cell` |
| `cells_around` | `lat`, `lng`, `ring` | lista de inteiros, na ordem | `search._cells_around` |
| `dist_m` | `lat1`, `lng1`, `lat2`, `lng2` | metros | `geo.dist_m` |
| `closeness` | `meters` | 0 a 1 | `search._closeness` |
| `distance_to_line` | `lat`, `lng`, `coords` (`[[lat, lng], ...]`) | metros | `street_lines.distance_to_line` |
| `score` | `full`, `partial`, `rank`, `place_rank`, `mun_hits`, `mun_words`, `cover` (`null`: busca só pela categoria), `distance_m` (`null`: sem posição) | a nota | `search.score` |
| `label` | `name`, `kind`, `house_number`, `district`, `municipality` | o rótulo | `search.Result.label` |

### `search`: as buscas

```json
{
 "id": "GO-numero_casa", "type": "numero_casa", "origin": "receita", "uf": "GO", "db": "GO",
 "query": "avenida castelo branco 202 goiania", "limit": 10,
 "expected": [
  {"name": "Avenida Castelo Branco", "cls": "street", "kind": "highway=trunk", "municipality": "Goiânia",
   "district": "Aeroviário", "lat": -16.672378, "lng": -49.302206, "house_number": 202,
   "label": "Avenida Castelo Branco, 202, Aeroviário, Goiânia",
   "hits": 3, "house": true, "elsewhere": false, "kind_match": false, "score": 0.971764706},
  ...
 ],
 "compare": {"order_exact": 3, "same_set": 8, "score_tol": 1e-06, "coord_tol_m": 1.5, "distance_tol_m": 0.5},
 "trace": {"folded": "...", "corrected": "...", "forced": null, "words": [...], "text": [...], "kinds": [],
           "category_words": [], "municipality": "Goiânia", "house_number": 202}
}
```

- **Entrada:** `db` (o banco: a UF ou `base`), `query` (o texto como foi digitado, com acento, maiúscula e Unicode
  como vier), `near` (`[lat, lng]`, só quando a busca é feita de uma posição) e `limit`. `type` e `origin` só
  classificam o caso (abaixo); `known_gap: true` marca uma [lacuna conhecida](#lacunas-conhecidas).
- **Saída esperada:** os `limit` primeiros resultados da referência (menos, se ela achou menos; `[]` se nada), na
  ordem. Cada um com o que o identifica **de forma estável entre portes**: `name`, `cls`, `kind`, `municipality` (o
  nome) e o ponto `lat`, `lng` (em graus, 6 casas; o do número da casa, interpolado na escada); o `id` do registro não
  entra (muda a cada geração). E mais: `district`, `house_number`, `label`, `distance_m` (com `near`) e os
  **critérios da ordem** ([`CONSUMO.md`](CONSUMO.md), passo 9): `hits` (palavras casadas no nome), `house` (a rua com
  o número na escada), `elsewhere` (fora do município citado), `kind_match` (do tipo da categoria) e `score` (a nota,
  arredondada a 9 casas, como na ordenação).
- **`trace`**, as etapas da análise da referência, para diagnóstico: o texto dobrado, o corrigido (erros de
  digitação), o da troca forçada quando a busca não achou nada (`forced`), as palavras sem as vazias (`words`), as de
  texto (`text`), os tipos da categoria ou marca (`kinds`), as palavras da categoria, o município citado e o número da
  casa. Não é comparado como falha: quando uma busca falha, o verificador mostra a primeira etapa que difere.

### `which_street`: "que rua é esta?"

`{"id": "GO-que_rua-rua", "db": "GO", "lat": -16.660233, "lng": -49.329062, "expected": {"name": "Avenida
Anhanguera", "cls": "street", "kind": "highway=trunk", "municipality": "Goiânia", "district": "Capuava", "lat":
-16.65611, "lng": -49.32943, "distance_m": 8.02}, "compare": {"coord_tol_m": 1.5, "distance_tol_m": 0.5}}`. O ponto
do registro é o da rua (o `item`), e `distance_m` a distância do ponto até o traçado; `expected` `null` quando não há
rua a até 75 m.

## Como comparar

O que um verificador faz, para cada caso (é `conformance.compare_search`, `compare_which_street` e `compare_unit`):

1. **O mesmo registro** é o mesmo `name`, `cls`, `kind` e `municipality`, com o ponto a até `coord_tol_m` metros
   (1,5 m).
2. **Busca:**
   1. o mesmo número de resultados (com o mesmo `limit`);
   2. nas `order_exact` primeiras posições (3, ou menos se houver menos resultados), o mesmo registro na mesma
      posição;
   3. nas `same_set` primeiras (todas as esperadas), os mesmos registros, em qualquer ordem;
   4. em cada registro casado: `hits`, `house`, `elsewhere`, `kind_match`, `district` e `house_number` iguais, a nota a
      até `score_tol` (10⁻⁶) e `distance_m` a até `distance_tol_m` (0,5 m).
3. **"Que rua é esta?":** `null` se e só se esperado `null`; senão o mesmo registro e `distance_m` a até 0,5 m.
4. **Funções puras:** valores JSON iguais, com os números com vírgula a até `tol`; booleano não é número.
5. Um caso `informative` ou `known_gap` que difere é **aviso**; os outros, **falha**. O porte passa quando não há
   falha.

A tolerância de cada caso sai da própria referência: se duas notas vizinhas são quase iguais (diferença menor que
10⁻⁶ e maior que zero, com os outros critérios iguais), um porte pode trocá-las por arredondamento, e o gerador baixa
`order_exact` (ou `same_set`, na fronteira do `limit`) para antes delas. Na geração 2026-11-10-c17dff60 nenhum caso
precisou disso. Notas exatamente iguais não trocam: o desempate é o tamanho do nome e o `id`, e o porte lê o mesmo
banco.

## A receita

Os casos de busca vêm de duas fontes, nesta ordem (uma busca repetida, mesmo banco, texto e posição, entra uma vez):

1. **As travas** (`origin: "buscas.json"`, `type: "trava"`): todos os casos de
   [`gerador/buscas.json`](../gerador/buscas.json) das UFs geradas, com o texto e a posição deles, ids
   `trava-<UF>-<n>` na ordem do arquivo. O conjunto não diminui quando o `buscas.json` cresce.
2. **A receita por UF** (`origin: "receita"`, ids `<UF>-<tipo>`, `-2` na segunda do mesmo tipo), escolhida das
   tabelas do próprio banco, sem sorteio: o "mais importante" é sempre o de maior `rank` e, no empate, o menor `id`.
   A posição (`near`) é a sede da capital (tabela `municipality`). O rodízio usa a posição da UF em ordem alfabética
   (AC 0, AL 1... TO 26).

| `type` | O caso |
|---|---|
| `municipio` | A capital escrita como o IBGE escreve ("Florianópolis", acento e maiúscula); e o município mais importante depois dela (no DF, o lugar mais importante), dobrado |
| `normalizacao` | A capital escrita de outro jeito, em rodízio: maiúsculas ("GOIÂNIA"), letras matemáticas em negrito ("𝐌𝐚𝐜𝐞𝐢𝐨́"), largura total ("Ｍａｎａｕｓ") e "Cidade de Campo-Grande." (pontuação e a expressão dispensável) |
| `erro_digitacao` | A capital e o bairro (com a capital) com um erro: na palavra mais longa só de letras, de 4 letras ou mais, as duas letras do meio trocadas de lugar ("goiania" → "goainia"; iguais, a do meio sai) |
| `bairro` | O bairro (`place=suburb`, `neighbourhood` ou `quarter`) mais importante da capital, com a capital |
| `rua` | A avenida mais importante da capital (senão a rua), com "avenida" abreviada ("av anhanguera goiania") |
| `prefixo` | A mesma, sem a capital e com a última palavra pela metade, pelo menos 3 letras ("av anhan"): o autocompletar |
| `rua_comum` | O nome de rua mais repetido da UF que existe na capital, com a capital ("rua 2 goiania") |
| `categoria` | "hospital" e a capital |
| `categoria_perto` | "posto" da sede da capital |
| `marca` | Da sede, em rodízio: "ipiranga", "shell", "petrobras", "posto shell" |
| `frase_categoria` | Da sede, em rodízio: "posto de saude", "pronto socorro", "caixa eletronico", "lava jato", "posto de gasolina", "area de descanso" |
| `numero_casa` | Na rua da capital com escada do CNEFE mais importante em que a referência acha o número (das 30 primeiras): um par entre os dois degraus do meio do primeiro pedaço do lado par (interpolado) com a capital ("avenida castelo branco 202 goiania"), e o degrau do meio do lado ímpar com "n" antes ("avenida castelo branco n 669") |
| `rodovia` | A BR do município mais importante da UF que tem uma, com o município ("br-101 joinville") |
| `lacuna` | As [lacunas conhecidas](#lacunas-conhecidas) (em GO) |
| `base` | Na base: em cada UF, o segundo município mais importante (no DF, o único) com a sigla ("joinville sc"); e "br 101", "BR-116", "br 153 goias" |

"Que rua é esta?" (`which_street`), em cada UF: um ponto 8 m ao lado do meio do primeiro segmento do traçado da
avenida da capital (`<UF>-que_rua-rua`) e o primeiro ponto em volta da sede, a 0,02°, 0,05°, 0,1° ou 0,2° nas 8
direções, sem rua a até 75 m (`<UF>-que_rua-sem_rua`).

As funções puras são uma lista fixa de entradas em `sabia/conformance.py` (`unit_inputs`), escolhidas pelos pontos que
mais divergem num porte ([abaixo](#onde-um-porte-costuma-divergir)); a saída é a da referência.

### Casos levados às travas

A mesma receita propôs 4 casos por UF para o [`buscas.json`](../gerador/buscas.json) das 25 UFs que só tinham 3
(`python scripts/build_conformance.py --dbs PASTA --validation-candidates`), no formato das travas e com folga, para
a geração não ficar mais frágil: o nome da capital com o erro de digitação (o município em 1º), "posto" da sede (um
posto a até 3 km em 1º), "hospital <capital>" (um hospital da capital até o 3º) e a rua da capital com o número da
casa (a rua com o número até o 3º). Só entra o que a trava aceita na geração atual: no MA, "sao lius" não é corrigido
("Lius" existe no pacote, na Vila São Lius), e o caso ficou de fora. Com eles, o `buscas.json` passou de 168 para 267
casos, 6 ou mais por UF (GO 72, DF 21, MA 6, as outras 7), e todos passam na geração 2026-11-10-c17dff60, também no
SQLite 3.22.

## O conjunto da geração 2026-11-10-c17dff60

- **935 casos:** 241 das funções puras, 640 buscas e 54 de "que rua é esta?".
- **Arquivo:** 134 kB compactado (`sabia-conformidade.json.zst`), 1,9 MB de JSON; 4.901 resultados esperados.
- **Buscas por tipo:** `trava` 267, `municipio` 37, `erro_digitacao` 30, `base` 30, `numero_casa` 29, `bairro` 27,
  `rua` 27, `prefixo` 27, `rua_comum` 27, `normalizacao` 27, `categoria_perto` 27, `marca` 27, `frase_categoria` 27,
  `rodovia` 26, `lacuna` 3, `categoria` 2 (o "hospital <capital>" das outras 25 UFs já está nas travas).
- **Por banco** (buscas e "que rua é esta?"): GO 92, DF 38, a base 30, AM, CE, ES, MT, PA, PE, RJ, SE e SP 22, as
  outras 21.
- **Funções puras:** `fold` 35, `options` 17, `house_number_in` 18, `name_score`, `name_cover` e `name_hits` 16 cada,
  `ladder_position` 15, `correct` 14, `parse` 14, `edit_distance` 13, `same_sound` 12, `max_errors` 11,
  `index_text` 10, `closeness` 9, `cell` 7, `dist_m` 4, `distance_to_line` 4, `score` 4, `label` 4, `cells_around` 2.
- Medido aqui, as 27 UFs e a base: pouco mais de 1 min para fazer o conjunto e a referência conferir.

## Como a geração publica

Depois das travas (etapa `validate`), a etapa `conformance` do `generate.py` faz o conjunto sobre os bancos de
`data/build/`, roda a própria referência contra ele (tem de passar inteira; senão a geração para, sem catálogo) e grava
`data/dist/sabia-conformidade.json.zst` e o `.sha256` ao lado. O `scripts/publish.py` não publica uma geração sem o
conjunto, com o `.sha256` que não bate ou com o conjunto de outra geração ou formato, e sobe os dois arquivos na
release, depois dos pacotes. A etapa build apaga o conjunto da geração anterior em `data/dist/`.

À mão, sobre os bancos de uma release:

```
gh release download 2026-11-10-c17dff60 -R Murkiriel/sabia -p 'sabia-*.sqlite.zst' -D bancos
(cd bancos && for f in *.zst; do zstd -d "$f"; done)
python scripts/build_conformance.py --dbs bancos --out sabia-conformidade.json.zst
python scripts/check_conformance.py sabia-conformidade.json.zst --dbs bancos
python scripts/check_conformance.py conformidade-exemplo.json    # só as funções puras, sem bancos
```

O exemplo versionado sai de `--example conformidade-exemplo.json`; os testes conferem que as funções puras dele são as
da referência de hoje (mudou o código da busca, regenere o exemplo).

## Como um porte usa

1. **Baixe** o conjunto da mesma geração dos bancos que o porte usa: `<release_url>sabia-conformidade.json.zst` do
   `catalogo.json` (ou o exemplo do repositório, para começar sem rede), confira o sha256 com o
   `sabia-conformidade.json.zst.sha256` e descompacte (zstd). Recuse `conformance_version` maior que a conhecida.
2. **Abra os bancos** de `packages` e confira `meta.build_id`: de outra geração, pule os casos dele (e diga).
3. **Escreva o adaptador**, as quatro chamadas da classe `Reference` de
   [`sabia/conformance.py`](../gerador/sabia/conformance.py), que devolvem os mesmos campos que a referência:
   - `unit(fn, args)`: chama a função do porte; as que precisam de regras (`options`, `name_*`, `parse`, `correct`)
     montam as regras a partir de `rules` e `unit_fixtures` do arquivo, não do banco;
   - `search(db, query, near, limit)`: a busca do porte, cada resultado com `name`, `cls`, `kind`, `municipality`,
     `district`, `lat`, `lng` (em graus; o do número da casa, interpolado), `house_number`, `distance_m` (com `near`) e,
     se o porte os expõe, os critérios `hits`, `house`, `elsewhere`, `kind_match` e `score` (sem eles, só não são
     comparados);
   - `which_street(db, lat, lng)`: a rua, com `distance_m`, ou nada;
   - `trace(...)`, opcional, as etapas da análise.
4. **Compare** como em [Como comparar](#como-comparar) e falhe o teste se houver falha.

Em **Kotlin** (Android): as funções puras num teste de JVM comum (JUnit), com o exemplo em `src/test/resources`; as
buscas num teste instrumentado, no aparelho ou no emulador, com os bancos da geração copiados para o armazenamento do
app: o SQLite que vale é o do aparelho (FTS4, sem FTS5). Para o `fold`: `s.lowercase(Locale.ROOT)`, depois
`java.text.Normalizer.normalize(s, Normalizer.Form.NFKD)`, depois tirar cada caractere com classe combinatória
diferente de 0 (`android.icu.lang.UCharacter.getCombiningClass(cp) != 0`; `Character.getType(cp) ==
Character.NON_SPACING_MARK` dá o mesmo no português, não em todas as escritas) e trocar por espaço o que não é letra
nem número (`Character.isLetterOrDigit` não basta: `Character.isLetter(cp) || Character.getType(cp)` em
`DECIMAL_DIGIT_NUMBER`, `LETTER_NUMBER` ou `OTHER_NUMBER`), percorrendo por **code point**.

Em **JavaScript** (web): `s.toLowerCase().normalize("NFKD")`, tirar `/\p{M}/gu` (o mesmo no português; a referência
tira só as marcas de classe combinatória diferente de 0, e marcas como a vogal `ि` do devanágari viram espaço nela: os
casos `informative`), trocar `/[^\p{L}\p{N}]+/gu` por espaço; os tamanhos e índices de palavra por code point
(`[...palavra]`), não por `length`. As buscas com o SQLite da plataforma (num navegador, um SQLite em WebAssembly
compilado com FTS4), os bancos da geração e o mesmo `limit`; o verificador pode ser um teste do Node que lê o
`.json.zst` (por exemplo com um descompactador zstd em WebAssembly) ou o JSON já descompactado.

## Onde um porte costuma divergir

Os casos das funções puras cobrem estes pontos:

- **`fold`:** as minúsculas vêm **antes** da decomposição NFKD. Uma maiúscula que só a decomposição revela (as letras
  matemáticas: "𝐆" vira "G") fica maiúscula: `fold("𝐆𝐨𝐢𝐚̂𝐧𝐢𝐚")` é `"Goiania"`, não `"goiania"` (o FTS4 acha do
  mesmo jeito, porque o tokenizador `simple` põe em minúscula as letras ASCII da consulta; o município citado e o
  vocabulário, não). "º" e "ª" viram "o" e "a" ("nº" é o conector `no`), o hífen suave e a junção de largura zero
  separam palavras, "ß", "æ", "ø" e "đ" ficam. Os casos de outras escritas são `informative`.
- **Números:** "dígito" é o decimal do Unicode, como o `str.isdigit` do Python (na prática, 0 a 9 depois do `fold`);
  um número por extenso casa só inteiro ("10" e "dez", nunca "dezesseis"); no índice, "um" e "uma" não ganham o "1"
  (`index_text("Rua Um")` é `"rua um"`), só o "1" ganha o "um".
- **Distância de edição:** a de transposição simples (OSA), não a de Damerau completa: `edit_distance("ca", "abc")` é 3.
- **Tamanhos por code point**, não por unidade UTF-16 (`String.length` do Kotlin e do JavaScript), em `max_errors`, no
  prefixo da última palavra e no desempate pelo tamanho do nome.
- **Ordem das alternativas** (`options`): a própria palavra primeiro, depois as outras em ordem de code point de
  `(termo, inteiro?)`; as combinações seguem o produto cartesiano (a última palavra varia mais rápido), cortado em
  `MAX_COMBINATIONS` (16). Uma ordem diferente muda quais combinações sobram.
- **Consultas:** uma `MATCH` por combinação, cada uma com `LIMIT 2000` (`MAX_ROWS`), na ordem do `docid`; nada de `OR`
  dentro da `MATCH`. A busca no vocabulário compara bytes (`word >= ? AND word < ?||'{'`).
- **Nota:** a soma na ordem de `search.score` e arredondada a 9 casas antes de ordenar (`round` do Python, metade
  para o par sobre o valor binário); compare com tolerância. A distância é a do plano local com o cosseno da latitude
  média (`geo.dist_m`), e `closeness` usa `log10`.
- **Coordenadas:** inteiros do banco ÷ 100.000; o "que rua é esta?" mede num plano local com o cosseno da latitude do
  ponto, e o ponto do número da casa interpola lat e lng separadamente entre os degraus.

## Lacunas conhecidas

`-16.68, -49.25` (coordenada digitada), `74115-030` e `cep 74115030` (CEP) não acham nada: a busca por coordenada
digitada não existe e o CEP não é exportado nos pacotes. Os três ficam no conjunto (`type: "lacuna"`, `known_gap:
true`) com o resultado vazio da referência; um porte que já os resolva recebe aviso, não falha.

## O que fica de fora

- **Juntar vários bancos:** [`CONSUMO.md`](CONSUMO.md) manda rodar a busca em cada estado instalado e juntar pela
  mesma ordem, mas a referência busca um banco por vez; cada caso tem um banco só.
- **O bairro de um ponto** (os polígonos de `district`) e o "mais perto" fora da busca por categoria não estão em
  `search.py` e não têm casos.

## O catálogo

O `catalogo.json` não tem (ainda) a chave do conjunto: o formato comum do catálogo está sendo definido à parte. Quando
entrar, a proposta é uma chave de topo, ao lado de `base` e `states`:

```
"conformance": {
  "file": "sabia-conformidade.json.zst",   o arquivo na release (release_url + file)
  "bytes": 134029,                         o tamanho do .zst
  "sha256": "...",                         o mesmo do .sha256 ao lado
  "conformance_version": 1,                a versão do formato do conjunto
  "cases": {"unit": 241, "search": 640, "which_street": 54}
}
```

Até lá, o `.sha256` ao lado do arquivo na release faz o papel do `sha256`.
