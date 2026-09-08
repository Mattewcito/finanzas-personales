# Presupuesto por baldes (50/30/20), metas de ahorro y deudas

## Veredicto
Aprobado -- y ya nos pusimos a construirlo. Es una idea grande, así que
la separamos en pasos para que puedas ver avances reales pronto, en vez
de esperar todo junto al final.

## De dónde sale esto
Nos mostraste la planilla que usabas antes, la del "Planeador
financiero 2026", con la regla de Necesidades / Gustos / Ahorro, y nos
dijiste algo bien claro: acá las categorías se sienten un poco absurdas,
y no tenés forma de saber si lo que gastaste estuvo bien o mal para tu
situación. Tenés toda la razón -- hoy el dashboard te cuenta lo que YA
pasó, pero no te ayuda a decidir cuánto gastar ANTES de gastarlo, que es
justo lo que tu planilla sí te daba. Esto busca traer eso de vuelta,
pero con el menor esfuerzo posible de tu parte, como pediste.

## Qué vas a poder hacer
- Definir tu propio presupuesto en 3 grupos simples -- Necesidades,
  Gustos, y Ahorro/deudas -- con 50/30/20 como punto de partida sugerido,
  pero vos podés ajustarlo a lo que te sirva.
- Ver de un vistazo, sin sumar nada a mano, cuánto gastaste de verdad
  contra cuánto tenías presupuestado en cada uno de esos 3 grupos (no 22
  categorías sueltas, que es justo lo que no querías).
- Crear metas de ahorro (por ejemplo "vacaciones" o "fondo de
  emergencia") y ver tu avance real hacia cada una.

## Cómo lo organizamos (para que no se vuelva eterno)

**Ahora mismo construimos:**
- El presupuesto por los 3 baldes, con 50/30/20 como default editable.
- Un mapeo simple de tus categorías actuales a esos 3 baldes (ya viene
  precargado con una asignación razonable -- comida, servicios, salud
  van a Necesidades; restaurantes, entretenimiento, ropa van a Gustos;
  pagos de tarjeta y ahorro van a Ahorro/deudas -- así arrancás sin
  tener que configurar nada, y lo ajustás después si algo no te calza).
- Metas de ahorro, con el mismo patrón que ya usamos para las tarjetas
  de crédito (crear, ver avance, archivar).

**Esto lo dejamos para después de que lo veas funcionando:**
- Generalizar "deudas" más allá de las tarjetas de crédito (préstamos
  personales, deudas informales). No sabemos todavía si de verdad las
  tenés -- antes de construir algo para un caso que capaz no aplica,
  preferimos preguntarte primero. Si tenés deudas de ese tipo, avisanos
  y lo armamos con el mismo cariño que le pusimos a las tarjetas.

## Criterios de aceptación
- [ ] Podés definir (y editar cuando quieras) qué porcentaje de tu
      ingreso real va a cada uno de los 3 baldes, con 50/30/20 ya
      cargado por defecto.
- [ ] El dashboard te muestra, para el período que estés mirando,
      presupuestado vs. real vs. diferencia en cada balde -- 3 líneas
      claras, no una lista larga de categorías.
- [ ] Cada categoría existente ya viene asignada a un balde por
      defecto, y podés cambiar esa asignación sin tocar código ni
      pedirnos ayuda.
- [ ] Podés crear una meta de ahorro (nombre, monto objetivo, fecha
      opcional) y ver cuánto llevás acumulado hacia ella, en el mismo
      lenguaje simple que ya usa el resto del dashboard.
- [ ] Si un balde no llega al 100% de tu ingreso entre los 3 (o se pasa),
      te lo mostramos con claridad -- así nunca queda plata "sin contar
      en ningún lado" sin que lo sepas.

## Casos borde que ya tenemos cubiertos
- **Cuenta nueva sin presupuesto configurado todavía:** el dashboard no
  se rompe ni muestra `NaN` -- simplemente te invita a configurarlo,
  igual que ya hacemos con los estados vacíos del resto de la app.
- **Cada cuenta ve solo lo suyo:** el presupuesto y las metas de ahorro
  quedan aislados por usuario, igual que todo lo demás en el proyecto.
- **Nada de esto es un dato sensible que haya que cifrar** -- son
  montos y porcentajes, el mismo criterio que ya usamos para las
  tarjetas de crédito.

## Quién hace cada parte
- **`backend-engineer`**: las tablas nuevas (presupuesto por balde,
  mapeo categoría → balde, metas de ahorro), siguiendo el mismo patrón
  que ya probamos con las tarjetas de crédito.
- **`frontend-dataviz`**: la sección nueva en el dashboard, con el
  mismo estilo simple y directo que ya le dimos al resto (KPIs con
  lenguaje claro, "Ver detalle" para lo técnico).
- **`marketing-brand`**: qué colores le quedan mejor a esta sección
  nueva -- se lo pedimos antes de que `frontend-dataviz` la construya,
  para no tener que rehacer el estilo después.
- **`test-engineer`** / **`qa-responsive`** / **`product-designer`**:
  el mismo control de calidad de siempre, sin atajos -- acá hay plata
  real de por medio, como en todo lo demás.

## Algo a cuidar entre todos
Para que esto funcione bien, conviene que los 3 porcentajes siempre
sumen 100% (o que te avisemos si no) -- así nunca hay gasto real que
quede "invisible", sin caer en ningún balde. Es el mismo cuidado que ya
le pusimos a la deuda "sin asignar" de las tarjetas, aplicado acá.

---

Avisanos si esto lo ves distinto, o si querés que empecemos por otra
parte primero -- lo vamos mostrando a medida que avanza.
