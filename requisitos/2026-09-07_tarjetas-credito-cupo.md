# Tarjetas de crédito con cupo

## Veredicto
Aprobado con ajustes -- la idea original describe bien el problema pero
deja sueltas varias decisiones de las que este proyecto ya se ha
golpeado antes (migración retroactiva, cifrado, ambigüedad de datos).
Los ajustes que hice, con su porqué, están explicados en cada sección
de abajo; en resumen:
- Cupo total es **obligatorio** al crear la tarjeta (no "opcional" como
  todo lo demás) -- una "tarjeta con cupo" sin cupo no cumple el
  objetivo que le da nombre a esta feature.
- Los movimientos de tarjeta ya cargados **nunca** se reasignan
  retroactivamente a una tarjeta, ni siquiera si el usuario termina
  registrando una sola -- lo dejo explícito para que nadie improvise
  esa regla a mitad de la implementación.
- **No se cifra nada de esto** (cupo/nombre/entidad/últimos 4) -- son
  datos financieros equivalentes a "monto", no credenciales; cifrar
  solo el último-4 nuevo sería además inconsistente, porque ya vive en
  texto plano dentro de `descripcion` en movimientos existentes.
- El matching automático por últimos 4 dígitos **no** se implementa
  parseando `descripcion` de nuevo con una regex -- ya existe esa
  información como variable local en los parsers de `leer_correo.py` y
  `tools/reconciliar_extractos.py`, solo hay que propagarla.

## Justificación de negocio
Hoy el sistema ya sabe clasificar compras/avances/pagos de tarjeta de
crédito (`clasificar_medio_pago()`) y calcular un saldo de deuda
agregado (`v_deuda_ledger`/`obtener_ledger_deuda`), pero no existe el
concepto de "tarjeta" como entidad con capacidad propia -- alguien con
dos o más tarjetas no tiene forma de saber si está por pasarse del
cupo de una en particular hasta que el banco se lo avisa (o hasta que
le rebota una compra). Eso es exactamente el tipo de sorpresa
financiera que el objetivo del producto dice querer evitar. Cerrar
esta brecha es una extensión natural y de bajo riesgo conceptual sobre
algo que ya existe a medias, y "cupo disponible"/"% de utilización"
es un feature estándar en la categoría (CreditWise, MaxRewards,
Monarch Money lo destacan como parte central de sus apps de finanzas
personales).

## Qué debe poder hacer el usuario

- Registrar una o más tarjetas de crédito propias: nombre/etiqueta
  (obligatorio, texto libre, ej. "Bancolombia Visa Gold"), entidad/banco
  (opcional, mismo campo con autocompletado que ya usa `entidad` en
  movimientos, vía `obtener_entidades()`), cupo total (obligatorio,
  > 0), últimos 4 dígitos (opcional -- solo sirve para el matching
  automático, no es obligatorio para que la tarjeta exista).
- Editar una tarjeta ya registrada (nombre, entidad, cupo total -- ej.
  cuando el banco le sube el cupo -- y últimos 4 dígitos).
- Archivar una tarjeta que ya no usa sin perder el historial de
  movimientos asociados a ella (soft delete vía `activa=0`). Borrarla
  definitivamente solo está permitido si esa tarjeta nunca tuvo ningún
  movimiento asociado.
- Ver, en la sección ya existente del Dashboard "💳 Tarjetas de crédito
  y deuda", por cada tarjeta activa: cupo total, deuda actual de ESA
  tarjeta (no la agregada de todas), cupo disponible (cupo total −
  deuda de esa tarjeta), % de uso, y una alerta visual si el % de uso
  supera un umbral (propongo ámbar en ≥80%, rojo en ≥95% -- el
  tratamiento visual exacto lo define `product-designer` después).
