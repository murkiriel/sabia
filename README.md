# Sabiá — busca de lugares sem internet, por estado

**Busca offline de lugares no Brasil**, a partir do OpenStreetMap: cidades, bairros, ruas, rodovias e pontos de
interesse (postos, borracharias, hospitais, pedágios…) num banco SQLite pequeno por estado, pronto para buscar no
celular sem sinal. O nome vem do trocadilho: o Sabiá **sabia** onde fica.

> **Situação (2026-10-05): em construção.** O gerador está sendo escrito; **nenhum pacote foi publicado ainda**. O
> formato abaixo é o planejado e pode mudar até a primeira geração. As decisões e as medições que levaram a ele estão
> em [`docs/DECISOES.md`](docs/DECISOES.md).

> **Aviso.** Os dados vêm do OpenStreetMap e podem estar incompletos ou errados.

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

## Atualização (planejada)

Uma geração nova a cada 29 dias, com o extrato do Brasil mais recente do OpenStreetMap, pelo GitHub Actions; cada
geração é uma release, e ficam no ar as 3 mais recentes.

## Licença

Os **pacotes** são uma base derivada do OpenStreetMap, distribuída sob a **Open Database License (ODbL) 1.0** (texto
em [`LICENSE`](LICENSE)).

- Cite "© colaboradores do OpenStreetMap".
- Se você publicar uma base derivada destes pacotes, ela precisa manter a ODbL.

Os municípios e os limites municipais vêm do IBGE. O **código** (pasta `gerador/`) é MIT
([`gerador/LICENSE`](gerador/LICENSE)).

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
