# Pipeline de agentes -- de una idea a "listo para revisión"

Los agentes de `.claude/agents/` no se invocan solos entre sí: es
quien conduce la sesión (el usuario, o Claude Code orquestando en la
conversación) quien los despacha en este orden. Este documento existe
para que ese orden no dependa de la memoria de una conversación
puntual.

```
Idea del usuario
      │
      ▼
┌─────────────────┐   rechaza (justificado) ──► se le informa al usuario, fin
│  product-owner   │
└─────────────────┘
      │ aprueba -- escribe requisitos/<fecha>_<slug>.md
      ▼
┌───────────────────────────────┐
│ backend-engineer / frontend-  │  (en paralelo si el requerimiento
│ dataviz implementan           │   toca ambas capas)
└───────────────────────────────┘
      │ cada uno se autoverifica (pytest -q / navegador) antes de avisar que terminó
      ▼
┌─────────────────┐
│  test-engineer   │  pytest -v/-q en verde, cobertura del requerimiento
└─────────────────┘
      │
      ▼
   git push a `dev` -- AUTOMÁTICO, sin pedir confirmación cada vez
   (ver "Sobre el push a dev" más abajo; solo dentro de este pipeline)
      │
      ▼
┌─────────────────┐
│  qa-responsive   │  prueba funcional/responsive SOLO contra dev,
└─────────────────┘  reporte breve y claro + qa_reports/<fecha>/reporte_bugs.xlsx
      │
      ├─ encuentra bug ──► vuelve a backend-engineer/frontend-dataviz (flujo normal de fix), y se re-testea
      │
      ▼ aprueba
┌─────────────────┐
│ product-designer │  audita con severidad si dev cumple requisitos/<fecha>_<slug>.md
└─────────────────┘  en los 3 breakpoints, contra la app real (no mockups)
      │  qa_reports/<fecha>/ux_review.md
      ├─ 🔴 NO APTO / 🟡 con observaciones ──► vuelve a desarrollo, se re-testea
      │
      ▼ 🟢 APTO
   Se le avisa al usuario para su revisión final
```

## Qué produce y consume cada etapa

| Etapa | Lee | Escribe |
|---|---|---|
| `product-owner` | la idea del usuario, código/docs existentes | `requisitos/<fecha>_<slug>.md` |
| `backend-engineer` / `frontend-dataviz` | `requisitos/*.md` | código en `src/`/`routes/`/`dashboard/` |
| `test-engineer` | código nuevo/modificado | tests en `tests/` |
| `qa-responsive` | `dev` corriendo, `requisitos/*.md` (para saber qué probar) | `qa_reports/<fecha>/reporte_bugs.xlsx` |
| `product-designer` | `dev` corriendo, `requisitos/*.md`, resultado de `qa-responsive` | `qa_reports/<fecha>/ux_review.md` |

## Sobre el "dba"

Este proyecto usa SQLite de un solo archivo dentro de una app Flask
chica -- no hay un servidor de base de datos que administrar. Todo lo
de esquema, migraciones y cifrado de columnas sensibles ya es
responsabilidad explícita de `backend-engineer` (`src/db_finanzas.py`).
**No existe un agente `dba` separado en este proyecto** -- si algún
requerimiento futuro de verdad lo justificara (ej. migrar a un motor
de base de datos distinto), habría que crear uno recién en ese
momento, no antes.

## ✅ Sobre el push a `dev`/`master` -- resuelto, 2026-09-06 (regla GENERAL del proyecto, no solo de este pipeline)

**Decisión explícita del usuario** (ampliada respecto a la primera
versión de esta sección, que lo limitaba solo a este pipeline):

- **`dev`: push automático, siempre.** Cualquier cambio verificado
  (tests en verde) se sube a `dev` sin pedir confirmación cada vez --
  no hace falta que haya pasado por `product-owner` ni por este
  pipeline completo, aplica a CUALQUIER trabajo en este proyecto (un
  fix puntual, una tarea suelta, lo que sea). La idea es que el usuario
  pueda ver cualquier cambio corriendo en `dev` sin tener que pedirlo
  cada vez.
- **`master`/prod: JAMÁS, bajo ningún concepto, sin autorización
  explícita del usuario en la conversación en vivo.** Ni un push, ni
  un merge de `dev` a `master`, ni un deploy real -- esta regla no
  tiene excepción, ni siquiera para un cambio que ya pasó por todo el
  pipeline (`product-owner` → dev → `test-engineer` → `qa-responsive`
  → `product-designer`, todos 🟢). Pasar todo el pipeline dice que el
  cambio está LISTO para producción, no que ya está autorizado a
  llegar ahí -- esa autorización la da el usuario aparte, siempre.

Dentro de este pipeline específico, el push a `dev` ocurre
inmediatamente después de que `test-engineer` confirma `pytest -v`/`-q`
en verde, y ANTES de despachar a `qa-responsive` (QA necesita el
código ya corriendo en `dev` para poder probarlo ahí).

**Quién ejecuta el push:** ninguno de los agentes de desarrollo
(`backend-engineer`/`frontend-dataviz`/`devops-engineer`) lo hace --
sus instrucciones siguen diciendo explícitamente que no pushean, y eso
no cambia. Lo ejecuta siempre la sesión que está conduciendo el
trabajo (equivalente a lo que ya se hizo manualmente en este proyecto:
`git add -A && git commit -m "..." && git push origin dev`, seguido de
`docker compose up -d --build` y un chequeo de `/health` contra `dev`).

## Sobre "que no dependa de mi revisión para trabajar por sí solo"

`qa-responsive` y `product-designer` están diseñados para correr sin
esperar que el usuario revise cada bug o cada observación uno por
uno -- si `qa-responsive` encuentra un bug, el flujo normal es que
vuelve a desarrollo y se re-testea, no que se detiene a esperar al
usuario. El usuario entra recién al final, cuando `product-designer`
da 🟢 APTO (o si algo queda bloqueado y ningún agente puede decidir
por su cuenta cómo seguir, ej. `product-owner` no está seguro de si
una idea aporta valor).
