# Investigación de color -- evolución del dashboard hacia un lenguaje visual estilo Apple

**Fecha:** 2026-09-10
**Quién pide:** usuario (dueño del proyecto), directamente en conversación.
**Qué se pidió:** investigación sobre color + percepción financiera +
principios de diseño de Apple, y un plan de evolución de la paleta
actual para que el usuario entienda su situación financiera "de un
vistazo", con foco en verse tan cuidado como las mejores apps del
mercado. **Esto es investigación y recomendación escrita, no
implementación** -- ni código ni mockups reales; ese trabajo lo hace la
sesión principal (mockups) y después `frontend-dataviz` (CSS real)
sobre esta base.
**Limitación de alcance de `marketing-brand` (igual que siempre):** no
decido layout (`product-designer`), no escribo CSS/HTML/JS, no apruebo
requerimientos de negocio (`product-owner`).

---

## 0. Punto de partida real: lo que YA existe en el proyecto

Leído de `:root` en `dashboard/dashboard_finanzas.html` y
`src/templates/base.html` (coinciden en las variables compartidas):

| Variable | Hex | Uso actual |
|---|---|---|
| `--bg` | `#090c13` | fondo de página (negro-azulado, no negro puro) |
| `--bg-soft` | `#0d111b` | fondo secundario / troughs de barras |
| `--card-solid` | `#131928` | fondo de tarjetas |
| `--card-hover` | `#171e30` | hover de tarjetas/botones |
| `--text` | `#eef1f8` | texto principal (casi blanco, no blanco puro) |
| `--text-dim` | `#8d96ab` | texto secundario |
| `--text-faint` | `#949cb2` | texto terciario (subido el 2026-09-07 para cumplir WCAG AA, ver comentario en el propio archivo) |
| `--accent` | `#7c6cfb` | violeta -- marca/interactivo |
| `--accent-2` | `#38bdf8` | celeste -- secundario, confianza |
| `--green` | `#27d9a8` | ingresos / positivo (verde-teal, no verde puro) |
| `--red` | `#fb7185` | gastos / negativo / alerta (coral, no rojo puro) |
| `--gold` | `#fbbf24` | atención / highlights (`.nivel-amber` en tarjetas) |
| `--balde-necesidades` / `--balde-gustos` | `#5f8ff7` / `#e26bf5` | identidad de baldes de presupuesto (sumadas 2026-09-08, ver `qa_reports/2026-09-08/marketing_paleta_presupuesto.md`) |
| `PALETTE` (JS, 20 hex cíclicos) | ver línea 1731 de `dashboard_finanzas.html` | color de categorías/series en gráficos, asignación round-robin por índice, sin significado semántico |
| paleta de identidad de tarjeta (JS) | `['#7c6cfb','#38bdf8','#27d9a8','#f97316','#ec4899','#fbbf24']` | color fijo por tarjeta de crédito (Apple Wallet redesign, commit `227d883`, 2026-09-10) |

**Conclusión clave de este punto de partida:** el proyecto **ya tomó
casi todas las decisiones correctas** según la investigación de
mercado (sección 1): fondo oscuro azulado (no negro puro), texto casi
blanco (no blanco puro), verde-teal en vez de verde saturado, coral en
vez de rojo saturado. No hace falta -- ni se recomienda -- un cambio de
paleta de cero. El trabajo real está en (a) **curar** el `PALETTE`
cíclico de gráficos, que hoy es ruidoso, y (b) **formalizar** un
sistema de profundidad de superficies más explícito, y (c) **corregir
un problema de contraste real que ya existe** en las tarjetas de
crédito (detallado en la sección 4).

---

## 1. Investigación de mercado (con fuente)

### 1.1 Apple -- Human Interface Guidelines (Dark Mode, Color)

