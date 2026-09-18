# Pendientes -- ideas sin evaluar todavía

Cola de ideas crudas del usuario que todavía NO pasaron por
`product-owner` (Modo 1, ver `.claude/agents/PIPELINE.md`). No son
requerimientos aprobados -- son candidatas a evaluar la próxima vez que
haya una sesión/loop dedicada a revisar backlog. Cualquier agente puede
tomar una de acá, evaluarla con `product-owner` y, si se aprueba,
seguir el pipeline normal (`backend-engineer`/`frontend-dataviz` ->
`test-engineer` -> push a `dev` -> `qa-responsive` ->
`product-designer`). Esto incluye tanto a los agentes propios del
proyecto (`.claude/agents/*.md`) como a los agentes genéricos `ecc:*`
disponibles en la sesión (ej. `ecc:code-explorer`, `ecc:planner`,
`ecc:python-reviewer`) si hace falta investigación o revisión de código
más general antes de pasarle la idea a `product-owner`.

Al tomar una idea de acá, borrarla de esta lista (o marcarla como
tomada) para no evaluarla dos veces.

---

## ~~2026-09-10 -- Botón en el frontend para disparar la lectura de correo a demanda~~ (YA EXISTE, no es un pendiente)

Corrección: esto ya está construido desde hace tiempo (commit
`db1560e`, "Automatización de correo (Fase 1)"), muy anterior a esta
sesión -- `POST /api/correo/sincronizar-ahora`
(`routes/correo.py:162-183`) + botón "Sincronizar ahora" en
`templates/configurar_correo.html:369-390`. Se deja esta nota tachada
para que quede registro de la corrección; no evaluar de nuevo.

---

## 2026-09-10 -- Lectura de correo: soportar múltiples entidades (Lulo, Nu, Nequi, BBVA, etc.), no solo Bancolombia

Hoy `leer_correo.py` está *hardcodeado* a una sola entidad: busca por
IMAP solo dos direcciones exactas de remitente de Bancolombia
(`REMITENTES_BANCOLOMBIA`, `leer_correo.py:116-119`) y cada correo se
matchea contra 7 regex hechos a medida del formato exacto de sus
alertas (`leer_correo.py:169-334` -- `_p_compra_tarjeta`, `_p_avance`,
etc.). No es "buscar por palabras clave genéricas": cada banco redacta
sus notificaciones distinto, así que sin un parser dedicado por
entidad no se puede extraer monto/fecha/comercio de forma confiable.

La idea del usuario: que la app permita **agregar entidades** (Lulo,
Nu, Nequi, BBVA, etc.) donde tiene su plata/mueve sus finanzas, y que
la lectura de correo busque en esas entidades también, no solo en
Bancolombia.

Cosas a resolver cuando se evalúe (no vinculante, para
`product-owner`/`backend-engineer`):
- Probablemente necesita: (1) una UI para que el usuario declare qué
  entidades usa, (2) por cada entidad, su(s) dirección(es) de
  remitente conocida(s) para buscar por IMAP, y (3) un parser regex
  específico por cada tipo de alerta que esa entidad mande -- calcado
  del patrón que ya existe para Bancolombia (`PARSERS` en
  `leer_correo.py`), no una búsqueda por palabras sueltas.
- Requiere tener/conseguir ejemplos reales de las alertas de cada
  banco nuevo para poder escribir sus regex (igual que se hizo para
  Bancolombia, ver los comentarios con ejemplos de cada `_p_*`).
- Evaluar si tiene sentido una arquitectura de "un módulo de parsers
  por entidad" en vez de agregar todo a `leer_correo.py` a mano,
  pensando en que esto va a seguir creciendo.

**Estado: sin evaluar por `product-owner` todavía.**

---

## ~~2026-09-10 -- Lectura de correo: ampliar la ventana de la primera corrida~~ (YA IMPLEMENTADO)

Hecho el mismo día: `calcular_dias_a_revisar()` (`leer_correo.py:389`)
ya no usa un tope fijo de 30 días para la primera corrida de una
cuenta -- ahora busca desde el 1 de enero del año en curso hasta
`ahora`. A partir de la SEGUNDA corrida (ya hay `ultima_corrida`
guardado), la ventana vuelve exactamente al criterio de siempre
(cubrir el hueco desde la última corrida, topado en
`DIAS_MAXIMO_SI_HUBO_HUECO = 60`) -- no se tocó esa parte, tal como
pidió el usuario ("lo que funciona hoy sí es funcional"). Tests
actualizados y en verde (`tests/test_leer_correo_main.py`).

