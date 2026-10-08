# Formato dos pacotes

Cada pacote é um banco **SQLite** compactado em **zstd** (nível 19, com o tamanho original e o checksum no cabeçalho
do quadro). Descompacte uma vez, na instalação, e abra o `.sqlite` no lugar, só leitura. O banco usa só o que o
SQLite do Android tem desde o 3.22 (Android 10): **FTS4**, sem FTS5 e sem R-Tree, em modo rollback (não WAL).

A versão do formato está em `meta.format_version` e no `catalogo.json` (`format_version`). Quem consome **recusa uma
versão maior** que a que conhece. A versão sobe quando muda algo que um leitor antigo não entenderia (tabela ou
coluna renomeada ou removida, valor que muda de significado); tabelas e colunas novas não sobem a versão.

## Banco do estado (`sabia-<UF>.sqlite`)

| Tabela | Colunas | O que é |
|---|---|---|
| `meta` | `key`, `value` | `format_version`, `build_id`, `uf`, `osm_timestamp`, `attribution` |
| `municipality` | `id`, `name`, `lat`, `lng` | Os municípios do estado: `id` é o código do IBGE (7 dígitos), o ponto é a sede |
| `district` | `id`, `municipality`, `name`, `kind`, `lat`, `lng`, `polygon` | Os bairros. `kind`: `suburb`, `quarter`, `neighbourhood`, `admin_level=10`, `admin_level=9`. `polygon` NULL: bairro conhecido só por um ponto |
| `item` | `id`, `cls`, `kind`, `name`, `municipality`, `district`, `lat`, `lng`, `cell` | Os registros (abaixo) |
| `item_text` | `name`, `area` (FTS4, `docid` = `item.id`) | O índice de busca |
| `street_line` | `item`, `cell`, `coords` | O traçado das ruas, para "que rua é esta?" |
| `word_form` | `word`, `form`, `rule` | Abreviações, formas e números (regras de busca) |
| `category` | `word`, `kinds` | Palavras de categoria: "posto" → `amenity=fuel` |
| `item_source` | `item`, `source` | A origem dos registros cuja posição não foi conferida no mapa: `anp` (posto que só a ANP tem). Só os marcados; o registro que não está aqui veio do mapa. Pacote anterior: sem a tabela |

Índices comuns: `item_cell` em `item(cell)` e `street_line_cell` em `street_line(cell)`.

### `item`

| `cls` | `kind` | O que é |
|---|---|---|
| `place` | `municipality` | O município, com o nome oficial do IBGE, na sede |
| `place` | `place=<valor>` | Lugar com nome do OpenStreetMap: `city`, `town`, `village`, `hamlet`, `suburb`, `neighbourhood`, `quarter`, `locality`, `isolated_dwelling`, `farm`, `island`, `islet` |
| `place` | `ibge=<categoria>` | Localidade da Base de Localidades do IBGE (2022) que o OpenStreetMap não tem com o mesmo nome a até 3 km no mesmo município: `povoado`, `vila`, `lugarejo`, `nucleo_urbano`, `nucleo_rural`, `agrovila`, `indigena`, `quilombola`, `regiao_administrativa`, `distrito_estadual`; `localidade` para as outras (e para uma categoria nova do IBGE). As sedes municipais não entram: são o `municipality` |
| `street` | `highway=<valor>` | Uma rua: os trechos de mesmo nome no mesmo município que se tocam ou têm as pontas a menos de 60 m. O `kind` é o do trecho mais importante; o ponto, o meio do trecho mais central |
| `road` | `road` | Uma rodovia num município: `name` é a sigla (`BR-153`, `GO-060`) |
| `poi` | `<chave>=<valor>` | Ponto de interesse: `amenity=fuel`, `shop=tyres`, `tourism=hotel`, `natural=waterfall`, `aeroway=aerodrome`, `barrier=toll_booth`... Os de viagem (posto, hospital, clínica, polícia, farmácia, recarga, borracharia, oficina, pedágio, áreas de descanso) entram também sem nome: `name` é a marca (`brand`) ou vazio |
| `poi` | `amenity=police` (PRF) | Unidade da Polícia Rodoviária Federal (ANTT) que o OpenStreetMap não tem: `name` é "PRF - Polícia Rodoviária Federal, BR-060 km 182" |
| `poi` | `overture=<categoria>` | Lugar de comércio ou serviço da Overture Maps sem `kind` equivalente do OpenStreetMap que a busca use: `overture=clothing_store`, `overture=beauty_salon`, `overture=dental_clinic`... (a categoria da Overture, em inglês). Os que têm equivalente (posto, farmácia, hotel, restaurante, oficina, borracharia, banco, escola, igreja...) entram com o `kind` do OpenStreetMap |
| `poi` | `highway=milestone` | Marco de km de rodovia federal, gerado ao longo do SNV do DNIT: `name` é "BR-060 km 120". O km é o do SNV (recomeça em cada estado); em trechos concedidos com numeração antiga, a placa da estrada pode estar a alguns km |
| `poi` | `aeroway=aerodrome` (ANAC) | Aeródromo público ou privado da ANAC que o OpenStreetMap não tem: "Aeródromo Fazenda Boa Vista (SWXX)", com o código OACI no fim |
| `poi` | `natural=*`, `tourism=*`, `leisure=park`, `boundary=national_park` (GeoNames, Wikidata) | Cachoeira, caverna, praia, pico, fonte, parque, mirante ou atração turística do GeoNames ou do Wikidata que o pacote não tinha |
| `poi` | `amenity=fuel` (ANP) | Posto em operação da ANP que o pacote não tinha: "Posto Ipiranga", "Posto Petrobras" (bandeira Vibra), "Posto Shell" (Raízen) ou a razão social. Um posto do OpenStreetMap sem nome a até 100 m de um da ANP fica com o nome dele. O que só a ANP tem está em `item_source` com `anp`: o ponto é o declarado à ANP, sem um posto no mapa que o confirme |
| `poi` | `amenity=hospital` (CNES) | Hospital, UPA ou pronto-socorro aberto 24 horas do CNES que o OpenStreetMap não tem: `name` é o nome fantasia do cadastro em caixa de título ("Hospital Municipal de Itaberaí") |

