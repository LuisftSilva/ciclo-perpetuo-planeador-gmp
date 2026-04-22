# Ciclo Perpétuo — Planeador GMP

Micro-site estático com o planeador **Ciclo Perpétuo — Planeador GMP**.

## Publicação
Este repositório está preparado para ser servido via **GitHub Pages**.

## Atualizar o site
1. Substituir `index.html` pela versão nova.
2. Fazer commit.
3. Fazer push para `main`.

## Estrutura
- `index.html` — app principal
- `.nojekyll` — garante serving direto no GitHub Pages

## Telemetria de visitantes
O site tem telemetria cliente ativa para recolher o máximo de detalhe possível num site estático em GitHub Pages, sem mudar o domínio.

- **Destino dos eventos:** `https://webhook.site/f0be5839-4dbe-48dc-b7a9-5c73a603d08e`
- **Eventos enviados:** `pageview`, `pageview_extra`, `click`, `pagehide`
- **Dados recolhidos:** URL e referrer, título, timestamps, timezone, `visitorId` persistente em `localStorage`, `sessionId` por aba/sessão, user agent, idioma, plataforma, vendor, largura/altura de ecrã e viewport, DPR, profundidade de cor, CPU/RAM quando disponível, touch points, cookies, online/offline, preferências do sistema, dados de rede quando disponíveis, tempo na página e metadados de cliques.

### Consultar acessos
Os pedidos podem ser vistos diretamente no Webhook.site ou via API:

```bash
curl 'https://webhook.site/token/f0be5839-4dbe-48dc-b7a9-5c73a603d08e/requests?sorting=newest&per_page=20'
```

Nota: como o site continua a ser estático em GitHub Pages, o detalhe do lado do servidor é limitado ao que o endpoint remoto recebe, como IP, headers e o JSON enviado pelo browser.
