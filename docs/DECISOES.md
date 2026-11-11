# Decisões

Registro do que foi decidido em 2026-10-05 (D1 a D12), depois das medições resumidas no fim deste documento, e em
2026-11-11 (D13 e D14). Todas as propostas abaixo foram aceitas como estão; onde o que foi feito saiu diferente do
decidido (D1, D9, D10), a seção da decisão diz como ficou.

## Resumo

| # | Decisão | Escolha |
|---|---|---|
| D1 | Repositório | Público, anônimo, com a convenção de nomes e idiomas do README (público de fato desde 2026-11-11) |
| D2 | Formato do pacote | SQLite com FTS4, lido pelo SQLite do sistema; um arquivo por estado mais uma base nacional |
| D3 | Compactação | zstd nível 19; o banco é descompactado uma vez, na instalação |
| D4 | O que entra na etapa A | Lugares, ruas, rodovias por município e pontos de interesse do OpenStreetMap, mais os polígonos de bairro |
| D5 | Regra de juntar ruas | Mesmo município, mesmo nome, trechos que se tocam ou com as pontas a menos de 60 m |
| D6 | "Que rua é esta?" | Entra na etapa A, com o traçado de cada trecho simplificado a 10 m |
| D7 | Tipos de ponto de interesse | Todos os que têm nome, mais os de viagem sem nome, mais aeroporto, cachoeira, pico, mirante e autódromo |
| D8 | Regras de busca | Tabelas dentro do pacote: abreviações, formas, números por extenso, categorias, "cidade de" dispensável |
| D9 | Endereço com número (etapa B) | Depois da etapa A, pelo CNEFE do IBGE; feito como a escada de números de cada rua, sem quadra e lote (abaixo) |
| D10 | Postos da ANP (etapa C) | Depois da etapa A; feito com o ponto que a API da ANP traz, não pelo CNEFE (abaixo) |
| D11 | Ciclo | A cada 29 dias, dois disparos diários, geração extra por data, 3 gerações guardadas |
| D12 | Nome | Sabiá (`sabia`) é o nome definitivo |
| D13 | Coordenadas (2026-11-11) | WGS84; latitude primeiro no banco e no `bbox` do catálogo, mantida (não migra para a ordem do GeoJSON) |
| D14 | Reprodutibilidade (2026-11-11) | Só a geração corrente; dependências travadas com hash e actions fixadas pelo SHA |

## D1: repositório público

Decidido como "público desde o começo", mas o repositório ficou **privado até 2026-11-11**: o `catalogo.json` e os
pacotes das releases respondiam 404 a quem não tinha acesso, e o app consumidor não conseguia baixá-los. Em 2026-11-11
o histórico (45 commits) foi conferido (sem segredos, e-mails pessoais ou caminhos de máquina) e o repositório
**passou a ser público**; desde então o `catalogo.json` (pelo `raw.githubusercontent.com` também) e os pacotes
respondem sem autenticação.

## D2: SQLite com FTS4, lido pelo SQLite do sistema

O SQLite que vem no Android é compilado com FTS3 e FTS4, **sem FTS5 e sem R-Tree**. Um banco de teste de Goiás
(121 mil registros, FTS4 sem conteúdo duplicado, tokenizador simples, prefixos de 2 e 3 letras) abriu no SQLite 3.22
do Android 10 e respondeu igual ao do computador, de 0 a 5 ms por consulta. FTS5 e R-Tree deram "no such module".

Consequências:

- O FTS4 não ordena por relevância: a ordenação fica no código de quem consome (as regras são as de D8).
- "Mais perto" não usa R-Tree: cada registro tem o número do quadrado do zoom 13 (~5 km, `cell`), e a busca olha os 9
  quadrados em volta, com um índice comum.
- O texto do índice vem sem acento e em minúsculas, feito pelo gerador: quem consome não depende de como o SQLite do
  aparelho trata acento.

## D3: zstd 19

Um terço do tamanho do banco, ou menos, e rápido de descompactar com pouca memória. O banco é descompactado uma vez, na
instalação, e lido no lugar.

## D4: o que entra

| Classe (`cls`) | O que entra |
|---|---|
| `place` | Pontos `place=` com nome (cidade, vila, povoado, bairro, localidade) e as áreas de bairro sem ponto |
| `street` | Vias com nome, com os trechos da mesma rua juntados (D5) |
| `road` | Uma por rodovia (`ref`) em cada município: "BR-153 em Anápolis" |
| `poi` | Pontos de interesse (D7) |

