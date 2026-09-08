# Presupuesto 50/30/20, control de ahorro y deudas (punto 11, crítica del usuario 2026-09-08)

## Veredicto
**Aprobado en principio, pendiente de implementación -- queda fuera de la
tanda de UX cerrada hoy (puntos 1-10, commit `e68db2e`) a propósito.** Es
una feature de fondo (modelo de datos nuevo, no solo CSS/JS como los
puntos 1-10), y el pedido original ("hasta donde alcancen los tokens")
prioriza cerrar bien lo pequeño y dejar esto documentado para la próxima
sesión en vez de arrancarlo a medias sin presupuesto para verificarlo con
`test-engineer`/`qa-responsive` como corresponde.

## Contexto que trae el usuario
El usuario compartió capturas de una planilla de Google Sheets que usaba
antes de este proyecto ("Planeador financiero 2026"): presupuesto mensual
por categorías agrupadas en 3 baldes (Gastos básicos / Gustos / Ahorro),
columna Presupuesto vs. Real vs. Diferencia por cada balde y por cada
línea de gasto/deuda/ahorro individual, un tablero de deudas con
Presupuesto vs. Real por deuda, y un balance diario acumulado. Su crítica
puntual a este dashboard: *"las categorías son absurdas"* (hoy son ~22
categorías de clasificación automática por texto -- comida, transporte,
suscripciones, etc. -- sin ningún presupuesto ni meta asociada) y pide
"agregar las opciones necesarias... teniendo un presupuesto, registrando
deudas..., control de ahorro etc., todo lo necesario para manejar las
finanzas sin que eso se vuelva tedioso ni engorroso... lo más completo
posible pero con el menor esfuerzo posible".

## Justificación de negocio
Hoy el dashboard es un espejo de lo que YA pasó (clasificación automática
de movimientos ya registrados) pero no ayuda a decidir CUÁNTO gastar
antes de gastarlo -- que es justamente lo que la planilla anterior sí
hacía y el usuario extraña. Sin un presupuesto de referencia, ninguna
cifra del dashboard actual ("gastaste $X en comida") le dice al usuario
si eso está bien o mal para su situación. La regla 50/30/20 (o cualquier
regla configurable) le da ese punto de comparación con el mínimo de
esfuerzo posible: 3 baldes, no 22 categorías con presupuesto individual
cada una (eso sí sería "tedioso y engorroso", lo que el usuario pide
evitar explícitamente).

---

## Alcance propuesto (a validar/priorizar en la próxima sesión)

### 11.1 Regla de presupuesto configurable (no solo 50/30/20 fijo)
- El usuario define, por perfil, 3 porcentajes de su ingreso mensual real
  (ver "Dinero que entró", ya calculado) para 3 baldes:
  **Necesidades**, **Gustos**, **Ahorro/deudas** -- 50/30/20 como *default*
  sugerido al crear el presupuesto, no un valor fijo en código (algunos
  usuarios reales lo ajustan, ej. 60/20/20).
- Cada categoría de movimiento existente (`CAT_ICONS`, ~22 hoy) se mapea a
  UNO de los 3 baldes -- mapeo simple, editable por el usuario, con un
  default razonable ya precargado (ej. `supermercado`/`servicios`/
  `salud`/`hogar` → Necesidades; `restaurantes`/`entretenimiento`/`ropa` →
  Gustos; `pago_tarjeta_credito`/ahorro explícito → Ahorro/deudas) para
  que la mayoría de usuarios no tenga que tocar nada al empezar.
- El dashboard (o una sección nueva) muestra, para el período filtrado:
  Presupuesto vs. Real vs. Diferencia por balde -- 3 filas, no 22.

### 11.2 Control de ahorro
- Registrar una o más "metas de ahorro" (nombre, monto objetivo, fecha
  opcional) -- reutilizar el patrón ya probado de `tarjetas_credito`
  (tabla propia, CRUD análogo) en vez de inventar un mecanismo distinto.