- Ver aparte, con su propio total y etiqueta clara ("Sin tarjeta
  asignada"), toda la deuda de tarjeta que no está vinculada a ninguna
  tarjeta registrada (todo lo histórico previo a esta feature, y
  cualquier movimiento nuevo que no matcheó ninguna tarjeta) -- nunca
  mezclada silenciosamente dentro del número de una tarjeta real.
- Opcionalmente elegir a qué tarjeta pertenece un movimiento al
  registrarlo a mano (formulario "Registrar movimiento").
- El agregado histórico que ya existe (KPI "Deuda actual estimada", el
  gráfico de evolución, la tabla de ledger completo) sigue funcionando
  exactamente igual que hoy, sin ningún cambio -- se lo entiende ahora
  como "todas las tarjetas juntas + lo sin asignar".

## Criterios de aceptación

- [ ] Un usuario puede crear una tarjeta con nombre + cupo_total (>0);
      entidad y últimos 4 dígitos son opcionales.
- [ ] Un usuario puede editar cupo_total/nombre/entidad/últimos4 de una
      tarjeta ya creada, y el cambio se refleja de inmediato en el cupo
      disponible mostrado (no requiere recalcular ni reprocesar
      movimientos).
- [ ] Un usuario puede archivar una tarjeta: deja de aparecer en los
      selectores para asociar nuevos movimientos y en el desglose de
      tarjetas "activas" del Dashboard, sin borrar ni desasociar sus
      movimientos históricos.
- [ ] Un usuario puede borrar definitivamente una tarjeta SOLO si tiene
      0 movimientos asociados; si tiene al menos uno, el sistema
      rechaza el borrado y sugiere archivar en su lugar (ver nota de
      implementación en la sección de Backend: esto se puede apoyar en
      la propia restricción FK de SQLite, ya que `conectar()` corre con
      `PRAGMA foreign_keys = ON`).
- [ ] Un usuario con 0 tarjetas registradas ve el Dashboard exactamente
      como hoy en la sección de deuda (agregado global, sin desglose
      por tarjeta) -- nada nuevo rompe ni queda vacío de forma confusa.
- [ ] Los movimientos ya cargados antes de esta feature (con
      `medio_pago` en `credito`/`avance_credito`/`pago_tarjeta_credito`)
      NO se reasignan retroactivamente a ninguna tarjeta -- quedan y se
      muestran agrupados como "Sin tarjeta asignada".
- [ ] Un movimiento nuevo (correo automático o "Cargar extractos") que
      trae últimos 4 dígitos detectables Y ese usuario tiene
      EXACTAMENTE una tarjeta activa con esos mismos últimos 4 dígitos,
      se asocia automáticamente a esa tarjeta.
- [ ] Si el último-4 no se detecta, o hay 0 o 2+ tarjetas activas de
      ese usuario con esos mismos últimos 4 dígitos, el movimiento
      queda sin tarjeta asignada (`tarjeta_id` NULL) -- nunca se
      adivina.
- [ ] Un movimiento registrado a mano puede opcionalmente asociarse a
      una tarjeta activa elegida de una lista con las tarjetas de ESE
      usuario (`viendo_id()`); si no se elige ninguna, queda sin
      asignar, igual que hoy.
- [ ] Aislamiento entre usuarios respetado en cada punto: un usuario
      nunca ve, edita ni puede asociar movimientos a una tarjeta de
      otro usuario; todo pasa por `viendo_id()`, igual que "Registrar
      movimiento"/"Cargar extractos".
- [ ] La deuda por tarjeta usa la misma lógica de signo que
      `v_deuda_ledger` (créditos/avances suman, pago_tarjeta_credito
      resta) y el mismo filtro `moneda = 'COP'`, de modo que: suma de
      "deuda por tarjeta" (todas) + "deuda sin asignar" == "Deuda
      actual estimada" agregada, siempre.
- [ ] Si el cupo disponible calculado da negativo (sobregiro, o cupo
      cargado por debajo de la deuda ya acumulada), se muestra el
      número negativo tal cual, en rojo/alerta -- nunca se trunca a 0.

## Casos borde a cubrir (específicos de este proyecto)

- **Estado vacío (0 tarjetas):** la sección "deuda" se ve igual que
  hoy -- ningún listado vacío ni tabla rota. Si el usuario tiene
  movimientos de tarjeta sin tarjeta registrada, mostrar un llamado a
  la acción discreto tipo "Registrá tus tarjetas para ver cupo
  disponible por tarjeta" (mismo patrón `empty-state` que ya usa esta
  sección en `dashboard_finanzas.html` ~líneas 1079-1086 para "no hay
  movimientos de tarjeta en el período").
- **Aislamiento entre usuarios:** toda tabla/consulta nueva
  (`tarjetas_credito`, y el nuevo campo `movimientos.tarjeta_id`) se
  filtra siempre por `viendo_id()`, nunca por `session["usuario_id"]` a
  secas (mismo patrón documentado en `auth.py`). Un admin viendo el
  perfil de otro usuario debe poder gestionar SUS tarjetas igual que
  hoy puede registrarle un movimiento -- mismo banner de aviso que ya
  existe en `registrar.html` cuando `usuario_rol == 'admin'` y
  `viendo_id()` apunta a otra cuenta.
- **Migración de datos existentes:** movimientos ya cargados con
  `medio_pago` en (`credito`, `avance_credito`, `pago_tarjeta_credito`)
  reciben `tarjeta_id` NULL por default (columna nueva, nullable, vía
  `_agregar_columna_si_falta` -- reusar ese helper, no reinventar el
  patrón de migración). NUNCA se infiere automáticamente a qué tarjeta
  pertenecen, ni siquiera si el usuario termina registrando una sola
  tarjeta (la tarjeta pudo haber cambiado, cerrado, o haber sido otra
  distinta a la que registra hoy) -- se muestran agrupados como "Sin
  tarjeta asignada" indefinidamente, salvo que a futuro se construya
  una función de reasignación manual (fuera de alcance acá, ver más
  abajo).
- **Ambigüedad de últimos 4 dígitos:** si dos tarjetas activas del
  mismo usuario comparten el mismo último-4 (raro pero posible, ej.
  reemplazo de tarjeta con el mismo número final), nunca autoasignar
  -- el movimiento queda sin tarjeta.
- **No existe edición de movimientos individuales:** se confirmó
  (grep sobre `src/`) que no hay ninguna ruta para editar o borrar un
  movimiento ya insertado uno por uno. Por lo tanto, un movimiento que
  quedó "sin tarjeta asignada" (por ambigüedad o por ser histórico) NO
  tiene, en esta iteración, ninguna forma de corregirse a mano. Construir
  edición de movimientos individuales está fuera de alcance de este
  requerimiento -- si se vuelve un problema real, es candidato a una
  idea nueva aparte (ver sugerencias al final), no se improvisa acá.
- **Cifrado -- decisión explícita:** `cupo_total`, `nombre` y `entidad`
  de la tarjeta NO se cifran. Son datos financieros equivalentes a
  "monto"/"saldo_acumulado", que ya viven en texto plano en toda la
  base -- `cifrado.py` existe únicamente para credenciales de
  autenticación reales que la app necesita reutilizar en texto plano
  (contraseña de aplicación IMAP, cédula para desbloquear PDFs), no
  para cifras financieras en sí. Los **últimos 4 dígitos tampoco se
  cifran**: ya viven en texto plano hoy, embebidos en `descripcion` de
  movimientos existentes (ej. "Compra en TEMU COM con T.Cred *2011")
  -- cifrar solo la copia nueva en `tarjetas_credito` daría una falsa
  sensación de protección sin proteger nada real, porque el mismo dato
  sigue legible en otra columna. Si a futuro se quiere enmascarar
  visualmente el último-4 en la UI (mostrar "···· 2011"), es una
  decisión de presentación de `product-designer`, no de cifrado de
  dato.
- **Borrado de tarjeta con movimientos asociados:** no permitir un
  DELETE si algún movimiento referencia esa tarjeta -- ofrecer
  "archivar" en su lugar. Nota de implementación: como `conectar()` ya
  corre con `PRAGMA foreign_keys = ON`, declarar `tarjeta_id` como FK
  normal (sin `ON DELETE CASCADE` ni `SET NULL`) hace que SQLite mismo
  rechace el DELETE con un `IntegrityError` si hay movimientos
  asociados -- alcanza con capturarlo y devolver un mensaje claro, no
  hace falta un chequeo manual previo.
- **Consistencia con `vistas_ocultas`:** el desglose por tarjeta vive
  DENTRO de la sub-vista `"deuda"` que ya existe en
  `VISTAS_DISPONIBLES` -- no se crea una entrada nueva en ese catálogo.
  Si un admin ya oculta "Tarjetas y deudas" para un usuario, el
  desglose por tarjeta se oculta con el mismo mecanismo existente, sin
  trabajo adicional.
- **Redondeo:** usar el mismo criterio de redondeo que ya usa el resto
  del dashboard para comparar/sumar montos (el mismo que
  `insertar_movimientos()` usa para deduplicar, `round(monto)`, y el
  mismo formateador COP del frontend) -- un segundo criterio de
  redondeo distinto haría que "cupo disponible" no cuadre centavo a
  centavo con lo que el usuario sume a mano, y eso rompe confianza en
  TODO el dashboard, no solo en esta sección.
- **Moneda:** igual que `v_deuda_ledger`, todo el cálculo de deuda por
  tarjeta y % de uso debe filtrar explícitamente `moneda = 'COP'` -- no
  mezclar compras en USD de la misma tarjeta en el mismo número de
  "deuda de esta tarjeta" ni en el % de cupo usado.

## A quién le corresponde

**Backend (`backend-engineer`):**
- Tabla nueva `tarjetas_credito` en `db_finanzas.py` (esquema +
  migración idempotente, mismo patrón que `_agregar_columna_si_falta`
  ya usado en el archivo): `id`, `usuario_id` (FK `usuarios`),
  `nombre`, `entidad` (nullable), `cupo_total` (REAL; validar > 0 en la
  capa de creación/edición, no solo en la UI), `ultimos4` (TEXT,
  nullable), `activa` (INTEGER default 1), `creado_en`, `actualizado_en`.
- Columna nueva `movimientos.tarjeta_id` (INTEGER, nullable, FK a
  `tarjetas_credito`), agregada vía `_agregar_columna_si_falta` (ya
  existe ese helper).
- CRUD de tarjetas (crear/editar/archivar/borrar-si-vacía), todas las
  funciones reciben y filtran por `usuario_id` explícito, análogo a
  `obtener_categorias`/`obtener_entidades`.
- Función de cálculo (ej. `obtener_tarjetas_con_deuda(conn, usuario_id)`)
  que devuelva, por cada tarjeta activa: `cupo_total`, `deuda_actual`
  (misma lógica de signo que `v_deuda_ledger`, agrupada por
  `tarjeta_id`, `moneda='COP'`), `cupo_disponible`, y el total "sin
  tarjeta asignada" (`tarjeta_id IS NULL`) aparte.
- Auto-asociación al insertar, SIN volver a parsear `descripcion` con
  una regex nueva -- el último-4 ya se conoce como variable local en:
  `_p_compra_tarjeta`/`_p_compra_tarjeta_asociada`/`_p_avance` de
  `leer_correo.py` (variable `tarjeta`) y
  `normalizar_card()`/`parse_card_statement()` de
  `tools/reconciliar_extractos.py` (variable `ultimos4`). Propagar esa
  info al dict del movimiento (ej. clave `ultimos4`) y resolver
  `tarjeta_id` dentro de `insertar_movimientos()`/`enriquecer_movimiento()`
  antes del INSERT, buscando una tarjeta activa de ese `usuario_id` con
  ese último-4 (NULL si no hay exactamente una coincidencia).
- Endpoint(s) API para gestión de tarjetas y para exponer
  `tarjetas_con_deuda` desde `/api/dashboard-data` (agregar una clave
  nueva, ej. `"tarjetas"`, sin romper `movimientos`/`ledger_deuda`/
  `perfil` que ya consume el frontend) -- protegidos por
  `login_required` y operando sobre `viendo_id()`, igual que el resto
  de `routes/dashboard.py`.
- Extender `/api/registrar-movimiento` para aceptar un `tarjeta_id`
  opcional, validando que pertenezca a una tarjeta activa de
  `viendo_id()` (nunca confiar en el valor del formulario sin
  validar la pertenencia).

**Frontend (`frontend-dataviz`):**
- Pantalla de gestión de tarjetas (alta/edición/archivado/borrado) --
  puede ser página propia (mismo patrón que `configurar_correo.html`,
  con su ítem de menú) o un panel dentro de la sección de deuda del
  Dashboard; la decisión de dónde vive visualmente queda para
  `product-designer`, pero funcionalmente debe cubrir las 4 acciones
  sin salir del flujo normal de la app.
- En el Dashboard, dentro de la sección existente "💳 Tarjetas de
  crédito y deuda" (`dashboard_finanzas.html`, HTML ~líneas 563-582,
  JS ~líneas 1279-1311): una tarjeta/card visual por cada tarjeta
  activa con cupo total, deuda de esa tarjeta, cupo disponible, barra
  de progreso de % de uso, y alerta visual sobre el umbral (propuesto
  ámbar ≥80%, rojo ≥95%). Incluir también, aparte, el bloque "Sin
  tarjeta asignada" con su propio total, para que ese dinero nunca
  desaparezca de la vista.