- Os registros de outras fontes que não o OpenStreetMap usam o `kind` do OpenStreetMap equivalente quando há um
  (a PRF é `amenity=police`; o CNES, `amenity=hospital`; um posto da Overture, `amenity=fuel`): as palavras de categoria e os ícones valem para eles sem mudar nada em quem consome.
- `municipality`: código do IBGE do município do registro; `district`: o `district.id` do bairro, ou NULL.
- `lat`, `lng`: inteiros, graus × 100.000 (5 casas, ~1 m).
- `cell`: o quadrado do mapa no zoom 13 (o tile dos mapas na web, ~4 a 5 km de lado no Brasil), como um número:
  `x × 8192 + y`, com `x = floor((lng + 180) / 360 × 8192)` e
  `y = floor((1 − asinh(tan(lat em radianos)) / π) / 2 × 8192)`. "Mais perto" e "que rua é esta?" olham os 9
  quadrados em volta do ponto: `(x + dx) × 8192 + (y + dy)`, com `dx` e `dy` de −1 a 1.

### `item_text`

FTS4 sem conteúdo (`content=""`), tokenizador `simple`, prefixos de 2 e 3 letras (`prefix="2,3"`). O texto já vem
**dobrado**: sem acento, minúsculo, pontuação virando espaço ("Avenida T-63" → `avenida t 63`).

- `name`: o nome dobrado (e os nomes alternativos do GeoNames e do Wikidata, quando há: "bonfim" acha Silvânia; o
  nome mostrado continua o de `item.name`), com cada número também na outra forma logo depois ("Rua 14" → `rua 14 quatorze catorze`;
  "Rua Quatorze" → `rua quatorze 14`).
- `area`: o município e o bairro, dobrados (`goiania setor oeste`).

Como a tabela não guarda o texto, leia o nome em `item.name` (`JOIN item ON item.id = item_text.docid`).

### `street_line`

Cada trecho de rua com nome (e cada trecho sem nome de uma rodovia), simplificado a 10 m e cortado em pedaços de até
2 km. `item` é o `item.id` da rua (ou da rodovia); `cell` é o quadrado do meio do pedaço; `coords` são int32
little-endian, `lat, lng, lat, lng...` × 100.000. Para achar a rua de um ponto: os pedaços dos 9 quadrados em volta,
a distância do ponto até cada segmento, o menor.

### `district.polygon`

Os anéis do polígono (externos e buracos), simplificados a 10 m. Cada anel é int32 little-endian: o número de
vértices `n` e depois `n` pares `lat, lng` × 100.000, sem repetir o primeiro vértice no fim. Dentro ou fora pela
regra par-ímpar sobre todos os anéis.

### `word_form` e `category`

Tudo dobrado. Ver as regras de uso em [`CONSUMO.md`](CONSUMO.md).

| `rule` | Exemplo | O que vale |
|---|---|---|
| `abbr` | `dr` → `doutor` | Nos dois sentidos |
| `form` | `rodoviaria` → `rodoviario` | A outra forma da mesma palavra |
| `number` | `14` → `quatorze` | Número e número por extenso (o índice já tem os dois) |
| `drop_prefix` | `cidade de` → (vazio) | Expressão que pode ser ignorada no começo da busca |

`category.kinds`: os `kind` da palavra, separados por vírgula (`oficina` → `shop=car_repair,shop=motorcycle_repair`).

## Base nacional (`sabia-base.sqlite`)

| Tabela | O que é |
|---|---|
| `meta` | Como no estado, com `uf` = `base` |
| `municipality` | `id`, `name`, `uf`, `lat`, `lng`: todos os municípios do país |
| `item` | Os municípios (`cls` `place`, `kind` `municipality`) e as rodovias federais (`cls` `road`, um registro por sigla, no município do trecho mais central) |
| `item_text` | Como no estado; `area` é o nome do estado e a sigla (`goias go`) |
| `road_state` | `item`, `uf`: os estados de cada rodovia federal |
| `word_form`, `category` | Como no estado |

Com a base, "Pirenópolis" é achada sem nenhum estado instalado, e a UF diz qual pacote baixar.