- El aporte a una meta se registra como un movimiento más (tipo
  `ahorro`, o reutilizando `categoria` dentro del balde "Ahorro/deudas")
  -- **no** un sistema paralelo de "transferencias internas" que
  complique el modelo de datos ya establecido.
- El dashboard muestra el avance (ahorrado / meta) por cada una, con el
  mismo lenguaje simple que ya se aplicó en los puntos 7-10 de la ronda
  anterior (nada de "saldo acumulado neto de flujos de ahorro").

### 11.3 Deudas más allá de tarjetas de crédito
- Hoy `tarjetas_credito` (ver `requisitos/2026-09-07_tarjetas-credito-cupo.md`)
  ya cubre el caso más común. Este punto evalúa si hace falta generalizar
  a "otras deudas" (préstamos personales, deudas informales sin tarjeta)
  con el mismo patrón (cupo/monto total, saldo, activa/archivada) -- **a
  decidir con el usuario si de verdad las tiene**, antes de construir un
  modelo genérico que nadie llegue a usar.

### 11.4 Simplificación de categorías visibles al usuario
- No se trata de borrar las ~22 categorías de clasificación automática
  (siguen siendo necesarias para el detalle/la tabla de movimientos), pero
  la vista principal de "cuánto gasté" debe poder mostrarse agrupada por
  los 3 baldes del presupuesto (11.1), no como una lista plana de 22
  barras -- eso es exactamente la queja de "categorías absurdas".

## A quién le correspondería
- **`product-owner`**: primer paso obligatorio antes de tocar código --
  revisar este documento con el usuario, decidir prioridad entre 11.1-11.4
  (probablemente 11.1 primero, es la base de todo lo demás), y si 11.3
  aplica de verdad o se descarta.
- **`backend-engineer`**: tabla(s) nueva(s) (presupuesto por balde y
  perfil, mapeo categoría→balde, metas de ahorro -- siguiendo el patrón ya
  usado por `tarjetas_credito`), endpoints CRUD, ningún dato sensible
  nuevo que cifrar (son montos y porcentajes, mismo criterio que ya se
  decidió para tarjetas).
- **`frontend-dataviz`**: nueva sección del dashboard (Presupuesto vs.
  Real por balde, metas de ahorro), reutilizando el lenguaje simple y el
  patrón "Ver detalle" ya introducido hoy (commit `e68db2e`).
- **`test-engineer`** / **`qa-responsive`** / **`product-designer`**: mismo
  pipeline completo de siempre, sin atajos -- es una feature de negocio
  con dinero real de por medio.

## Riesgo a vigilar
- **No repetir el error ya corregido del `origen` de conciliación**
  (commit `f56eec6`): cualquier campo nuevo que compare texto contra un
  literal (ej. el tipo de movimiento "ahorro") debe usar la MISMA
  constante en el punto donde se escribe y donde se lee, verificado con
  un test explícito -- no dos strings que deberían coincidir y no
  coinciden.
- **No convertir esto en 22 presupuestos individuales** -- el usuario
  pidió explícitamente lo contrario ("el menor esfuerzo posible"); si
  `product-owner`/`frontend-dataviz` derivan hacia presupuesto por
  categoría en vez de por balde, están resolviendo un problema distinto
  al que pidió el usuario.
- **Los porcentajes deben sumar 100%** (o advertir si no) -- un
  presupuesto de baldes que no cubre el 100% del ingreso real puede
  esconder gasto sin categorizar en ningún balde, el mismo tipo de "dinero
  fantasma" que el proyecto ya viene corrigiendo (deuda "sin asignar" de
  tarjetas, `origen` de conciliación).

## Pendiente inmediato
No implementar nada de esto todavía -- este documento es el punto de
partida para que, en la próxima sesión, `product-owner` lo revise con el
usuario y priorice 11.1-11.4 antes de que `backend-engineer` toque
`src/db_finanzas.py`.