- Selector de tarjeta (opcional) en el formulario "Registrar
  movimiento" (`registrar.html`), poblado con las tarjetas activas de
  `viendo_id()`.
- Manejo del estado vacío (0 tarjetas) sin romper nada de lo ya
  renderizado hoy -- seguir el mismo patrón `empty-state`/textContent
  condicional que ya usa `renderDashboard()` para "deuda" (~líneas
  1079-1086) en vez de inventar un patrón nuevo.
- Responsive: la barra de uso de cupo y las cifras (incluyendo cupo
  disponible negativo, que puede tener más dígitos que el positivo) no
  deben cortarse en mobile/tablet -- mismo tipo de riesgo que el bug
  reciente de overflow horizontal en cifras financieras (commits
  `6fc31ae`/`b65d23a`).

## Riesgo financiero/UX a vigilar

- El más importante: que "cupo disponible" nunca se confunda
  visualmente con "dinero disponible en general" (caja real) -- es
  cupo de UNA tarjeta de crédito, no plata propia. `product-designer`
  debe verificar que el copy/iconografía lo deje inequívoco (mismo
  cuidado que ya se tomó recientemente para aclarar que "Balance de
  caja real" no incluye deuda de tarjeta, ~líneas 1232-1239 de
  `dashboard_finanzas.html`).
