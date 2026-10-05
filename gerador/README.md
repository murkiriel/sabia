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

Os testes também rodam no GitHub Actions a cada push e pull request (`.github/workflows/testes.yml`), com as
dependências do `requirements.txt` e sem dados baixados.

## Convenções

Ver a seção "Convenções" do README da raiz: código, módulos, opções de linha de comando e formato dos dados em
inglês; nomes de arquivos de dados, comentários, documentação, logs e commits em português.

## Licença

Código: MIT (`LICENSE` desta pasta). Os pacotes gerados são base derivada do OpenStreetMap, sob a ODbL 1.0 (ver o
README da raiz).
