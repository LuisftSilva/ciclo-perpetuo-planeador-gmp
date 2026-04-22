# Ciclo Perpétuo — Planeador GMP

Micro-site estático publicado em **GitHub Pages**.

## Estrutura principal

- `index.html` — app principal (planeador)
- `metrics/index.html` — dashboard de métricas (desencriptação no browser)
- `metrics/data/metrics.enc.json` — dataset encriptado (sem plaintext)
- `metrics/state.json` — estado não sensível para rotação/sync de tokens
- `scripts/metrics_sync.py` — sync webhook.site + rotação + encriptação
- `scripts/metrics_crypto.py` — utilitário PBKDF2 + AES-GCM
- `.github/workflows/metrics-sync.yml` — pipeline automática a cada 15 min

---

## Telemetria de visitantes (cliente)

O `index.html` envia eventos para um coletor `webhook.site` via constante:

```js
const TELEMETRY_COLLECTOR_URL = 'https://webhook.site/<uuid>'
```

A pipeline atualiza automaticamente este UUID quando roda token.

### Eventos enviados

- `pageview`
- `pageview_extra`
- `click`
- `pagehide`

Inclui metadados de sessão (visitorId/sessionId), URL/referrer, device/browser, idioma/timezone, viewport/screen e dados de clique.

---

## Dashboard protegida por password

A dashboard está em `metrics/` e:

1. faz fetch de `metrics/data/metrics.enc.json`
2. pede password ao utilizador
3. desencripta localmente no browser com **PBKDF2-SHA256 + AES-256-GCM**
4. apresenta:
   - total de eventos
   - visitantes únicos
   - sessões únicas
   - IPs únicos
   - visitas recentes
   - cliques recentes
   - top devices/plataformas
   - idiomas/timezones
   - tabela raw de eventos

> O repositório público guarda apenas dados encriptados. Não guarda password nem dataset em claro.

---

## Setup obrigatório (GitHub)

### 1) Configurar secret `METRICS_PASSWORD`

No GitHub repo:

`Settings → Secrets and variables → Actions → New repository secret`

- **Name:** `METRICS_PASSWORD`
- **Value:** password forte (esta será usada para abrir a dashboard)

### 2) Ativar workflow

Workflow: `.github/workflows/metrics-sync.yml`

- corre por `schedule` (a cada 15 minutos)
- pode ser disparado manualmente em `Actions → metrics-sync → Run workflow`

Na primeira execução, a workflow:

- cria token webhook.site se não existir
- atualiza o coletor no `index.html`
- sincroniza requests dos tokens ativos
- constrói dataset consolidado
- encripta dataset com `METRICS_PASSWORD`
- commit/push apenas de artefactos seguros (`index.html`, `metrics/state.json`, `metrics/data/metrics.enc.json`)

---

## Operação local (opcional)

```bash
pip install requests cryptography
METRICS_PASSWORD='uma-password-local' python scripts/metrics_sync.py --repo-root .
```

### Utilitário de crypto

Encriptar:

```bash
python scripts/metrics_crypto.py encrypt \
  --input plain.json \
  --output metrics/data/metrics.enc.json \
  --password-env METRICS_PASSWORD
```

Desencriptar (debug local):

```bash
python scripts/metrics_crypto.py decrypt \
  --input metrics/data/metrics.enc.json \
  --output decrypted.json \
  --password-env METRICS_PASSWORD
```

---

## Publicação do site

Como é GitHub Pages estático:

1. Commit das alterações
2. Push para `main`
3. Pages serve automaticamente
