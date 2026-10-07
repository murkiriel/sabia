# Sabiá — busca de lugares sem internet, por estado

**Busca offline de lugares no Brasil**, a partir do OpenStreetMap: cidades, bairros, ruas, rodovias e pontos de
interesse (postos, borracharias, hospitais, pedágios…) num banco SQLite pequeno por estado, pronto para buscar no
celular sem sinal. O nome vem do trocadilho: o Sabiá **sabia** onde fica.

> **Situação (2026-10-05): em construção.** O gerador está sendo escrito; **nenhum pacote foi publicado ainda**. O
> formato abaixo é o planejado e pode mudar até a primeira geração. As decisões e as medições que levaram a ele estão
> em [`docs/DECISOES.md`](docs/DECISOES.md).

> **Aviso.** Os dados vêm do OpenStreetMap e podem estar incompletos ou errados.

## Baixar por estado

<!-- downloads:start -->
Geração **2026-10-06-93a54bc6**: OpenStreetMap de 2026-10-05, formato 1. Baixe a base e os estados que quiser; confira o sha256 pelo [`catalogo.json`](catalogo.json).

| Pacote | Arquivo | Tamanho |
|---|---|---:|
| **Base** (os municípios do Brasil e as rodovias federais) | [sabia-base.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-base.sqlite.zst) | 0,3 MB |
| Acre (AC) | [sabia-AC.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-AC.sqlite.zst) | 0,8 MB |
| Alagoas (AL) | [sabia-AL.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-AL.sqlite.zst) | 1,8 MB |
| Amapá (AP) | [sabia-AP.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-AP.sqlite.zst) | 0,7 MB |
| Amazonas (AM) | [sabia-AM.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-AM.sqlite.zst) | 2,9 MB |
| Bahia (BA) | [sabia-BA.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-BA.sqlite.zst) | 12,1 MB |
| Ceará (CE) | [sabia-CE.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-CE.sqlite.zst) | 5,3 MB |
| Distrito Federal (DF) | [sabia-DF.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-DF.sqlite.zst) | 1,5 MB |
| Espírito Santo (ES) | [sabia-ES.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-ES.sqlite.zst) | 4,6 MB |
| Goiás (GO) | [sabia-GO.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-GO.sqlite.zst) | 6,2 MB |
| Maranhão (MA) | [sabia-MA.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-MA.sqlite.zst) | 3,9 MB |
| Mato Grosso (MT) | [sabia-MT.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-MT.sqlite.zst) | 3,8 MB |
| Mato Grosso do Sul (MS) | [sabia-MS.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-MS.sqlite.zst) | 3,3 MB |
| Minas Gerais (MG) | [sabia-MG.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-MG.sqlite.zst) | 22,3 MB |
| Pará (PA) | [sabia-PA.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-PA.sqlite.zst) | 4,4 MB |
| Paraíba (PB) | [sabia-PB.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-PB.sqlite.zst) | 3,6 MB |
| Paraná (PR) | [sabia-PR.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-PR.sqlite.zst) | 9,8 MB |
| Pernambuco (PE) | [sabia-PE.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-PE.sqlite.zst) | 6,1 MB |
| Piauí (PI) | [sabia-PI.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-PI.sqlite.zst) | 3,1 MB |
| Rio Grande do Norte (RN) | [sabia-RN.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-RN.sqlite.zst) | 2,9 MB |
| Rio Grande do Sul (RS) | [sabia-RS.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-RS.sqlite.zst) | 14,4 MB |
| Rio de Janeiro (RJ) | [sabia-RJ.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-RJ.sqlite.zst) | 9,8 MB |
| Rondônia (RO) | [sabia-RO.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-RO.sqlite.zst) | 1,5 MB |
| Roraima (RR) | [sabia-RR.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-RR.sqlite.zst) | 0,8 MB |
| Santa Catarina (SC) | [sabia-SC.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-SC.sqlite.zst) | 10,6 MB |
| São Paulo (SP) | [sabia-SP.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-SP.sqlite.zst) | 37,8 MB |
| Sergipe (SE) | [sabia-SE.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-SE.sqlite.zst) | 2,0 MB |
| Tocantins (TO) | [sabia-TO.sqlite.zst](https://github.com/Murkiriel/sabia/releases/download/2026-10-06-93a54bc6/sabia-TO.sqlite.zst) | 1,6 MB |
<!-- downloads:end -->

## O que resolve

1. **Buscar sem internet:** "Rua 10, Setor Oeste", "posto ipiranga anápolis", "br-153 anápolis".
2. **Dizer "que rua é esta?"** a partir de uma coordenada (o traçado simplificado de cada rua vai no pacote).
3. **Achar o mais perto** por categoria: "posto", "borracharia", "hospital".

## O pacote

```
sabia-base.sqlite.zst    os 5.570 municípios (nome, UF, ponto da sede, código do IBGE) e as rodovias federais
sabia-<UF>.sqlite.zst    o estado: registros, índice de busca, traçados das ruas, bairros, tabelas de busca
catalogo.json            o índice: tamanho, sha256, retângulo e contagens de cada pacote, e a versão do formato
```

Cada pacote é um banco **SQLite com índice FTS4**, que o SQLite do Android (desde o 3.22) lê sem biblioteca a mais,
compactado em **zstd** e descompactado uma vez, na instalação. Um estado não depende do vizinho: cada um pode ser
instalado e atualizado sozinho. Tabelas, colunas e codificações: [`docs/FORMATO.md`](docs/FORMATO.md).

Tamanhos medidos (extrato de 2026-09-29): Goiás 23,8 MB (6,2 MB compactado), DF 7,4 MB (1,5 MB), a base 1,1 MB
(0,3 MB).

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
                   para fora; use para escolher o que baixar
  counts           registros por classe (place, street, road, poi), bairros (district), pedaços de traçado
                   (street_line), municípios e o total (items)
```

## Atualização

O conjunto é gerado de novo a cada 29 dias, com o extrato do Brasil mais recente do OpenStreetMap, pelo GitHub
Actions (workflow [`gerar`](.github/workflows/gerar.yml)). Cada geração é uma release nova; o `catalogo.json` da raiz
sempre aponta para a mais recente. Ficam no ar as **3 gerações mais recentes**: use sempre o `release_url` do
`catalogo.json`, não um link fixo de release. Cada estado é independente: dá para atualizar um sem mexer nos outros.

Uma geração só é publicada se passar nas travas: 69 buscas de verdade com o resultado esperado, todos os municípios do
IBGE presentes, nenhuma queda grande de registros em relação à geração anterior, e o banco abrindo e respondendo igual
no SQLite 3.22 (o do Android 10). Como é gerado: [`gerador/README.md`](gerador/README.md).

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
- os aeródromos públicos e privados: ANAC, dados abertos.

O **código** (pasta `gerador/`) é MIT ([`gerador/LICENSE`](gerador/LICENSE)).

## Convenções

- Nomes de arquivos e pastas de dados e documentos: português, sem acento, sem espaço (`catalogo.json`,
  `sabia-GO.sqlite.zst`, `DECISOES.md`). Exceção: os nomes que o ecossistema espera (`README.md`, `LICENSE`,
  `requirements.txt`).
- Código: nomes de variáveis, funções, classes, módulos e arquivos de código em inglês; siglas como são (`osm`,
  `ibge`, `uf`). Opções de linha de comando e identificadores de automação também.
- Formato dos dados: tabelas e colunas do banco, chaves do `catalogo.json` e valores com significado em inglês.
- Comentários, docstrings, documentação, mensagens de log e de erro, notas das releases, nomes dos passos do workflow e
  mensagens de commit: português.
- Commits só com a identidade anônima do GitHub (`…@users.noreply.github.com`).

## English

**Sabiá** (work in progress, nothing published yet) builds offline place search packs for Brazil from OpenStreetMap:
one small SQLite database per state with an FTS4 index (readable by Android's built-in SQLite), with cities,
neighbourhoods, streets, highways and points of interest, plus simplified street lines for reverse lookup. Data under
the ODbL 1.0 (© OpenStreetMap contributors); generator code under MIT.