Se deja esta nota tachada para que quede registro; no evaluar de
nuevo.

---

## 2026-09-10 -- Movimientos genéricos: descripción editable, categoría editable y filtros dinámicos en la tabla

Pedido del usuario, con ejemplos reales de movimientos poco
descriptivos que vienen de correo/PDF (`"Transferencia a cuenta
*35142078986"`, `"Compra en DOLLARCITY LOS MOLIN con T.Cred *2011"`,
`"Pago QR desde cuenta *5360 a llave 0040669244"`, `"Bre-B a Esteban
Garcia Zapata"`):

1. Poder editar la descripción de un movimiento (útil sobre todo para
   los genéricos, para hacerlos más "dicientes") desde la tabla de
   movimientos/vistas.
2. Poder editar la categoría asignada, también desde ahí.
3. Filtros dinámicos en la tabla de vistas y movimientos.

**Hallazgo importante al investigar esto:** los puntos 1 y 2 YA
TIENEN backend completo y probado -- `POST
/api/movimiento/<id>/editar` (`routes/dashboard.py:222-266`, ver
`requisitos/2026-09-07_editar-borrar-movimiento.md`) acepta cambiar
`descripcion` y `categoria` (entre otros campos) de CUALQUIER
movimiento propio, no solo los "genéricos". Pero **no existe ningún
botón/modal en el frontend que lo use** -- confirmado por grep, ningún
archivo de `templates/` ni `dashboard/dashboard_finanzas.html`
referencia ese endpoint. O sea: falta solo la parte de UI, no la
lógica de negocio. El punto 3 (filtros dinámicos) sí es enteramente
nuevo, no hay nada parecido hoy en la tabla.

**Estado: sin evaluar por `product-owner` todavía.**

---

## 2026-09-10 -- Presupuesto: selector de reglas de presupuesto + categorías dinámicas por balde

Dos pedidos relacionados sobre la sección de Presupuesto
(`dashboard/dashboard_finanzas.html`, modales "Configurar presupuesto"
y "Reasignar categorías a un balde"):

**a) Selector de regla al inicio del modal "Configurar presupuesto".**
Hoy solo existe la regla 50/30/20 (Necesidades/Gustos/Ahorro, ver
`requisitos/2026-09-08_presupuesto-ahorro-deudas.md`). El usuario pidió
un desplegable con varias reglas conocidas, cada una con su
descripción visible para que el usuario entienda en qué consiste antes
de elegirla:
- **Regla 80/20** ("Págate a ti mismo primero"): 20% a ahorro/inversión
  apenas se reciben los ingresos, 80% restante libre, sin categorizar
  gasto por gasto.
- **Regla 70/20/10**: 70% gastos básicos, 20% ahorro/pago de deudas,
  10% inversión/educación/donaciones.
- **Regla del 60%**: 60% a gastos fijos (necesidades); el 40% restante
  dividido en 4 partes iguales (10% c/u): jubilación, ahorro largo
  plazo, ahorro corto plazo, diversión.
- **Presupuesto Base Cero**: sin porcentajes fijos -- ingresos menos
  gastos debe dar exactamente cero, asignándole un propósito específico
  a cada peso antes de que empiece el mes.
- (La 50/30/20 ya existente debería sumarse a este mismo desplegable,
  con su propia descripción, en vez de quedar como la única opción
  implícita.)

**b) Categorías dinámicas por balde, no fijas a 3.** Desde el modal
"Reasignar categorías a un balde", poder agregar categorías nuevas. Y
más importante: la estructura de "baldes" no debería quedar fija a 3
(Necesidades/Gustos/Ahorro) para todas las reglas -- por ejemplo, Base
Cero no tiene 3 baldes predefinidos, el usuario define los que quiera.
La UI/modelo de datos de baldes tiene que soportar esa flexibilidad
según la regla elegida en (a), no asumir siempre 3 categorías fijas.

Esto es una idea grande (nueva estructura de datos para baldes
variables por regla, UI de selección con descripciones, migración de
lo que ya existe hoy con 50/30/20 fijo) -- probablemente amerite
partirse en pasos, como se hizo con
`requisitos/2026-09-08_presupuesto-ahorro-deudas.md`.

**Estado: sin evaluar por `product-owner` todavía.**
