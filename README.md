# mgdn-precos

Monitor **pessoal** de preços do Nintendo Switch 2 e de alguns jogos e acessórios, com alertas no
[ntfy](https://ntfy.sh). Roda na [mgdn-platform](https://github.com/MarcosDaNight/mgdn-platform), só pela
tailnet. Uso próprio, volume baixo: poucas requisições por hora.

## Regras do projeto

- **Termos de uso vencem `robots.txt`.** Só entra loja cujos termos não proíbem coleta automatizada.
  Ficam **de fora**: Fast Shop (cláusula 6.1, c, proíbe robôs), Amazon, Magalu e Nintendo Store BR.
- **User-Agent identificável, sempre** (`mgdn-precos/0.1 ...`). Nunca de navegador, e nunca contornar
  bloqueio ou captcha: se uma loja responder 403/429, ela é **desativada** e eu recebo um aviso
  (`python -m precos enable <loja>` reativa).
- `robots.txt` é lido e respeitado, com 5 s entre requisições ao mesmo host e retry só para falha de
  rede e 5xx.
- **Mercado Livre** só pela API oficial, com token. Nada de HTML.

## O que entra no histórico

Só oferta **nova**, **vendida e entregue pela própria loja** (marketplace de terceiros, usado,
recondicionado e importado são recusados), com o título certo (palavras obrigatórias e proibidas por
produto, para não confundir Switch 1 com Switch 2). Jogos só em **mídia física**: digital, código,
pacote de melhoria e Game-Key Card são recusados. O que for recusado fica gravado com o motivo.

## Alertas

Avisa quando: preço ≤ meta, **ou** novo mínimo histórico, **ou** queda ≥ 8% sobre a mediana de 14 dias.
Não repete produto+loja em 24 h, salvo se o preço cair de novo. A mensagem traz Pix, parcelado,
loja, meta, mínimo histórico e o veredito (`COMPRAR`/`ESPERAR`). Se o parcelado sem juros custar até 5%
a mais que o Pix, recomenda parcelar; senão, Pix. Resumo diário às 09:00 (America/Recife). Coleta a cada
6 h, e de hora em hora entre 20/11 e 01/12.

## Uso

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                      # testes (HTML real salvo em tests/fixtures)
.venv/bin/python -m precos check-config         # valida o config.yaml
.venv/bin/python -m precos --dry-run once       # uma rodada, sem enviar ao ntfy
NTFY_URL=https://ntfy.sh/<topico-secreto> .venv/bin/python -m precos run   # laço contínuo
```

| Variável | Para quê |
|---|---|
| `NTFY_URL` | URL **completa** do tópico secreto (vem de um segredo cifrado, nunca do repositório) |
| `PRECOS_CONFIG` | caminho do `config.yaml` (padrão: `config.yaml`) |
| `PRECOS_DB` | arquivo SQLite (padrão: `data/precos.sqlite`) |

`config.yaml` guarda metas, URLs fixas de produto e a agenda. As metas medem contra o **preço de rua**,
não o sugerido.

## Estado

- [x] Núcleo, filtros, alertas, resumo, agenda e coletor da **KaBuM**
- [ ] Mercado Livre (API oficial, falta o token)
- [ ] Pichau (depende dos termos de uso)
- [ ] Imagem, CI e deploy na plataforma
- [ ] Depois da Black Friday: gráficos e métricas

## Licença

[MIT](LICENSE).
