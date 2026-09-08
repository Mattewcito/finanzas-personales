# Finanzas personales -- instrucciones de proyecto

App de finanzas personales: Flask + SQLite + Docker, multiusuario.
Dos checkouts/entornos separados que comparten solo `data/finanzas.db`:
- `dev`: este repo (`C:\Finanzas personales`), rama `dev`, contenedor
  `finanzas-app-dev`, puerto **5001**.
- `prod`: `C:\finanzas-deploy`, rama `master`, puerto **5002**.

## Regla de git push (vigente desde 2026-09-06)

- **`dev`: push automático, siempre.** Cualquier cambio que quede
  verificado (suite de `pytest` en verde) se sube a `dev` sin pedir
  confirmación cada vez -- no hace falta preguntar "¿lo subo?", el
  usuario quiere poder ver cualquier cambio corriendo ahí.
- **`master`/prod: JAMÁS sin autorización explícita del usuario en la
  conversación en vivo.** Ni push, ni merge de `dev` a `master`, ni
  deploy real -- sin excepción, aunque el cambio ya esté completamente
  verificado. Un push a `master` dispara el deploy automático real vía
  GitHub Actions (`.github/workflows/deploy.yml`) -- por eso la barrera
  ahí es total.
- Después de pushear a `dev`, reconstruir el contenedor
  (`docker compose up -d --build`) y confirmar `/health` (`200`) antes
  de dar el cambio por terminado.
- Ver `.claude/agents/PIPELINE.md` para el detalle completo y el
  pipeline de agentes (`product-owner` → `backend-engineer`/
  `frontend-dataviz` → `test-engineer` → push a `dev` → `qa-responsive`
  → `product-designer` → usuario) que usa esta regla.

## Otras reglas ya establecidas

- Nunca tocar `data/finanzas.db`/`data/cifrado.key` reales, ni cuentas
  de usuarios reales, desde ningún agente o verificación -- usar
  siempre cuentas de prueba desechables (`docker exec` +
  `db.crear_usuario(...)`, se borran al terminar).
- Solo herramientas open-source y gratuitas (ej. Playwright para QA en
  vez de un servicio pago, `ruff`/`bandit` en vez de SonarQube).
- `pytest -q`/`-v` tiene que estar en verde antes de dar cualquier
  cambio de backend por terminado.
- Agentes de proyecto en `.claude/agents/`: `product-owner`,
  `backend-engineer`, `frontend-dataviz`, `devops-engineer`,
  `test-engineer`, `qa-responsive`, `product-designer`,
  `security-devops`, `marketing-brand` -- ver `PIPELINE.md` para el
  orden y qué produce/consume cada uno.