- **Dark Mode** ([developer.apple.com/.../dark-mode](https://developers.apple.com/design/human-interface-guidelines/foundations/dark-mode/)):
  Apple recomienda apuntar a **7:1 de contraste** para colores
  personalizados (más exigente que el mínimo WCAG AA de 4.5:1 para
  texto normal), y que la paleta oscura no sea una simple inversión de
  la clara -- algunos colores cambian de valor entero, no solo de
  fondo/texto. La paleta oscura típica usa **fondos apagados con
  primeros planos más brillantes**, con jerarquía de superficies por
  niveles de profundidad (más plano = más lejos del usuario, más claro
  = más cerca).
- **Colores semánticos** (mismo artículo, y
  [gist de HIG color](https://gist.github.com/eonist/7b5abce6979ce4a272c5de57eb0fb550/)):
  Apple nombra sus colores por **función** (`systemBlue`,
  `systemGreen`, `label`, `secondaryLabel`), no por apariencia -- el
  mismo principio que ya sigue este proyecto con `--green`/`--red`/
  `--accent` (nombrados por rol, no por tono). Esto valida la
  arquitectura de variables ya elegida acá.
- **Principio general de "usar color con propósito, no decoración"**
  (WCAG 2.1, criterio de éxito **1.4.1 "Use of Color"**, el estándar
  formal detrás de la guía de Apple de "nunca la única señal"): la
  información no puede depender solo del color -- tiene que haber un
  segundo indicador (ícono, texto, forma). Esto es exactamente lo que
  ya aplica el proyecto con `catIcon()` en los gráficos y con las
  cifras +/- junto al color en KPIs -- hay que **extenderlo
  consistentemente**, no inventarlo (ver sección 3.1).

### 1.2 Copilot Money -- la referencia más directa que existe

**Por qué es la referencia clave para este pedido puntual:** es una
app de finanzas personales nativa de Apple, **finalista de un Apple
Design Award**, construida en Swift específicamente para sentirse como
"una app nativa premium de iOS, no un dashboard fintech" -- es decir,
exactamente el objetivo que pidió el usuario.

- **Paleta de superficies** ([blakecrosley.com/guides/design/copilot-money](https://blakecrosley.com/guides/design/copilot-money)):
  fondo base **azul-marino ultra oscuro** (`#000814`, NO negro puro:
  "aporta calidez que el negro puro no puede lograr" y reduce la
  fatiga visual en sesiones largas de revisión financiera) con 4
  niveles de profundidad explícitos: fondo (`#000814`) → tarjeta
  (`#001533`) → modal elevado (`#00204D`) → área recesada (`#010D1E`).
  Texto al 90% de opacidad blanca (no blanco puro), para un efecto
  "premium, casi holográfico" sin dureza de contraste.
- **Colores semánticos** (misma fuente): **verde `#00CC4B`** para
  ingresos, **rojo-naranja `#FF4433`** para gastos, **azul `#1C6CFF`**
  para patrimonio neto/interactivo, **amarillo `#FECE4C`** para
  pendiente/advertencia.
- **Lectura para este proyecto:** la estructura semántica de Copilot
  (verde=ingreso, rojo=gasto, azul=interactivo/confianza,
  amarillo=advertencia) es **exactamente la misma estructura** que ya
  tiene este dashboard (`--green`/`--red`/`--accent`-`--accent-2`/
  `--gold`). La diferencia real está en la **saturación de fondo**
  (Copilot usa azul-marino más saturado que el casi-negro `#090c13`
  actual) y en la **tipografía de cifras grandes** (headlines
  monumentales con tracking negativo, "arquitectura, no burocracia") --
  ambas son palancas de percepción "premium" que no requieren tocar el
  significado semántico ya construido acá.

### 1.3 Apple Card / Apple Wallet -- código de color por categoría

- ([creditcards.com/card-advice/apple-card-colors](https://www.creditcards.com/card-advice/apple-card-colors/),
  [bustle.com apple-card-colors](https://www.bustle.com/p/why-does-the-apple-card-change-colors-heres-what-each-color-means-18669982)):
  Apple Card colorea cada categoría de gasto con un tono fijo y
  distinto -- naranja-amarillo (ropa/hogar), naranja oscuro (comida),
  verde (viajes), violeta (servicios), azul (transporte), rosa
  (entretenimiento), rojo (salud) -- y reusa el **mismo código de color
  entre la tarjeta, el resumen semanal y el resumen mensual**, para que
  el usuario aprenda una sola vez "este color = esta categoría" y lo
  reconozca en todas las vistas.
- **Lectura para este proyecto:** esto valida directamente el enfoque
  de "paleta de identidad de tarjeta" que `frontend-dataviz` ya
  implementó (commit `227d883`, un color fijo y determinístico por
  tarjeta) -- es el mismo patrón que usa Apple Card, no una invención
  del proyecto. También valida que **una paleta categórica de 6-8
  colores bien distinguibles es suficiente y deseable** -- Apple Card
  no usa 20 colores cíclicos para categorías, usa un puñado curado.
  Esto es evidencia directa a favor de curar el `PALETTE` de 20
  colores de este dashboard (sección 3.1).

### 1.4 Monzo y Revolut -- categorías con color + ícono, nunca solo color

- ([monzo.com/us/blog/.../trends-category-targets](https://monzo.com/us/blog/monzo-us-blog/trends-category-targets),
  búsqueda general sobre diseño Monzo/Revolut):
  las categorías de gasto en Monzo se personalizan con **nombre +
  ícono + color** simultáneamente (nunca solo color), y las metas de
  gasto ("targets") se muestran con un gráfico de barra interactivo
  que combina color + cifra + posición -- el color nunca es la única
  señal. Revolut sigue el mismo patrón de categorías con ícono
  asociado.
- **Lectura para este proyecto:** confirma otra vez el criterio de la
  sección 1.1 (WCAG 1.4.1) -- no es una preferencia estética, es un
  patrón repetido en las apps que el usuario mencionó como referencia.

### 1.5 Psicología del color en fintech (con matiz sobre qué es evidencia real y qué es marketing)

- **Confianza y calma -- azul** ([windmill.digital/psychology-of-color-in-financial-app-design](https://windmill.digital/psychology-of-color-in-financial-app-design/)):
  "el azul es la elección de color más segura a nivel global... en
  Europa y Norteamérica representa poder y confianza" -- es el color
  dominante en banca (PayPal, Chase). Cita un estudio real de
  **Hurlbert & Ling** sobre percepción de color: los participantes de
  ambos sexos reaccionan más rápido a contrastes de color azules --
  esta es la referencia más cercana a un hallazgo empírico verificable
  (percepción visual), a diferencia de otras afirmaciones del mismo
  artículo (ej. "reduce la ansiedad financiera") que son directrices de
  diseño sin estudio citado, no evidencia dura -- las señalo como
  **orientación de industria, no como métrica verificada**, para no
  sobre-afirmar donde no hay respaldo real.
- **Verde/rojo = ganancia/pérdida** (misma fuente,
  [weandthecolor.com/color-psychology-in-fintech-branding](https://weandthecolor.com/color-psychology-in-fintech-branding-how-the-right-palette-builds-user-trust/209146),
  ya citado en el informe previo de `marketing_paleta_presupuesto.md`):
  convención universal en finanzas (compra/venta, ganancia/pérdida) --
  exactamente el rol que ya cumplen `--green`/`--red` en este proyecto.
  Confirmación, no cambio necesario.
- **Estadística citada sobre decisión subconsciente de color**
  ([uxpin.com/studio/blog/color-schemes-for-apps](https://www.uxpin.com/studio/blog/color-schemes-for-apps/)):
  "los usuarios toman decisiones subconscientes sobre un producto en
  90 segundos; 62-90% de esa decisión depende del color" -- estadística
  de marketing general (Kissmetrics/CCICOLOR, sin paper primario
  verificable desde acá), la incluyo como contexto de por qué esto
  importa para la percepción de marca, no como métrica de comprensión
  de datos financieros específicamente.
- **Mint (discontinuada)** ([cnbc.com Mint shutting down](https://www.cnbc.com/2023/11/07/budgeting-app-mint-is-shutting-down-users-are-disappointed.html)):
  Intuit cerró Mint el 23 de marzo de 2024 después de 17 años,
  migrando funciones a Credit Karma. La incluyo porque el usuario la
  nombró explícitamente, pero **como referencia histórica, no como
  benchmark vigente** -- no hay producto activo para auditar su
  paleta hoy.

**Conclusión de la sección 1:** ninguna app de referencia relevante
usa fondos negros puros, textos blancos puros, o paletas categóricas
de más de ~8 colores simultáneos. Todas separan color de **identidad**
(categoría fija) de color de **estado** (dinámico), y todas refuerzan
el color con ícono/texto. El dashboard actual ya sigue este criterio
en sus piezas más nuevas (baldes de presupuesto, tarjetas de crédito);
falta aplicarlo de forma pareja en el resto (gráficos con `PALETTE`).

---

## 2. Contraste real medido (WCAG, fórmula de luminancia relativa)

Metodología: luminancia relativa `L = 0.2126·R + 0.7152·G + 0.0722·B`
sobre canales linealizados, contraste `(L1+0.05)/(L2+0.05)`. Mínimo
WCAG AA: **4.5:1** texto normal, **3:1** texto grande (≥18.66px negrita
o ≥24px regular) y componentes UI no textuales.

### 2.1 Lo que ya está bien (confirmado, no tocar)

| Combinación | Contraste medido | Resultado |
|---|---|---|
| `--text` `#eef1f8` sobre `--card-solid` `#131928` | ~15.9:1 | ✅ muy por encima de AA (y del 7:1 que pide Apple) |
| `--gold` `#fbbf24` sobre `--card-solid` `#131928` (texto de `.nivel-amber`) | **10.5:1** | ✅ AA |
| `--balde-necesidades` `#5f8ff7` sobre `--card-solid` | 5.64:1 (ya validado en informe previo) | ✅ AA |
| `--balde-gustos` `#e26bf5` sobre `--card-solid` | 6.39:1 (ya validado) | ✅ AA |

### 2.2 Riesgo NUEVO encontrado durante esta investigación (no soy quien lo implementó, lo señalo porque es directamente de color)

El rediseño de tarjetas de crédito estilo Apple Wallet (commit
`227d883`) pinta `.tarjeta-card-nombre` en **blanco sólido (`#fff`)
directamente sobre el color de identidad de la tarjeta** (el extremo
más claro del degradé, sin `text-shadow`). Medí el contraste de texto
blanco contra cada uno de los 6 colores de identidad, en su forma pura
(el punto más claro del degradé, que es exactamente donde cae el
nombre de la tarjeta):

| Color de identidad | Contraste con texto blanco `#fff` | Resultado (texto normal, mínimo 4.5:1) |
|---|---|---|
| `#7c6cfb` (violeta) | 3.89:1 | ❌ no llega |
| `#38bdf8` (celeste) | 2.14:1 | ❌ muy por debajo |
| `#27d9a8` (verde-teal) | 1.82:1 | ❌ muy por debajo |
| `#f97316` (naranja) | 2.80:1 | ❌ no llega |
| `#ec4899` (rosa) | 3.53:1 | ❌ no llega |
| `#fbbf24` (dorado) | 1.67:1 | ❌ muy por debajo |

**Ninguno de los 6 colores de identidad de tarjeta llega a 4.5:1 con
texto blanco encima**, y el nombre de la tarjeta (14.5px negrita) no
califica como "texto grande" WCAG (el umbral es 18.66px negrita), así
que el mínimo exigible es 4.5:1, no 3:1. El overlay radial blanco al
12% que ya tiene `.tarjeta-card::before` mejora la zona superior-
izquierda marginalmente, pero no alcanza a cerrar una brecha de esta
magnitud (sobre todo en verde-teal y dorado). **Esto no es parte de mi
paleta nueva -- es un hallazgo sobre una implementación de color ya
existente**, y lo dejo como insumo directo para `frontend-dataviz`/
`product-designer`, con una corrección concreta y de bajo costo: sumar
un `text-shadow` sutil (ej. `0 1px 3px rgba(0,0,0,0.55)`) sobre
`.tarjeta-card-nombre`/`.tarjeta-card-digits`, que es el mismo recurso
que usa el propio Apple Wallet real sobre tarjetas de color claro, o
alternativamente oscurecer el punto de inicio del degradé (hoy empieza
en el color puro al 0%, podría empezar en `color-mix(in oklch, ${color}
82%, black)` para ganar margen de contraste sin perder la identidad de
color).

### 2.3 Superficie elevada nueva propuesta (sección 3) -- contraste verificado

| Combinación | Contraste medido | Resultado |
|---|---|---|
| `--text` `#eef1f8` sobre `--surface-elevated` `#1b2338` (nueva) | 13.81:1 | ✅ AA con amplio margen |
| `--text-dim` `#8d96ab` sobre `--surface-elevated` `#1b2338` | 5.27:1 | ✅ AA |

---

## 3. Paleta recomendada -- evolución, no reemplazo

### 3.1 Principio rector

**No cambiar ningún valor semántico ya validado** (`--accent`,
`--accent-2`, `--green`, `--red`, `--gold`, `--balde-*`) -- la
investigación de mercado (sección 1) confirma que ya están alineados
con lo que hacen Copilot Money, Apple Card y la psicología de color de
fintech. El trabajo de esta recomendación es **sumar profundidad de
superficie** (más Apple, menos "panel plano") y **curar el ruido
visual que sí existe** (paleta cíclica de gráficos), no reinventar el
sistema.

### 3.2 Nuevas variables de superficie (profundidad, inspirado en Copilot Money / Apple Materials)

```css
:root{
  /* ... variables existentes sin tocar ... */

  /* Profundidad de superficie -- evolución Apple/Copilot Money
     (2026-09-10, marketing-brand). Una superficie "elevada" (modal,
     dropdown, tarjeta destacada) debe leerse MÁS CERCA del usuario
     -- es decir, más clara, no más oscura -- reforzando la jerarquía
     que hoy el modal logra de forma incidental con un degradé hacia
     abajo (--card-solid -> #10141f, que es MÁS oscuro, al revés del
     principio de Apple). */
  --surface-elevated: #1b2338;   /* 13.81:1 con --text -- ver sección 2.3 */
}
```

**Por qué este hex y no otro:** es un paso de luminosidad por encima
de `--card-solid` (#131928) manteniendo el mismo matiz azul-violeta de
toda la paleta (no introduce un tono nuevo), igual que Copilot Money
sube de `#001533` (tarjeta) a `#00204D` (modal) dentro de la misma
familia de azul. Uso sugerido: reemplazar el segundo stop de los
degradés de modal (`linear-gradient(180deg, var(--card-solid),
#10141f)`) por `linear-gradient(180deg, var(--surface-elevated),
var(--card-solid))` -- el modal pasa a ser la superficie más clara de
la pila, coherente con "está más cerca de vos". Esto es una sugerencia
de valor de color, la decisión de aplicarlo (y dónde) es de
`frontend-dataviz`/`product-designer`.

### 3.3 Curaduría de la paleta de gráficos (`PALETTE`) -- el cambio de más impacto real

**Problema medido:** el `PALETTE` cíclico actual tiene 20 colores con
varios pares perceptualmente muy cercanos entre sí (ej. `#fb7185` y
`#f87171`, ambos rojos casi idénticos; `#34d399`, `#4ade80` y
`#2dd4bf`, tres verdes/turquesas contiguos; `#a78bfa` y `#c084fc`, dos
violetas contiguos). Con 6 u 8 categorías simultáneas en un gráfico de
torta o barras apiladas -- el caso más común en un presupuesto
personal real (comida, transporte, servicios, entretenimiento, salud,
compras, educación, otros) -- el usuario puede terminar confundiendo
dos rebanadas del gráfico por color solo, exactamente lo opuesto al
objetivo de "entender de un vistazo". Apple Card resuelve esto con un
puñado curado de colores bien separados en matiz (sección 1.3), no con
un ciclo largo.

**Recomendación concreta:** no reemplazar el array completo (rompería
gráficos ya guardados/consistencia entre recargas si algo depende del
índice), sino **reordenar el `PALETTE` para que los primeros 8 valores
sean los más distinguibles entre sí**, y dejar el resto como cola de
respaldo para el caso raro de más de 8 categorías en un mismo gráfico:

```js
// Curaduría de PALETTE (2026-09-10, marketing-brand): los primeros 8
// valores son la paleta "primaria" -- elegidos por separación de matiz
// entre sí (>=45° aprox. en el círculo de color) para que 6-8
// categorías simultáneas se distingan de un vistazo, con el respaldo
// de catIcon()/leyenda de texto (nunca solo color, WCAG 1.4.1). Los
// 12 restantes quedan como cola de emergencia para el caso raro de
// más de 8 categorías en un mismo gráfico -- ahí sí es esperable que
// dos tonos se acerquen, pero ya es un caso límite, no el uso típico.
const PALETTE = [
  '#7c6cfb', // violeta (marca) -- hue ~247
  '#38bdf8', // celeste -- hue ~199
  '#fb923c', // naranja cálido -- hue ~24 (ya existía en el array, solo se adelanta)
  '#27d9a8', // verde-teal -- hue ~165
  '#e879f9', // magenta/orquídea -- hue ~296 (ya existía, se adelanta)
  '#fbbf24', // ámbar -- hue ~45
  '#60a5fa', // azul medio -- hue ~213 (separado de celeste por luminosidad+saturación distintas)
  '#fb7185', // coral -- hue ~355
  /* ...resto del array actual sin tocar, como cola de respaldo... */
  '#a78bfa','#34d399','#f97316','#f87171','#2dd4bf','#c084fc','#facc15',
  '#4ade80','#818cf8','#5eead4','#fda4af','#93c5fd'
];
```

Los 8 primeros son **valores que ya existen en el array actual** (cero
hex nuevos) -- esto es reordenar por prioridad de distinción, no
inventar una paleta nueva, así que el riesgo de implementación es
mínimo. Aun así, **la separación de matiz es una heurística, no una
garantía para todos los tipos de daltonismo** (protanopia,
deuteranopia, tritanopia perciben distancias de color distintas) --
antes de dar esto por definitivo, recomiendo a `frontend-dataviz`/
`product-designer` correr una simulación real (ej.
[Coblis](https://www.color-blindness.com/coblis-color-blindness-simulator/),
herramienta gratuita) sobre un gráfico real con estos 8 colores. Lo
que sí puedo garantizar desde acá es el segundo nivel de defensa
(WCAG 1.4.1): **todo gráfico que use `PALETTE` tiene que mostrar
`catIcon()` + nombre de categoría en la leyenda/tooltip, nunca un
chip de color solo** -- función que el proyecto ya tiene escrita
(`catIcon`), falta confirmar que se aplique en TODOS los gráficos que
consumen `PALETTE`, no solo en algunos.

### 3.4 Qué NO cambiar (para que quede explícito y nadie lo reabra sin motivo)

- `--accent`, `--accent-2`, `--green`, `--red`, `--gold`: validados por
  la investigación de mercado (Copilot Money usa la misma estructura
  semántica casi valor a valor) y por contraste ya medido en informes
  previos. Tocarlos generaría el mayor riesgo de romper legibilidad en
  toda la app a cambio de cero beneficio de percepción.
- `--balde-necesidades`, `--balde-gustos`: validados en
  `qa_reports/2026-09-08/marketing_paleta_presupuesto.md`, mismo
  criterio.
- `--bg`/`--card-solid`: ya son azul-marino oscuro, no negro puro --
  exactamente el mismo criterio que usa Copilot Money. No hay
  justificación de mercado para tocarlos.

---

## 4. Elementos que más se benefician del cambio, en orden de prioridad

1. **Gráficos del dashboard (`PALETTE` cíclico).** Prioridad más alta:
   es el único punto donde la investigación encontró un problema real
   de percepción "de un vistazo" (colores contiguos casi idénticos en
   listas de 6-8+ categorías), y es también el elemento más citado por
   el usuario ("mejorar la percepción del usuario final de sus
   finanzas"). Cambio de bajo riesgo (reordenar valores existentes,
   sección 3.3).
2. **Tarjetas de crédito -- contraste de texto sobre color de
   identidad.** Prioridad alta por severidad (hoy el texto blanco
   sobre 6/6 colores de identidad no cumple WCAG AA, sección 2.2),
   aunque de alcance acotado (un solo componente, una sola regla CSS a
   ajustar: `text-shadow` o degradé más oscuro en el punto de inicio).
3. **Jerarquía de superficies (modales/dropdowns).** Prioridad media:
   mejora percibida de "pulido Apple" (profundidad consistente,
   sección 3.2), pero no es un problema de comprensión de datos, es un
   problema de terminado visual -- correcto para una fase 2, no
   bloqueante.
4. **Indicadores de saldo positivo/negativo (KPIs) y barras de
   presupuesto por balde.** Prioridad baja de cambio: ya están bien
   resueltos (verde/rojo semántico + cifra explícita + ícono),
   confirmado tanto por la investigación de mercado (mismo patrón que
   Copilot Money y Monzo) como por el informe previo de
   `marketing_paleta_presupuesto.md`. Señalo esto para que quede
   explícito que **no hace falta re-abrir esta pieza** -- ya está al
   nivel de las apps de referencia.

---

## 5. Plan de implementación por fases (para `frontend-dataviz`)

### Fase 1 -- Curaduría de `PALETTE` (bajo riesgo, alto impacto de percepción)
- **Qué tocar:** solo el array `PALETTE` en `dashboard_finanzas.html`
  (reordenar, sección 3.3). No toca `:root`, no toca ningún otro
  archivo.
- **Riesgo de romper algo:** bajo. Es el mismo conjunto de valores,
  reordenado -- el único efecto visible es que categorías ya
  existentes pueden "cambiar de color" entre una carga y otra si el
  índice que reciben cambia (esto ya pasa hoy cada vez que se agrega/
  quita una categoría, no es un riesgo nuevo).
- **Validación pedida:** correr Coblis (u otro simulador gratuito de
  daltonismo) sobre un gráfico real con 6-8 categorías antes de dar
  esto por cerrado.

### Fase 2 -- Corrección de contraste en tarjetas de crédito (bajo riesgo, corrige un defecto real)
- **Qué tocar:** `.tarjeta-card-nombre`/`.tarjeta-card-digits` en
  `dashboard_finanzas.html` (agregar `text-shadow`) y/o el punto de
  inicio del degradé JS (`color-mix` un poco más oscuro). Archivo
  puntual, no toca `base.html`.
- **Riesgo:** bajo, es un ajuste cosmético acotado a un componente ya
  aislado (no hay otro elemento que dependa de ese valor exacto de
  color de tarjeta).

### Fase 3 -- `--surface-elevated` y jerarquía de modales (riesgo medio, requiere tocar CSS compartido)
- **Qué tocar:** sumar la variable en `:root` de `base.html` Y
  `dashboard_finanzas.html` (hoy las variables compartidas están
  duplicadas en ambos archivos -- corregir esto de raíz, unificarlas en
  un solo lugar, sería una mejora aparte para `frontend-dataviz`/
  `devops-engineer`, no de color), y ajustar los degradés de modal que
  hoy usan el valor hardcodeado `#10141f` en varios lugares
  (`.modal-box`, `.chart-card` modal, `perfil-card`, etc.)
- **Riesgo:** medio -- toca CSS compartido entre varias páginas
  (`base.html` se usa en toda la app), así que cualquier regresión de
  contraste ahí es más visible. Recomiendo hacerlo en una rama/commit
  separado del de la Fase 1-2, y correr una pasada visual manual de
  las páginas con modal (tarjetas, presupuesto, metas) antes de dar
  por cerrado.

### Fase 4 (opcional, evaluar con `product-owner`) -- tipografía de cifras grandes al estilo Copilot Money
- No es un cambio de color, así que lo señalo como sugerencia para
  `product-owner`/`product-designer`, no como parte de mi entregable:
  las cifras hero (saldo total, KPI principal) podrían beneficiarse de
  mayor peso/tracking negativo en vistas grandes, replicando el efecto
  "arquitectónico" que Copilot Money usa para status financiero -- pero
  esto es tipografía/layout, fuera de mi alcance de color.

---

## 6. Resumen ejecutable (para copiar)

```css
:root{
  /* Sumar, sin tocar nada existente: */
  --surface-elevated: #1b2338;   /* modales/dropdowns -- 13.81:1 con --text */
}
```

```js
// Reordenar (no reemplazar) los primeros 8 valores de PALETTE, ver
// sección 3.3 completa para justificación de cada elección.
```

```css
/* Fase 2 -- sugerido, a validar por frontend-dataviz: */
.tarjeta-card-nombre, .tarjeta-card-digits{
  text-shadow: 0 1px 3px rgba(0,0,0,0.55);
}
```

---

## 7. A quién le corresponde cada paso

- **`frontend-dataviz`**: implementar las Fases 1-3 (código real), y
  decidir el mecanismo exacto de la Fase 2 (`text-shadow` vs. degradé
  más oscuro).
- **`product-designer`**: validar que la curaduría de `PALETTE`
  (Fase 1) y la jerarquía de superficies (Fase 3) encajen con el resto
  de la auditoría de UX/accesibilidad, y correr/revisar la simulación
  de daltonismo antes de cerrar la Fase 1.
- **`product-owner`**: evaluar la sugerencia de tipografía de cifras
  grandes (Fase 4) como posible funcionalidad/mejora a futuro -- no es
  una decisión de color, solo la señalo como insumo.
- **Sesión principal / usuario**: usar este documento como base para
  los mockups visuales que pidieron -- yo no genero mockups ni código,
  solo la investigación y los valores concretos de color.