Os municípios vêm do IBGE, não do OpenStreetMap: muita sede de município está marcada como vila no OpenStreetMap, e
somando cidades e vilas grandes dá menos que os 5.570 municípios.

**Bairros por polígono.** As relações do OpenStreetMap trazem pouco em nomes (+1,7% de registros em Goiás), mas muito
em bairros: 750 bairros de Goiás só existem desenhados como área. Com o polígono, o bairro de cada rua sai de "a rua
está dentro do bairro"; o ponto de bairro mais próximo (até 3 km) fica como reserva, porque acerta em só 73% das ruas.

## D5: juntar os trechos de uma rua

No mesmo município e com o mesmo nome, os trechos que se tocam (mesmo nó) ou cujas pontas ficam a menos de 60 m viram
um registro. Medido em Goiás:

| Regra | Registros | Av. Anhanguera, Goiânia | Av. Goiás, Goiânia | Rua local juntada com mais de 3 km |
|---|---:|---:|---:|---:|
| Meio dos trechos a menos de 440 m | 78.112 | 8 | 1 | 140 |
| Trechos que se tocam | 83.654 | 11 | 4 | 148 |
| **Se tocam, ou as pontas a menos de 60 m** | **74.795** | **5** | **1** | 161 |

"Se tocam" sozinho separa demais (rotatória, pista dupla, um pedaço sem nome no meio). As "Rua 10" de setores
diferentes ficam separadas. Juntar errado aparece como uma rua local com mais de 3 km de ponta a ponta: esses casos
vão para o relatório de cada geração.

## D6: "que rua é esta?"

O traçado de cada trecho de rua, simplificado a 10 m, acertou a rua de 99% de 4.000 pontos de teste em Goiás com
8 MB a mais; um ponto a cada 50 m acertou 95% com 47 MB, e um ponto por trecho, 60%.

## D7: pontos de interesse

Entram os pontos e áreas com `amenity`, `shop`, `tourism`, `leisure`, `craft`, `office`, `healthcare`, `emergency`
ou `historic` que têm nome, e os de viagem mesmo sem nome (posto, hospital, polícia, farmácia, borracharia, oficina,
pedágio e parecidos). Numa comparação de 50 buscas em Goiás com um geocodificador online feito do mesmo
OpenStreetMap, faltaram tipos que agora entram: aeroporto (`aeroway`), cachoeira, pico, mirante e autódromo.

## D8: regras de busca dentro do pacote

As 50 buscas de Goiás acertaram o primeiro resultado em 37; os erros pediram regras que vão em tabelas dentro do
pacote, para melhorar sem trocar o código de quem consome:

- **Abreviações:** "av" → avenida, "r" → rua, "cap" → capitão, "dr" → doutor.
- **Formas:** "rodoviária" e "rodoviário".
- **Números por extenso:** "14" e "quatorze" casam (o gerador grava as duas formas no índice).
- **Categorias:** "posto" vira filtro de `amenity=fuel`, e a busca passa a ser por distância.
- **"cidade de" dispensável** no começo ("cidade de goiás").
- **Município na busca** (regra de quem consome): a palavra que é o nome inteiro de um município puxa os registros
  dele, para "rua 90 goiania" não trazer primeiro a de Aparecida de Goiânia.

## D9 e D10: etapas B e C

Ficam para depois da etapa A.

- **B, endereço com número:** o OpenStreetMap tem 1,6 milhão de endereços com número no país, contra 111 milhões no
  CNEFE do IBGE (Censo 2022). Goiás, por face de quadra (primeiro e último número, o resto calculado), dá 13 MB com
  6 m de erro na mediana; 65% dos endereços de Goiás são de quadra e lote, que precisam entrar junto. A licença: uso e
  redistribuição permitidos com o crédito "IBGE, CNEFE, Censo Demográfico 2022", pela Política de Dados Abertos do
  IBGE.
- **C, postos da ANP:** o OpenStreetMap tem perto de 43% dos 2.071 postos de Goiás registrados na ANP. O cadastro da
  ANP não tem coordenada; a posição sai do endereço, pelo CNEFE.

**Como ficou** (as duas etapas estão em todas as UFs desde a geração 2026-11-10-c17dff60):