- Que un cupo disponible negativo (sobregiro, o cupo cargado por
  debajo de la deuda real) se muestre con la misma seriedad visual que
  una deuda alta -- nunca minimizado ni truncado a 0.
- Que el bloque "Sin tarjeta asignada" no se lea como un error o un
  dato roto -- debe transmitir "esto es deuda real que todavía no
  clasificaste por tarjeta", no "algo falló en el sistema".
- Que no ver desglose por tarjeta (0 tarjetas registradas) nunca se
  interprete como "no tengo deuda" -- el agregado global debe seguir
  siendo igual de visible que hoy, sin quedar tapado por la sección
  nueva.
- Consistencia aritmética: si "deuda por tarjeta" (sumada) + "sin
  asignar" no cuadra exactamente con el KPI agregado "Deuda actual
  estimada" ya existente, eso rompe la confianza en TODOS los números
  del dashboard, no solo en este -- verificar esto con datos de prueba
  reales (varias tarjetas, movimientos sin asignar, USD mezclado) antes
  de dar por buena la implementación, no solo revisarlo visualmente.

## Ideas adicionales sugeridas para el próximo ciclo (no evaluadas en esta corrida)

1. **Edición/eliminación de un movimiento individual ya cargado.**
   Confirmado leyendo el código: no existe ninguna ruta para editar o
   borrar un movimiento puntual (solo alta e inserción con dedup). Es
   una brecha real y transversal -- no solo ayudaría a corregir una
   `tarjeta_id` mal asignada a futuro, sino cualquier error de tipeo,
   categoría o descripción cargados a mano o mal detectados por el
   bot. Justifica una idea propia (con su propio análisis de
   aislamiento entre usuarios y de qué pasa con movimientos que ya
   fueron "consumidos" por la lógica de dedup de `insertar_movimientos()`).

2. **Presupuestos/límites de gasto por categoría, con alerta de
   sobregasto.** Confirmado leyendo `perfil_financiero.py`: hoy el
   "perfil financiero" solo genera consejos narrativos (texto
   cualitativo), no hay ningún concepto de meta numérica que el
   usuario fije (ej. "no más de $400.000 en restaurantes este mes") ni
   alerta cuando se supera. Es el mismo patrón de valor que esta
   feature de tarjetas (pasar de "cuánto gasté" a "cuánto margen me
   queda antes de un límite que yo mismo definí") pero aplicado a
   categorías de gasto en vez de cupo de tarjeta -- vale la pena
   evaluarla en un ciclo aparte.
