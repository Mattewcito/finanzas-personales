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
- **QA revisa TODO lo que se desarrolle, no solo lo que parezca
  arriesgado** (regla del usuario, 2026-09-17). `pytest` cubre backend:
  no ve un modal que no atrapa el foco, un tooltip que no aparece, un
  botón cortado ni un número que se muestra mal. Eso lo tiene que probar
  alguien que USE la app, y no puede ser la misma sesión que escribió el
  código -- el 2026-09-17 se entregaron un modal, tooltips y cambios de
  menú verificados solo a ojo por quien los escribió, que es revisarse a
  uno mismo, no QA.

  Por eso, **todo cambio que toque la interfaz pasa por un agente de QA
  antes de darse por terminado**, después de pushear a `dev` y
  reconstruir el contenedor (QA necesita el cambio corriendo):
  - `qa-evaluador-auto` es el default: entra con su cuenta `qa_auto`,
    recorre la app como un usuario real, crea/edita/borra datos y deja
    un informe `.md` con los bugs clasificados 🔴/🟡/🟢 más sugerencias
    de UX/producto.
  - `qa-responsive` cuando hace falta evidencia visual o cobertura por
    breakpoint: maneja su propio Chromium con Playwright y produce un
    Excel con capturas reales embebidas.

  Al agente de QA se le pasa QUÉ cambió y qué comportamiento se espera,
  no solo "probá la app" -- si no, revisa lo de siempre y no lo nuevo.
  Los 🔴 se arreglan antes de cerrar el cambio; los 🟡/🟢 van al backlog
  y se le reportan al usuario. Ningún agente de QA arregla código: solo
  detecta y documenta.
- **La suite corre sobre dos motores.** `pytest` a secas usa SQLite (el
  fallback de `db.conectar()` sin `DATABASE_URL`); producción usa
  PostgreSQL. La capa de adaptación entre ambos (`_PGConn`/
  `_adapt_sql_pg`) dejó pasar cinco bugs a `dev` con la suite en verde
  (2026-09-16/17), así que **cualquier cambio que toque `db_finanzas.py`
  se valida además contra PostgreSQL**:

  ```
  docker compose up -d postgres
  TEST_DATABASE_URL=postgresql://finanzas:finanzas_local@127.0.0.1:5433/finanzas_test pytest -q
  ```

  Cada test corre en su propio esquema, creado y borrado por
  `tests/conftest.py`. La base `finanzas_test` es OTRA base, separada de
  la real (`finanzas`): el conftest se niega a arrancar si la URL no
  termina en `_test`. Usar `127.0.0.1` y no `localhost` -- en Windows
  `localhost` resuelve primero a IPv6 y cuesta ~2 s por conexión.
  En CI esto ya corre solo (job `test-postgres` de `deploy.yml`).
- El motor de BD queda expuesto en `127.0.0.1:5433` para inspeccionarlo
  con psql/DBeaver/pgAdmin (`docker-compose.override.yml`, no
  versionado, solo en la carpeta de trabajo -- nunca en el
  `docker-compose.yml` que comparte la carpeta de despliegue, o los dos
  postgres pelearían por el mismo puerto del host).
- Agentes de proyecto en `.claude/agents/`: `product-owner`,
  `backend-engineer`, `frontend-dataviz`, `devops-engineer`,
  `test-engineer`, `qa-responsive`, `product-designer`,
  `security-devops`, `marketing-brand`, `experto-financiero` -- ver
  `PIPELINE.md` para el orden y qué produce/consume cada uno.
- **Excepción a "cuentas de prueba desechables":** `experto-financiero`
  usa una cuenta propia, real y PERSISTENTE (nunca se borra) -- es la
  única excepción deliberada a la regla de arriba, documentada en su
  propio `.md`. Sigue sin ser una cuenta de la familia real.