- **B:** não por face de quadra nem por quadra e lote. O pacote guarda, para cada rua do mapa que casa pelo nome com
  uma do CNEFE no município, a **escada de números**: por lado (par, ímpar), um degrau (número e ponto do endereço) a
  cada 20 números e o último, e um pedaço novo onde dois números seguidos ficam a mais de 300 m; o resto se interpola
  entre os degraus (Goiás: erro de 12 m na mediana, 92 m no p90). Tabela `house_number` ([FORMATO.md](FORMATO.md));
  medição e escolhas em [ENDERECOS.md](ENDERECOS.md); código em `gerador/sabia/cnefe.py`. **Quadra e lote não
  entraram**: o endereço "SN" com quadra e lote (quase dois terços dos de Goiás) não tem número na escada, e a busca
  trata "quadra" e "lote" só como palavras que levam número no nome.
- **C:** a API de revendedores da ANP já traz o ponto de cada posto (98% deles; Goiás: 2.019 de 2.069),
  enquanto o endereço pelo CNEFE achava lugar para só 26%. O posto entra no ponto que a ANP dá (o declarado à
  fiscalização ou pelo próprio posto); o que só a ANP tem fica marcado com `anp` na tabela `item_source`, porque essa
  posição não foi conferida no mapa. Código em `gerador/sabia/anp.py`.

## D11: ciclo

Uma geração a cada 29 dias, com o extrato do Brasil mais recente; dois disparos agendados por dia (um disparo pulado
pelo GitHub não avisa ninguém), geração extra por data marcada e as 3 gerações mais recentes no ar. O extrato é o do
Brasil inteiro publicado pelo openstreetmap.fr, o mesmo usado por tiles de rota feitos do OpenStreetMap: com o mesmo
extrato, uma rota nunca aponta para uma rua que a busca não conhece.

## D13: coordenadas (2026-11-11)

As coordenadas são WGS84 e vêm sempre com a latitude primeiro: `lat, lng` no banco (inteiros, graus × 100.000) e
`[lat_min, lon_min, lat_max, lon_max]` no `bbox` do `catalogo.json`. É o contrário do GeoJSON e do PMTiles, mas é a
ordem dos catálogos dos outros geradores do mesmo molde, e o app consumidor já a lê: migrar mexeria em todos sem
ganho. A ordem fica e passa a estar escrita em [FORMATO.md](FORMATO.md#coordenadas) e no
[CONSUMO.md](CONSUMO.md); o formato do catálogo não muda.

## D14: reprodutibilidade (2026-11-11)

Só a geração corrente precisa ser reproduzível: as entradas de cada geração (o extrato "latest" do OpenStreetMap e as
fontes baixadas na hora, sem versão fixa) não são arquivadas, e isso está declarado no README. Arquivar as entradas de
cada `build_id` fica para quando houver necessidade de auditar uma geração antiga. Obrigatório desde já: as
dependências do Python travadas, transitivas incluídas, com hash (`gerador/requirements.in` → `requirements.txt`,
instaladas com `--require-hashes`) e as actions fixadas pelo SHA do commit; os testes de
`gerador/tests/test_workflows.py` conferem as duas regras. Registrar o sha256 das entradas no `catalogo.json` mudaria
o formato do catálogo e ficou para depois.

## Medições (2026-10-01 a 2026-10-05)

| Medição | Resultado |
|---|---|
| Tamanho | Brasil inteiro, com o índice de busca: 350 MB (121 MB em gzip); São Paulo 82 MB, Amapá 1 MB |
| Android 10 | O banco FTS4 abre no SQLite 3.22 e responde igual ao computador, em 0 a 5 ms |
| "Que rua é esta?" | O traçado simplificado a 10 m acerta 99% com 8 MB em Goiás |
| Relações do OpenStreetMap | Pouco em nomes (+1,7%); muito em bairros (750 em Goiás) |
| Juntar trechos de rua | "Se tocam ou as pontas a menos de 60 m" |
| 50 buscas em Goiás | O primeiro resultado é o certo em 37 de 50; os erros pedem as regras de D7 e D8 |
| Endereços do IBGE (CNEFE) | Goiás por face de quadra: 13 MB, erro mediano de 6 m |
| Postos da ANP | O OpenStreetMap tem ~43% dos postos de Goiás |
