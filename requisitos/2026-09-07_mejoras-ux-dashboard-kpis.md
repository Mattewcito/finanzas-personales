# Mejoras UX del panel de KPIs del Dashboard (6 críticas del usuario)

## Veredicto
Aprobado con ajustes -- el usuario ya aprobó los 6 cambios en base al
informe de `product-designer`
(`qa_reports/2026-09-07/ux_review_criticas_usuario.md`); no vuelvo a
evaluar si aportan valor. Mi trabajo acá es cerrar los huecos que ese
informe deja abiertos antes de que un ingeniero tenga que adivinar:

- **Punto 1 (filtros) tenía una premisa incorrecta que corrijo:** el
  informe habla de "el selector de rango Desde/hasta" como si fuera un
  input interactivo que hay que colapsar dentro de "Personalizado".
  Leyendo el código (`dashboard_finanzas.html` ~L1017-1068,
  `rangoTotalBadge`), **no es un input** -- es un badge de solo lectura
  que muestra el rango de fechas resultante del año/mes ya elegido. No
  hay ningún date-range picker real que preservar; lo que sí hay son
  año/mes (los únicos filtros que de verdad filtran datos).
- **Hallazgo más grave, que el informe no menciona porque no estaba en
  su alcance de auditoría visual:** los botones **Trimestral / Semestral
  / Anual son decorativos, no filtran nada.** Está documentado en el
  propio código, `dashboard_finanzas.html` L530-531: *"Vista previa
  visual únicamente -- todavía sin lógica de agrupación (los botones no
  hacen nada aún, es solo para ver cómo quedan)."* Unificar 4 mecanismos
  de filtro en "un solo control coherente" sin resolver esto primero
  produciría algo **peor** que la dispersión actual: un control de
  aspecto sólido y confiable donde 3 de 4 opciones no hacen nada -- en
  una app financiera, un control que aparenta funcionar y no funciona es
  más grave que uno disperso pero honesto. Por eso agrego, como parte
  de este mismo requerimiento (sigue siendo 100% frontend, ver más
  abajo), la definición concreta de qué debe pasar al clickear cada
  botón.
- Todo lo demás (contraste, jerarquía, gráfico compacto, íconos, ocultar
  moneda única) se aprueba tal como está recomendado en el informe, con
  los casos borde específicos que agrego yo por sub-sección.

## Justificación de negocio
Ya evaluada y aprobada por el usuario; en resumen: el panel de KPIs es
lo primero que ve cualquier usuario al entrar, y hoy no comunica con
claridad cuál es el dato que más le importa (cuánta plata tiene
disponible), el texto que aclara qué mide cada número es ilegible por
contraste, y hay controles/íconos que transmiten desprolijidad (ícono
"❔", filtros dispersos en 3 alturas distintas) en un producto que
maneja datos financieros reales -- eso es exactamente el tipo de fricción
que compromete el objetivo de "control y claridad real sobre el dinero"
del producto.

---

## 1. Unificar los filtros de período

### Qué debe poder hacer el usuario
Ver y elegir el período del dashboard desde un único bloque de
controles, en la misma posición y con el mismo orden interno en los 3
breakpoints (375/768/1920px), con estas 4 opciones:
`[ Trimestral | Semestral | Anual | Personalizado ]`.

- **Trimestral / Semestral / Anual dejan de ser decorativos:** deben
  filtrar de verdad los mismos datos (`DATA_COMPLETA`) que hoy filtran
  año/mes, reutilizando el mismo pipeline de `aplicarFiltroPeriodo()` /
  `renderDashboard()` que ya existe -- no una segunda ruta de cálculo
  paralela.
