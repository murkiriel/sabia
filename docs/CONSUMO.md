# Como usar os pacotes

Para quem lê os pacotes: um programa no celular, um site, um script. O formato está em [`FORMATO.md`](FORMATO.md);
aqui, o que fazer com ele. A busca descrita abaixo está escrita, como referência, em
[`gerador/sabia/search.py`](../gerador/sabia/search.py), e é ela que as travas de cada geração usam para conferir as
buscas de verdade (`gerador/buscas.json`).

## Instalar

1. Leia o `catalogo.json` e escolha os pacotes: a **base** (todos os municípios do país) e os estados que interessam.
2. Baixe cada arquivo e confira o `sha256`.
3. Descompacte (zstd) uma vez e guarde o `.sqlite`. O cabeçalho do quadro zstd traz o tamanho descompactado, para
   conferir o espaço antes.
4. Abra só leitura e confira `SELECT value FROM meta WHERE key = 'format_version'`: **recuse uma versão maior** que a
   que o seu código conhece.

Cada estado é independente: dá para instalar, atualizar e apagar um sem mexer nos outros, e gerações diferentes
convivem (o `build_id` de cada um está em `meta`).

## Buscar

Com vários estados instalados, rode a busca em cada banco e junte os resultados pela mesma ordem. A base serve quando
o estado da cidade não está instalado (e diz, pela `uf`, qual pacote baixar).

1. **Dobrar o texto** como o gerador: minúsculas, sem acento (decomposição NFKD sem as marcas), tudo o que não é letra
   ou dígito vira espaço.
2. **Expressão dispensável no começo:** as linhas `drop_prefix` de `word_form` ("cidade de goias" → "goias").
3. **Município citado:** se a busca **termina** com o nome inteiro (dobrado) de um município da tabela
   `municipality`, ele é o município citado; vale o nome mais longo ("rua 10 aparecida de goiania" é Aparecida de
   Goiânia, não Goiânia). No meio da busca, o nome de um município é só uma palavra ("avenida anhanguera goiania":
   Anhanguera também é município).
4. **Palavras vazias:** tire "de", "da", "do", "dos", "das", "e" (a não ser que a busca seja só elas).
5. **Categoria:** a primeira palavra que está em `category` vira filtro de `kind` (os valores separados por vírgula).
   As outras palavras continuam como texto. Busque dos dois jeitos e junte: com o filtro de tipo (e sem a palavra da
   categoria no texto) e sem o filtro (com a palavra no texto: "Posto Cerrado" tem "posto" no nome). Só a categoria,
   sem mais nada ("posto"), é uma busca por perto: os registros do tipo nos 9 quadrados em volta, do mais perto.
6. **Alternativas de cada palavra** (`word_form`): a própria palavra; nas linhas `abbr`, a forma por extenso de uma
   abreviação digitada ("dr" → "doutor") e, no outro sentido, a abreviação de uma palavra digitada por extenso
   ("capitao" → "cap"), esta **só como palavra inteira** (para "setor" → "st" não casar com "styles"); as linhas
   `form` e `number`.
7. **As consultas:** uma `MATCH` por combinação de alternativas (o gerador limita a 16), cada uma só com termos
   separados por espaço, que o FTS junta com AND. **Não use `OR` nem parênteses dentro de uma `MATCH`**: a precedência
   do OR muda entre a sintaxe padrão e a estendida do FTS, e o SQLite do aparelho pode ter qualquer uma das duas.
   Junte as combinações no seu código (ou com `UNION`). Cada termo é prefixo (`avenida*`), menos o número e a letra
   solta, que valem inteiros (`10`, não `10*`, para "rua 10" não trazer "Rua 100"), **exceto na última palavra**,
   que ainda está sendo digitada.

   ```sql
   SELECT i.* FROM item_text JOIN item i ON i.id = item_text.docid WHERE item_text MATCH 'rua* 10 setor* oeste*'
   ```

8. **Ordenar**, nesta ordem de critérios:
   1. quantas palavras da busca casam com uma palavra do **nome** (com as alternativas; a palavra da categoria conta
      uma vez pelo `kind` e mais uma se estiver no nome). As palavras do município citado não contam aqui, a não ser
      que a busca seja só o nome dele;
   2. registros do município citado primeiro;
   3. com categoria, os do tipo dela primeiro;
   4. a classe: município, cidade e vila grande (`municipality`, `place=city`, `place=town`); vila e bairro
      (`place=village`, `suburb`, `neighbourhood`, `quarter`); outros lugares e ruas; rodovias; pontos de interesse;
   5. entre ruas, a via mais importante (`highway=primary` antes de `highway=residential`);
   6. as palavras do município citado no nome do registro ("goiania shopping" → "Goiânia Shopping");
   7. o mais perto do usuário, se a posição for conhecida; senão o nome mais curto.
9. **Rótulo:** nome, bairro e município, sem repetir ("Rua 10, Setor Oeste, Goiânia"). Ponto de interesse sem nome
   (posto sem nome no OpenStreetMap) mostra o tipo ("Posto de combustível").

Com essas regras, das 50 buscas de Goiás medidas antes do gerador (comparadas com um geocodificador online feito do
mesmo OpenStreetMap), o primeiro resultado é o certo em 46 (eram 37 antes das regras), pelo critério das travas; das
outras, 3 têm o certo nos 5 primeiros e uma não existe no OpenStreetMap com o nome escrito certo.

## Que rua é esta?

1. Calcule o quadrado (`cell`) do ponto e os 8 vizinhos (fórmula em [`FORMATO.md`](FORMATO.md)).
2. Leia os pedaços de `street_line` desses 9 quadrados e meça a distância do ponto até cada segmento (num plano local:
   x = lng × 111.320 × cos(lat), y = lat × 111.320, em metros).
3. O pedaço mais perto dá a rua (`street_line.item` → `item`). Mais longe que ~75 m, não há rua (o ponto está fora
   das vias com nome).

Medido em Goiás: acerta a rua de 99% dos pontos tirados do meio de trechos de rua, até 12 m para o lado.

Para o bairro de um ponto: os polígonos de `district` (regra par-ímpar), preferindo `suburb` e `admin_level=10`, depois
`quarter`, `neighbourhood` e `admin_level=9`, e o menor no mesmo nível.

## Mais perto

"Postos perto de mim": `SELECT ... FROM item WHERE kind = 'amenity=fuel' AND cell IN (<os 9 quadrados>)`, ordenado
pela distância. Para um raio maior, aumente a vizinhança de quadrados (5 × 5, 7 × 7).

## Crédito

Os pacotes são base derivada do OpenStreetMap (ODbL 1.0): mostre "© colaboradores do OpenStreetMap" onde os
resultados aparecem. O texto do crédito está em `meta.attribution`.
