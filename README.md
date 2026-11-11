# Sabiá — busca de lugares sem internet, por estado

**Busca offline de lugares no Brasil**, a partir do OpenStreetMap: cidades, bairros, ruas, rodovias e pontos de
interesse (postos, borracharias, hospitais, pedágios…) num banco SQLite pequeno por estado, pronto para buscar no
celular sem sinal. O nome vem do trocadilho: o Sabiá **sabia** onde fica.

> **Situação (2026-11-10): publicado.** Uma geração nova a cada 29 dias, com todas as fontes abaixo. O formato está
> em [`docs/FORMATO.md`](docs/FORMATO.md) (tabelas novas são acrescentadas sem mudar a versão); as decisões e as
> medições que levaram a ele, em [`docs/DECISOES.md`](docs/DECISOES.md).

> **Aviso.** Os dados vêm do OpenStreetMap e podem estar incompletos ou errados.

## Baixar por estado

<!-- downloads:start -->
Geração **2026-11-10-c17dff60**: OpenStreetMap de 2026-11-09, formato 1. Baixe a base e os estados que quiser; confira o sha256 pelo [`catalogo.json`](catalogo.json).

| Pacote | Arquivo | Tamanho |
|---|---|---:|
| **Base** (os municípios do Brasil e as rodovias federais) | [sabia-base.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-base.sqlite.zst) | 0,4 MB |
| Acre (AC) | [sabia-AC.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-AC.sqlite.zst) | 1,5 MB |
| Alagoas (AL) | [sabia-AL.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-AL.sqlite.zst) | 3,7 MB |
| Amapá (AP) | [sabia-AP.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-AP.sqlite.zst) | 1,3 MB |
| Amazonas (AM) | [sabia-AM.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-AM.sqlite.zst) | 5,5 MB |
| Bahia (BA) | [sabia-BA.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-BA.sqlite.zst) | 21,3 MB |
| Ceará (CE) | [sabia-CE.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-CE.sqlite.zst) | 11,9 MB |
| Distrito Federal (DF) | [sabia-DF.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-DF.sqlite.zst) | 2,6 MB |
| Espírito Santo (ES) | [sabia-ES.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-ES.sqlite.zst) | 8,0 MB |
| Goiás (GO) | [sabia-GO.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-GO.sqlite.zst) | 10,9 MB |
| Maranhão (MA) | [sabia-MA.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-MA.sqlite.zst) | 7,6 MB |
| Mato Grosso (MT) | [sabia-MT.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-MT.sqlite.zst) | 7,8 MB |
| Mato Grosso do Sul (MS) | [sabia-MS.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-MS.sqlite.zst) | 7,3 MB |
| Minas Gerais (MG) | [sabia-MG.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-MG.sqlite.zst) | 45,6 MB |
| Pará (PA) | [sabia-PA.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-PA.sqlite.zst) | 9,0 MB |
| Paraíba (PB) | [sabia-PB.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-PB.sqlite.zst) | 6,5 MB |
| Paraná (PR) | [sabia-PR.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-PR.sqlite.zst) | 25,6 MB |
| Pernambuco (PE) | [sabia-PE.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-PE.sqlite.zst) | 12,4 MB |
| Piauí (PI) | [sabia-PI.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-PI.sqlite.zst) | 5,5 MB |
| Rio Grande do Norte (RN) | [sabia-RN.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-RN.sqlite.zst) | 6,0 MB |
| Rio Grande do Sul (RS) | [sabia-RS.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-RS.sqlite.zst) | 30,2 MB |
| Rio de Janeiro (RJ) | [sabia-RJ.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-RJ.sqlite.zst) | 22,1 MB |
| Rondônia (RO) | [sabia-RO.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-RO.sqlite.zst) | 3,6 MB |
| Roraima (RR) | [sabia-RR.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-RR.sqlite.zst) | 1,5 MB |
| Santa Catarina (SC) | [sabia-SC.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-SC.sqlite.zst) | 21,8 MB |
| São Paulo (SP) | [sabia-SP.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-SP.sqlite.zst) | 90,2 MB |
| Sergipe (SE) | [sabia-SE.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-SE.sqlite.zst) | 3,7 MB |
| Tocantins (TO) | [sabia-TO.sqlite.zst](https://github.com/murkiriel/sabia/releases/download/2026-11-10-c17dff60/sabia-TO.sqlite.zst) | 3,0 MB |
<!-- downloads:end -->

## O que resolve

1. **Buscar sem internet:** "Rua 10, Setor Oeste", "Avenida Brasil, 1500, Anápolis", "posto ipiranga anápolis",
   "br-153 anápolis", "BR-060 km 120".
2. **Dizer "que rua é esta?"** a partir de uma coordenada (o traçado simplificado de cada rua vai no pacote).
3. **Achar o mais perto** por categoria: "posto", "borracharia", "hospital".

## O pacote

```
sabia-base.sqlite.zst    os 5.571 municípios (nome, UF, ponto da sede, código do IBGE) e as rodovias federais
sabia-<UF>.sqlite.zst    o estado: registros, índice de busca, traçados das ruas, bairros, números das casas,
                         tabelas de busca
catalogo.json            o índice: tamanho, sha256, retângulo e contagens de cada pacote, e a versão do formato
```

Cada pacote é um banco **SQLite com índice FTS4**, que o SQLite do Android (desde o 3.22) lê sem biblioteca a mais,
compactado em **zstd** e descompactado uma vez, na instalação. Um estado não depende do vizinho: cada um pode ser
instalado e atualizado sozinho. Tabelas, colunas e codificações: [`docs/FORMATO.md`](docs/FORMATO.md).

Tamanhos da geração 2026-11-10-c17dff60 (banco aberto, o espaço no aparelho, e compactado, o download):

| Pacote | Registros | Banco | Compactado (zstd 19) |
|---|---:|---:|---:|
| Base (5.571 municípios, 172 rodovias federais) | 5.743 | 1,3 MB | 0,4 MB |
| Amapá (AP), o menor | 12.176 | 4,7 MB | 1,3 MB |
| Distrito Federal (DF) | 46.307 | 11,1 MB | 2,6 MB |
| Goiás (GO) | 138.188 | 40,7 MB | 10,9 MB |
| São Paulo (SP), o maior | 976.272 | 323,7 MB | 90,2 MB |
| **Brasil inteiro** (a base e as 27 UFs) | 4.007.858 | 1.354,9 MB | 376,4 MB |

Os de cada estado estão no `catalogo.json` (`bytes_db` e `bytes`).

Como instalar, buscar, achar a rua de um ponto e o mais perto: [`docs/CONSUMO.md`](docs/CONSUMO.md).

## `catalogo.json`

```
schema             versão deste formato de catálogo (1)
format_version     versão do formato dos bancos (meta.format_version): recuse uma maior que a que você conhece
build_id           a geração: data + 8 primeiros do md5 do extrato (ex.: 2026-10-05-93a54bc6), também o nome da release
built_at           quando foi gerada (UTC)
generator_commit   commit do gerador que produziu a geração
osm                data (timestamp), md5 e endereço (url) do extrato do OpenStreetMap usado
release_url        onde baixar os arquivos desta geração
attribution        crédito obrigatório dos dados
base               a base nacional (campos abaixo; counts: municipality, road)
states             {UF: pacote}, um por estado
  name             nome do estado (só em states)
  file             nome do arquivo na release (.sqlite.zst)
  bytes            tamanho do arquivo compactado
  sha256           para conferir o download
  bytes_db         tamanho do banco descompactado (o espaço no aparelho)
  bbox             [lat mín, lon mín, lat máx, lon máx] dos municípios do estado (na base, o Brasil), arredondado
                   para fora; use para escolher o que baixar. Latitude primeiro, ao contrário do GeoJSON; graus
                   WGS84, como as coordenadas dos bancos (inteiros × 100.000, lat e lng): docs/FORMATO.md
  counts           registros por classe (place, street, road, poi), bairros (district), pedaços de traçado
                   (street_line), municípios, o total (items), as ruas com número das casas (house_number) e os
                   degraus da escada de números delas (house_number_rungs); na base, só municipality e road
```

## Atualização

O conjunto é gerado de novo a cada 29 dias, com o extrato do Brasil mais recente do OpenStreetMap, pelo GitHub
Actions (workflow [`gerar`](.github/workflows/gerar.yml)). Cada geração é uma release nova; o `catalogo.json` da raiz
sempre aponta para a mais recente. Ficam no ar as **3 gerações mais recentes**: use sempre o `release_url` do
`catalogo.json`, não um link fixo de release. Cada estado é independente: dá para atualizar um sem mexer nos outros.

Uma geração só é publicada se passar nas travas: 168 buscas de verdade (nas 27 UFs) com o resultado esperado, todos os municípios do
IBGE presentes, nenhuma queda grande de registros em relação à geração anterior, e o banco abrindo e respondendo igual
no SQLite 3.22 (o do Android 10). Como é gerado: [`gerador/README.md`](gerador/README.md).

## Reprodutibilidade

**Só a geração corrente é reproduzível**, e só enquanto as fontes ainda servem os mesmos dados; gerações antigas não
podem ser refeitas. O que fica no git: o código (`generator_commit` do `catalogo.json`), as dependências do Python
travadas com versão e hash ([`gerador/requirements.txt`](gerador/requirements.txt), gerado do `requirements.in`; as
versões são as que a geração 2026-11-10-c17dff60 instalou), as actions fixadas pelo SHA do commit e as cópias
versionadas do IBGE (malha e municípios), do SNV, da ANAC e da PRF, conferidas pelo sha256.

O que **não é arquivado**:

- o extrato do OpenStreetMap "latest" do openstreetmap.fr, trocado todo dia (em 2026-11-11 o endereço já servia
  outro extrato que o da geração 2026-11-10-c17dff60); o `catalogo.json` guarda só a data e o md5 dele;
- as fontes baixadas na hora, sem versão fixa: Overture (a versão mais nova da listagem), CNES (refeito todo dia),
  GeoNames, Wikidata (consulta SPARQL), ANP (API), CNEFE e a Base de Localidades do IBGE. A data de cada uma vai no
  `geracao.json` do artefato da geração no Actions (guardado por 14 dias), não o conteúdo.

Com as mesmas entradas, o gerador dá os mesmos pacotes, byte a byte.

## Licença

Os **pacotes** são uma base derivada do OpenStreetMap, distribuída sob a **Open Database License (ODbL) 1.0** (texto
em [`LICENSE`](LICENSE)).

- Cite "© colaboradores do OpenStreetMap".
- Se você publicar uma base derivada destes pacotes, ela precisa manter a ODbL.

Outras fontes, citadas no `attribution` do `catalogo.json` e na tabela `meta` de cada banco:

- os municípios, os limites municipais e as localidades (povoados, vilas, aldeias, quilombos): IBGE;
- os postos da Polícia Rodoviária Federal nas rodovias concedidas: ANTT, dados abertos (Creative Commons
  Atribuição);
- os hospitais, UPAs e prontos-socorros abertos 24 horas: CNES, Cadastro Nacional de Estabelecimentos de Saúde
  (Ministério da Saúde, dados abertos);
- lojas, restaurantes, oficinas e outros lugares de comércio e serviço: Overture Maps Foundation, sob a CDLA
  Permissive 2.0 (<https://cdla.dev/permissive-2-0/>);
- os quilômetros das rodovias federais ("BR-060 km 120"): Sistema Nacional de Viação do DNIT, dados abertos;
- os aeródromos públicos e privados: ANAC, dados abertos;
- nomes alternativos e pontos turísticos: GeoNames (<https://www.geonames.org/>, CC BY 4.0) e Wikidata (CC0);
- os postos de combustível em operação: ANP, cadastro de revendedores;
- o número das casas: IBGE, Cadastro Nacional de Endereços para Fins Estatísticos (CNEFE) do Censo 2022.

O **código** (pasta `gerador/`) é MIT ([`gerador/LICENSE`](gerador/LICENSE)).

## Convenções

- Nomes de arquivos e pastas de dados e documentos: português, sem acento, sem espaço (`catalogo.json`,
  `sabia-GO.sqlite.zst`, `DECISOES.md`). Exceção: os nomes que o ecossistema espera (`README.md`, `LICENSE`,
  `requirements.in`, `requirements.txt`).
- Código: nomes de variáveis, funções, classes, módulos e arquivos de código em inglês; siglas como são (`osm`,
  `ibge`, `uf`). Opções de linha de comando e identificadores de automação também.
- Formato dos dados: tabelas e colunas do banco, chaves do `catalogo.json` e valores com significado em inglês.
- Comentários, docstrings, documentação, mensagens de log e de erro, notas das releases, nomes dos passos do workflow e
  mensagens de commit: português.
- Commits só com a identidade anônima do GitHub (`…@users.noreply.github.com`).

## English

**Sabiá** builds offline place search packs for Brazil from OpenStreetMap and Brazilian open data (published, rebuilt
every 29 days): one small SQLite database per state with an FTS4 index (readable by Android's built-in SQLite), with
cities, neighbourhoods, streets, highways, points of interest and house numbers, plus simplified street lines for
reverse lookup. Coordinates are WGS84, latitude first (also in the catalogue `bbox`: `[lat_min, lon_min, lat_max,
lon_max]`). Only the current generation is reproducible: dependencies are locked with hashes and actions pinned by
commit SHA, but the inputs (the "latest" OpenStreetMap extract and the other live sources) are not archived. Data under
the ODbL 1.0 (© OpenStreetMap contributors); generator code under MIT.