- **Definiciones concretas** (no existían antes, las fijo yo para que
  nadie improvise una durante la implementación):
  - **Trimestral:** mes calendario en curso + los 2 meses calendario
    anteriores (3 meses corridos hasta hoy).
  - **Semestral:** mes calendario en curso + los 5 meses anteriores (6
    meses corridos hasta hoy).
  - **Anual:** año calendario en curso completo (enero → hoy), mismo
    criterio de corte en "hoy" que ya usa el cálculo del badge de rango
    (`dashboard_finanzas.html` ~L1021, "si el período incluye hoy, se
    corta en la fecha actual").
  - **Personalizado:** despliega inline los selectores de año/mes que
    ya existen hoy (`filtroAnio`/`filtroMes`, reutilizados tal cual, no
    reconstruidos) -- **se conservan como selects, no se eliminan**,
    porque hoy permiten una combinación útil que un simple rango
    Desde/Hasta no cubre (ej. "todos los años, solo diciembre" para
    comparar un mismo mes entre años). Al elegir "Personalizado" sin
    tocar nada, el valor por defecto es "Todos los años" + "Todos los
    meses" (todo el histórico), igual que el comportamiento actual al
    cargar la página.
- El badge de rango de fechas (`rangoTotalBadge`, solo lectura) se
  mantiene siempre visible pegado al control unificado, en las 4
  opciones (incluida Personalizado) -- es la única confirmación
  inequívoca de qué fechas exactas está mirando el usuario, y no debe
  perderse al reorganizar.
- Mismo control, misma posición, mismo orden interno en los 3
  breakpoints -- elimina la inconsistencia medida por `product-designer`
  (desktop: rango primero, período al final; mobile: al revés).

### Criterios de aceptación
- [ ] Existe un único bloque de filtro de período, visualmente
      agrupado, en la misma posición relativa al header en los 3
      breakpoints (375/768/1920px).
- [ ] Clickear "Trimestral"/"Semestral"/"Anual" cambia de verdad los
      números de TODO el dashboard (KPIs, gráficos, tabla), con las
      definiciones de rango de fechas especificadas arriba -- verificable
      comparando contra el resultado de fijar manualmente año/mes
      equivalentes.
- [ ] "Personalizado" revela los selectores de año/mes ya existentes
      (mismos `<select>`, mismas opciones) y oculta el resto del tiempo.
- [ ] El badge de rango de fechas (Desde/hasta) es visible sin importar
      qué opción esté activa, y su valor coincide exactamente con el
      rango real aplicado (ej. "Trimestral" hoy 2026-09-07 muestra
      "Desde 01/07/2026 hasta 07/09/2026", no un texto genérico).
- [ ] El orden de los 4 elementos del bloque (título del control,
      botones, selects condicionales, badge) es idéntico en los 3
      breakpoints -- ninguno cambia de posición relativa a otro.
- [ ] En mobile (375px), el bloque de filtros completo ocupa menos
      espacio vertical que hoy (hoy: ~460px de 812px, 57% del viewport) --
      el objetivo explícito es que el Balance de caja real (punto 3)
      entre más cerca del primer viewport, no que los filtros sigan
      compitiendo por ese mismo espacio.

### Casos borde a cubrir
- **Estado vacío:** si "Trimestral"/"Semestral"/"Anual" no tiene ningún
  movimiento en ese rango (cuenta nueva, o período sin actividad), el
  dashboard debe mostrar el mismo patrón de estado vacío que ya usa hoy
  cuando año/mes filtran a cero resultados -- nunca `NaN`, `Infinity` ni
  un gráfico roto por división por cero (bug real recurrente de este
  proyecto).
- **Cambiar de preset a "Personalizado" y volver:** si el usuario elige
  "Personalizado", ajusta año/mes a algo específico, y después vuelve a
  clickear "Anual", el control debe recalcular con la definición fija
  de "Anual" (no quedarse pegado al año que había elegido a mano en
  Personalizado).
- **Aislamiento entre usuarios:** no aplica cambio de riesgo -- el
  filtro sigue operando sobre `DATA_COMPLETA`, que ya llega al frontend
  filtrada por `viendo_id()` desde el backend (sin cambios en esa capa).

---

## 2. Subir el contraste del texto secundario (`--text-faint`)

### Qué debe poder hacer el usuario
Leer cómodamente, sin esfuerzo, todo texto que hoy usa
`--text-faint` (`#5b6379`): el `.sub` de cada tarjeta KPI (ej. "2
movimientos · excluye avances de tarjeta de crédito"), el `.aviso`
("Generado por reglas... no es asesoría financiera profesional"), el
`.last-updated`, y los `<th>` de la tabla de movimientos.

### Criterios de aceptación
- [ ] El nuevo valor de `--text-faint` mide **contraste ≥ 4.5:1**
      (WCAG AA, texto normal) contra **ambos** fondos donde se usa hoy:
      `rgb(19,25,40)` (fondo de tarjeta, usado en `.sub`) y
      `rgb(13,17,27)` (fondo de página, usado en `.aviso`,
      `.last-updated`, `<th>`) -- un solo valor de variable debe cumplir
      en los dos casos, medido con la misma metodología que usó
      `product-designer` (`getComputedStyle` + cálculo de contraste
      real), no "se ve más claro a ojo". La auditoría sugiere
      `#949cb2` (~5.8:1 medido) como punto de partida, pero quien
      implemente valida el número final, no lo da por sentado.
- [ ] El cambio se hace en la variable CSS `--text-faint` una sola vez
      (no se pisan los 4 usos por separado con colores distintos) --
      así los 4 lugares quedan consistentes entre sí, como ya lo están
      hoy.
- [ ] El texto secundario sigue siendo visualmente distinguible del
      texto principal (`.value`, `.label`, texto en `rgb(238,241,248)`)
      -- no debe quedar con brillo tan parecido que se pierda la
      jerarquía tipográfica, solo debe dejar de fallar el mínimo de
      legibilidad.

### Casos borde a cubrir
- **No es un campo de dato sensible ni de dinero real** -- es css puro,
  sin riesgo de cifrado ni de interpretación financiera directa. El
  único riesgo es que el texto que aclara "qué NO incluye" un número
  (ej. "no incluye deuda de tarjeta de crédito") sea leíble -- eso es
  justamente lo que este cambio arregla, no algo que deba vigilarse
  aparte.
- **No tocar los usos de otras variables** de gris (si existiera algún
  otro tono de texto tenue con nombre distinto no incluido en el
  listado de arriba) -- alcance limitado a `--text-faint`.

---

## 3. Rediseñar la jerarquía de las tarjetas KPI

### Qué debe poder hacer el usuario
Identificar de un vistazo, sin leer las 8 tarjetas por igual, cuál es
el dato más importante del dashboard: cuánta plata tiene disponible
("Balance de caja real"). Layout propuesto por `product-designer`
(referencia, la implementación exacta de grid queda en manos de
`frontend-dataviz`):

- **"Balance de caja real"**: tarjeta destacada, ~2x el tamaño de las
  demás (ancho completo de la grilla o doble alto/ancho), primera
  posición, fondo/borde distintivo según signo (igual criterio de color
  que ya existe: verde si ≥0, rojo/alerta si <0).
- **3 tarjetas de apoyo, mismo tamaño entre sí, más chicas que el
  balance:** "Ingresos reales", "Gasto real (caja)", y **"Deuda actual
  estimada"** -- esta última hoy solo vive en la sección "Tarjetas de
  crédito y deuda" (`kpiGridDeuda`); acá se **duplica su valor** (mismo
  cálculo, mismo dato, no una segunda función) en la grilla superior
  para dar contexto inmediato al balance, sin quitarla de su sección
  original.
- **Fila secundaria, texto compacto, menor protagonismo:**
  "Transacciones totales", "Categoría con mayor gasto", "Promedio
  mensual de gasto real", "Entidad más utilizada". "Distribución por
  moneda" **no baja de prioridad, se oculta** cuando aplica (ver punto
  6) -- son mecanismos distintos, no confundirlos.

