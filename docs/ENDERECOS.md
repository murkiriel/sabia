# Endereço com número: o CNEFE do IBGE (medição em Goiás, 2026-10-09)

O pacote de hoje acha a rua, não o número ("Rua 9, 1200"). Para o número, a fonte é o **CNEFE do Censo 2022** do IBGE
(Cadastro Nacional de Endereços para Fins Estatísticos), baixado direto do IBGE, com o crédito; não a Overture
Addresses, que no Brasil é o mesmo CNEFE marcado como proprietário.

## A fonte

`ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/Arquivos_CNEFE/CSV/UF/`:
um zip por UF (GO 121 MB, DF 20 MB, SP 1,08 GB), um CSV (`;`, UTF-8) com o município, o logradouro (tipo, título e
nome), o número, a localidade, o CEP e `LATITUDE`/`LONGITUDE` com `NV_GEO_COORD` (1 e 2: a coordenada do próprio
endereço; 3 a 6: estimada pela face de quadra, localidade ou setor). É o retrato do Censo: não muda, baixa-se uma vez.

## Números de Goiás

| | |
|---|---|
| Endereços | 3.960.937 |
| Com coordenada do próprio endereço (nível 1 ou 2) | 3.948.856 (99,7%) |
| Com número (maior que zero) | 1.389.920 (35%) |
| Com número e coordenada própria | 1.385.136 |
| Ruas (município + nome) com número | 63.885 |
| Ruas que casam pelo nome com as do pacote | 24.913 (39%), com 68% dos endereços numerados |

Em Goiás quase dois terços dos endereços são "SN" com quadra e lote (Goiânia, Aparecida e boa parte das cidades): o
número só resolve um terço. Quadra e lote ficam para outra etapa.

## A escada de números

Guardar todo endereço seria grande e sem ganho: entre dois números da mesma rua, a posição se interpola. Por rua e lado
(par, ímpar), um **degrau** a cada N números, mais o último; o resto se interpola entre os dois degraus em volta. A
mesma "Rua 1" existe em vários bairros do mesmo município, então a escada é quebrada quando dois números seguidos ficam
a mais de 300 m: sem a quebra, o p90 do erro era de 1,5 km.

| Degrau a cada | Degraus em GO | Tamanho bruto (10 bytes cada) | Erro dos interpolados: mediana | p90 | Até 50 m |
|---|---|---|---|---|---|
| 10 números | 597.957 | ~6,0 MB | 12 m | 92 m | 82% |
| **20 números** | **498.378** | **~5,0 MB** | **12 m** | **92 m** | **82%** |
| 40 números | 429.898 | ~4,3 MB | 13 m | 103 m | 79% |

Proposta: degrau a cada 20 números, quebra a 300 m. O pacote de GO hoje tem 6,2 MB em zstd; os degraus, com números e
coordenadas em inteiros como o resto do pacote, devem somar uns 2 a 3 MB comprimidos.

## O que entrou (2026-10-09)

- **Só ruas que o mapa já tem.** A primeira geração local de GO pôs também, como registro novo, a rua do CNEFE sem
  par no pacote (55 mil): o pacote foi de 8,3 MB para 18,3 MB e a busca "br-153 anapolis" passou a trazer a
  "Avenida Br 153" do CNEFE na frente da rodovia. Sem traçado, essas ruas ajudam pouco; ficaram de fora.
- **Uma linha por rua, degraus num blob** (`house_number(street INTEGER PRIMARY KEY, rungs BLOB)`, no molde do
  `street_line`): a chave é o rowid, sem índice à parte. `WITHOUT ROWID` daria o mesmo, mas a trava de esquema do
  gerador não aceita nada além do que o SQLite 3.22 lê sem surpresa.
- **Goiás, geração local:** 27.730 ruas com número, 291.404 degraus; 99.193 pedaços casados com ruas do mapa e
  121.324 sem rua de mesmo nome por perto. Pacote de 8,3 MB para 10,2 MB comprimido (+2,0 MB); as 49 buscas de
  referência passam e o banco abre igual no SQLite 3.22.

## Formato proposto (a primeira ideia)

- Tabela `house_number(street INTEGER NOT NULL, side INTEGER NOT NULL, seg INTEGER NOT NULL, number INTEGER NOT NULL,
  lat INTEGER NOT NULL, lng INTEGER NOT NULL)`: `street` é o item da rua (o casado pelo nome no município; a rua do
  CNEFE que o pacote não tem vira item novo, `kind` `cnefe`), `side` 0 par / 1 ímpar, `seg` o pedaço da escada.
- A busca "Rua X, 123": acha a rua como hoje e, com o número, o pedaço da escada que o contém; fora de todos, a rua.
- Crédito do IBGE no `catalogo.json` e no README, como as outras fontes.