### Criterios de aceptación
- [ ] "Balance de caja real" mide, medido con `getBoundingClientRect()`
      igual que hizo `product-designer`, un área visiblemente mayor
      (≥1.8x) que "Ingresos reales"/"Gasto real (caja)"/"Deuda actual
      estimada", en los 3 breakpoints.
- [ ] "Deuda actual estimada" aparece en la grilla superior (nueva) Y
      sigue apareciendo en "Tarjetas de crédito y deuda" (sin cambios)
      -- ambos valores provienen de la misma variable/cálculo
      (`deudaActual`), nunca de dos cálculos independientes que puedan
      desincronizarse.
- [ ] "Transacciones totales", "Categoría con mayor gasto", "Promedio
      mensual de gasto real" y "Entidad más utilizada" siguen mostrando
      exactamente los mismos datos que hoy, solo con menor tamaño/peso
      visual -- ningún dato se pierde, solo se reordena la prominencia.
- [ ] El balance destacado en rojo (saldo negativo, `accent-red`,
      ícono ⚠️) recibe el mismo tratamiento de tamaño 2x que en verde --
      la jerarquía visual no depende del signo del número.
- [ ] En mobile (375px) y tablet (768px), la tarjeta destacada ocupa el
      ancho completo disponible de la grilla en ese breakpoint (nunca
      la mitad, aunque el resto de tarjetas sigan en 2 columnas).

### Casos borde a cubrir
- **No reintroducir el bug de overflow horizontal recién resuelto**
  (commits `6fc31ae`/`b65d23a`, "overflow horizontal en mobile/tablet
  cortaba cifras financieras"): al agrandar la fuente del valor del
  balance (hoy 22px) dentro de un contenedor con `overflow: hidden`
  (`.kpi`), verificar explícitamente en 375px con un balance negativo
  de muchos dígitos (ej. `-$12.345.678`) que el número completo se ve,
  sin cortarse ni desbordar la tarjeta -- usar `font-size` responsive
  (media query), no un tamaño absoluto fijo igual en los 3 breakpoints.
- **Consistencia con `vistas_ocultas`:** si un admin tiene oculta la
  sub-vista que contiene "Tarjetas de crédito y deuda" para un usuario
  (`VISTAS_DISPONIBLES`), la tarjeta duplicada de "Deuda actual
  estimada" en la grilla superior debe seguir el mismo criterio de
  visibilidad que ya aplica hoy a esa sub-vista completa (no queda
  huérfana mostrando un dato que el resto de esa sección tiene oculto).
- **Aislamiento entre usuarios:** no aplica cambio -- sigue operando
  sobre los mismos datos ya filtrados aguas arriba, sin tocar ninguna
  consulta.

---

## 4. Gráfico compacto arriba del pliegue

### Qué debe poder hacer el usuario
Ver una versión compacta del gráfico "Ingresos vs. gastos" (el mismo
que ya existe en "Análisis visual", mismas cifras, mismo cálculo) sin
necesidad de scrollear, en la zona de KPIs superior.

### Criterios de aceptación
- [ ] El gráfico compacto es visible dentro del primer viewport (sin
      scroll) en los 3 breakpoints medidos (375/768/1920px) -- criterio
      duro, verificable con la misma instrumentación Playwright que usó
      `product-designer` (posición Y del elemento < altura del
      viewport).
- [ ] Los datos del gráfico compacto son idénticos a los del gráfico
      "Ingresos vs. gastos" completo de "Análisis visual" para el mismo
      período filtrado -- una sola fuente de cálculo, reutilizada, no
      una segunda serie de datos independiente.
- [ ] El gráfico completo original en "Análisis visual" se mantiene sin
      cambios (no se elimina ni se reemplaza, ambos coexisten).
- [ ] El espacio para este gráfico sale de reorganizar/achicar
      tarjetas existentes (puntos 3 y 6), no de agregar altura extra a
      la página -- en mobile, el orden de la zona superior debe quedar:
      filtros (compactos, punto 1) → Balance destacado → tarjetas de
      apoyo → gráfico compacto → fila secundaria.

### Casos borde a cubrir
- **Estado vacío:** si el período filtrado no tiene datos (ver punto
  1), el gráfico compacto debe mostrar el mismo estado vacío que ya usa
  el gráfico completo -- no un gráfico compacto roto o con ejes vacíos
  sin explicación.
- **No empeorar el problema que resuelve:** si el gráfico compacto
  agrega tanto alto en mobile que termina empujando el Balance de caja
  real (punto 3) fuera del primer viewport, no cumple su propósito --
  priorizar que el Balance siga siendo lo primero visible, el gráfico
  compacto va después.

---

## 5. Agrandar íconos y corregir el ícono roto de "Otros"

### Qué debe poder hacer el usuario
Reconocer el concepto de cada tarjeta KPI más rápido gracias a un
ícono más grande y con color distintivo, y no interpretar por error que
la categoría "Otros" es un ícono que no cargó.

### Criterios de aceptación
- [ ] `.kpi .icon` sube de `font-size: 20px` a un tamaño en el rango
      28-32px, envuelto en un fondo circular de color (reutilizando las
      clases `accent-green`/`accent-red`/`accent-purple` ya existentes
      para las tarjetas que ya las tienen; definir un color neutro
      consistente para las que no tienen accent hoy).
- [ ] `CAT_ICONS.otros` cambia de `'❔'` a `'📦'` -- el mismo símbolo
      que ya usa `catIcon()` como fallback general (`dashboard_finanzas.html`
      L855, `CAT_ICONS[c] || '📦'`) para categorías sin mapeo. Se
      reutiliza el mismo ícono a propósito: "Otros" y "categoría sin
      mapear" comunican la misma idea ("no clasificado específicamente"),
      usar el mismo símbolo es consistente, no hace falta un tercer
      ícono nuevo.
- [ ] Ningún otro ícono del mapa `CAT_ICONS` cambia (💼🍔🚌🛒 etc. ya son
      semánticamente correctos según la auditoría).

### Casos borde a cubrir
- **Fila secundaria del punto 3:** las tarjetas que bajan a fila
  secundaria (más chicas, texto compacto) pueden no tener espacio para
  un ícono de 28-32px con badge circular -- si no entra, usar el mismo
  ícono más chico (tamaño actual ~20px) solo en esa fila, no forzar el
  tamaño grande en un contenedor que no lo soporta y generar overflow.
- **No es dato sensible ni cifrado** -- cambio puramente visual/de
  mapeo estático en JS, sin implicación de datos de usuario.

---

## 6. Ocultar "Distribución por moneda" cuando solo hay una moneda activa

### Qué debe poder hacer el usuario
No ver una tarjeta KPI ni un gráfico de dona que solo dicen "100% en
una sola moneda" cuando, en el período que está mirando, todos sus
movimientos están en la misma moneda -- ese dato no aporta nada y le
hace pensar que falta información.

### Criterios de aceptación
- [ ] La tarjeta KPI "Distribución por moneda" (grilla superior) se
      oculta cuando la cantidad de monedas distintas en `DATA` (el
      conjunto ya filtrado por el período activo, no `DATA_COMPLETA`)
      es `<= 1`.
- [ ] El gráfico de dona "Distribución por moneda" (`chartMoneda`,
      dentro de "Análisis visual") se oculta con la misma condición,
      sobre el mismo `DATA` filtrado -- ambos elementos comparten la
      condición, nunca uno oculto y el otro visible al mismo tiempo.
- [ ] La condición se recalcula en cada `renderDashboard()` (cada vez
      que cambia el filtro de período, incluidos los nuevos presets del
      punto 1) -- **no** se calcula una sola vez al cargar la página.
- [ ] La condición es un conteo estricto de monedas distintas presentes
      (`> 1`), nunca un umbral de porcentaje -- una moneda que
      representa el 0.5% de los movimientos sigue siendo dinero real, y
      debe seguir mostrándose si está presente.
- [ ] El espacio liberado en la grilla superior se reutiliza según el
      punto 3/4 (tarjetas de apoyo o gráfico compacto) -- no queda un
      hueco vacío ni un salto brusco de layout.

### Casos borde a cubrir
- **Cuenta recién creada sin movimientos** (`DATA.length === 0`): 0
  monedas distintas también es `<= 1` -- la tarjeta/gráfico se ocultan
  igual que con una sola moneda, sin generar un error por dividir sobre
  un conjunto vacío. Debe convivir con el estado vacío general del
  dashboard, no mostrar una tarjeta de moneda vacía por separado.
- **Cuenta con exactamente 1 movimiento:** 1 moneda presente -> se
  oculta. No es un caso especial distinto de "una sola moneda", es
  literalmente el mismo caso con el número mínimo de movimientos.
- **Cambio dinámico al cambiar de filtro (el caso más importante,
  explícitamente pedido):** si el usuario está viendo un período con
  una sola moneda (tarjeta y gráfico ocultos) y cambia a un
  período/preset donde sí hubo 2+ monedas, ambos deben **reaparecer de
  inmediato** en el mismo re-render, sin recargar la página -- y
  viceversa. Esto debe probarse como un flujo explícito (cambiar de
  "Anual 2025" con 2 monedas a "Trimestral" con solo COP, y de vuelta),
  no asumir que "ocultar" es un estado fijo calculado una sola vez.
- **Grid de "Análisis visual" al ocultar el gráfico de dona:** el resto
  de gráficos de esa sección no debe dejar un hueco en blanco donde
  estaba "Distribución por moneda" -- el grid debe recomponerse igual
  que ya lo hace hoy para otras tarjetas condicionales (`kpiGridDeuda`,
  sub-vistas ocultas).
- **Aislamiento entre usuarios:** no aplica riesgo nuevo -- opera sobre
  datos que ya llegan filtrados por `viendo_id()` desde el backend, sin
  ninguna consulta nueva.

---

## A quién le corresponde

**Los 6 cambios son 100% de `frontend-dataviz`**, todos dentro de
`dashboard/dashboard_finanzas.html` (CSS + JS embebido). Ninguno
requiere `backend-engineer`: los datos que necesitan (`DATA_COMPLETA`,
`monedaCount`, `deudaActual`, etc.) ya llegan completos al frontend hoy;
el filtrado por período, el conteo de monedas y el cálculo de deuda ya
se hacen client-side sobre datos ya entregados por el backend filtrados
por `viendo_id()` -- no hace falta ningún endpoint nuevo, columna nueva,
ni cambio de esquema. Tampoco hay ningún campo sensible nuevo que
cifrar (todo lo que se toca es presentación y JS de agregación sobre
datos que ya existen en texto plano en el dashboard actual).

No hay trabajo de base de datos en este bloque: no se toca
`src/db_finanzas.py`, no hay migración, no hay motor de datos
involucrado más allá de lo que ya carga el dashboard hoy.

## Riesgo financiero/UX a vigilar

- **Punto 1 es el de mayor riesgo de interpretación:** si "Trimestral"/
  "Semestral"/"Anual" quedan mal definidos o el badge de rango no
  refleja exactamente las fechas incluidas, un usuario puede creer que
  está viendo "todo el año" cuando en realidad ve "últimos 3 meses" (o
  viceversa) y tomar una decisión con una base de datos incompleta sin
  saberlo. `product-designer` debería verificar, con capturas, que el
  badge de rango sea legible y esté siempre visible en las 4 opciones,
  no solo en "Personalizado".
- **Punto 3, la duplicación de "Deuda actual estimada":** si a futuro
  alguien cambia la lógica de cálculo de deuda en un solo lugar y no en
  el otro, los dos números del dashboard dejarían de coincidir --
  máximo riesgo de romper confianza en TODO el dashboard, no solo en
  esa tarjeta. `test-engineer`/`product-designer` deberían verificar
  explícitamente que ambos valores sean siempre idénticos, con datos de
  prueba que incluyan deuda real.
- **Punto 6, el umbral estricto (`> 1`, nunca por porcentaje):** vigilar
  que la implementación no derive silenciosamente hacia un umbral de
  "moneda dominante" (ej. ocultar si una moneda es >95% del total) --
  eso escondería dinero real en una moneda distinta, que es
  precisamente el tipo de opacidad que el objetivo del producto quiere
  evitar.
- **Punto 3 en mobile:** que el tamaño 2x del balance no reintroduzca
  el overflow horizontal recién resuelto -- verificar específicamente
  con un balance negativo de muchos dígitos en 375px antes de dar el
  cambio por terminado.

---

## Resumen de 1 línea por punto

1. **Filtros:** un solo control `[Trimestral | Semestral | Anual |
   Personalizado]`, mismo orden en los 3 breakpoints, con Trimestral/
   Semestral/Anual filtrando de verdad (hoy son decorativos) según
   definiciones fijas de rango, y el badge de fechas siempre visible.
2. **Contraste:** `--text-faint` sube a un valor con contraste medido
   ≥4.5:1 contra los dos fondos donde se usa (tarjeta y página), una
   sola variable, sin perder la jerarquía frente al texto principal.
3. **Jerarquía KPI:** "Balance de caja real" ≥1.8x el tamaño de las
   demás tarjetas (medido), con "Deuda actual estimada" duplicada como
   tarjeta de apoyo, sin reintroducir el overflow horizontal ya
   arreglado en mobile.
4. **Gráfico compacto:** versión compacta de "Ingresos vs. gastos"
   visible sin scroll en los 3 breakpoints, misma fuente de datos que
   el gráfico completo existente, sin empujar el Balance fuera del
   primer viewport.
5. **Íconos:** `.kpi .icon` de 20px a 28-32px con badge circular de
   color, y `CAT_ICONS.otros` cambia de `❔` a `📦` (mismo fallback ya
   usado para categorías sin mapear).
6. **Moneda única:** tarjeta KPI y gráfico de dona de "Distribución por
   moneda" se ocultan cuando el período filtrado tiene 1 sola moneda
   (o 0), se recalculan en cada cambio de filtro, y reaparecen de
   inmediato si el usuario filtra a un período con 2+ monedas.
