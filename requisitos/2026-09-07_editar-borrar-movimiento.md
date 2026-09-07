# Editar/borrar un movimiento individual

## Veredicto
Aprobado con ajustes -- la idea en sí es la brecha más básica de CRUD
que le falta al producto (hoy se puede crear un movimiento por 4 vías
distintas pero no corregir ni un typo sin tocar la base de datos a
mano), y confirmé por grep que no existe ninguna ruta hoy
(`routes/dashboard.py`, `routes/tarjetas.py`, `routes/usuarios.py`).
Los ajustes que dejo abajo no son sobre SI construirlo sino sobre las
reglas exactas de qué pasa cuando se edita/borra un movimiento que ya
participó de la conciliación automática o que viene de una fuente que
no es 100% manual -- si no se dejan explícitas acá, alguien las va a
tener que inventar a mitad de la implementación, y es exactamente el
tipo de decisión que puede llevar a una mala interpretación financiera
(números que "cuadran" en la UI pero ya no representan lo que el banco
realmente reportó).

**Hallazgo que cambia el alcance -- hay que corregirlo como parte de
este trabajo, no es opcional:** `routes/dashboard.py::api_registrar_movimiento`
(línea 155) llama a `db.insertar_movimientos(..., origen="manual", ...)`,
pero **toda** la lógica de conciliación en `insertar_movimientos()`
(líneas 1042 y 1077 de `db_finanzas.py`) compara contra el literal
`"app_manual"`, y así lo usan consistentemente `test_conciliacion.py`,
`test_tarjetas.py`, `test_tarjetas_routes.py` y `test_actualizar_dashboard.py`.
Esto significa que **hoy, en producción, ningún movimiento cargado a
mano por un usuario real dispara jamás la rama de conciliación** que
preserva su descripción y guarda `referencia_bancaria` cuando el banco
confirma esa misma transacción por correo/PDF/Excel -- esa rama sólo
se ejercita en los tests, que sí usan el literal correcto a mano. Toda
la regla de "qué pasa si edito un movimiento ya conciliado" (ver más
abajo) depende de que `referencia_bancaria` efectivamente se pueda
setear en movimientos manuales reales -- si no se corrige el
`origen="manual"` → `origen="app_manual"` en esa línea, esa regla
queda muerta en la práctica, igual que está hoy. **Corregir esa línea
es parte de este requerimiento**, no un hallazgo aparte para otro
ciclo.

## Justificación de negocio
Un usuario que se equivoca al tipear un monto, carga un duplicado sin
querer, o ve un movimiento mal clasificado (por typo en la
descripción, por una asociación de tarjeta ambigua, o por un parseo
imperfecto de un PDF/correo) hoy no tiene ninguna forma de corregirlo
dentro de la app -- tiene que vivir con el dato incorrecto o pedir que
alguien edite `finanzas.db` a mano. Eso es exactamente lo opuesto al
objetivo del producto ("control y claridad real sobre su dinero"): un
solo número mal cargado y sin forma de corregirlo hace que el usuario
deje de confiar en el resto del dashboard. Es funcionalidad base de
cualquier app de finanzas personales (Mint, YNAB, Monarch Money -- en
todas se puede editar y borrar una transacción individual desde la
lista), no una feature diferencial: acá el riesgo de NO tenerla es más
alto que el costo de construirla.

## Qué debe poder hacer el usuario

- Desde la tabla "📑 Todos los movimientos" (la vista paginada que ya
  existe en el Dashboard, sección "Movimientos"), cada fila tiene
  acciones de **Editar** y **Borrar**. Las otras tablas resumen del
  Dashboard ("Últimos movimientos", "Mayores gastos", "Mayores
  ingresos", "Por moneda", "Deuda tarjetas") NO llevan estas acciones
  -- son vistas curadas de un vistazo, no el lugar para gestionar datos
  uno por uno; "Todos los movimientos" es la lista exhaustiva y ya
  tiene paginado, es el lugar natural.
- **Editar** abre un formulario (modal o página, decide `frontend-dataviz`)
  precargado con los datos actuales de ESE movimiento (ya están en el
  cliente -- vienen en el array `movimientos` de `/api/dashboard-data`,
  no hace falta un endpoint de lectura nuevo), con los mismos campos
  que "Registrar movimiento": fecha, tipo, monto, moneda, descripción,
  categoría, entidad, tarjeta (selector opcional).
- Al guardar una edición:
  - Si el movimiento es manual (`origen = 'app_manual'`), sin
    conciliación activa (`referencia_bancaria IS NULL`): se guarda
    directo, sin advertencias adicionales.
  - Si el movimiento **ya fue conciliado** (`referencia_bancaria IS
    NOT NULL`, es decir un correo/PDF/Excel posterior ya confirmó que
    esta fila representa una transacción real del banco) **o viene
    directo de una fuente automática** (`origen != 'app_manual'`, ej.
    `correo_imap`, `upload_excel`, `upload_pdf_tarjeta`,
    `upload_pdf_ahorros`, `gmail_bot_excel`) **y** el usuario está
    editando alguno de los campos "de identidad" (fecha, monto, tipo,
    moneda): el sistema muestra una advertencia explícita ANTES de
    guardar (ver Criterios de aceptación) que el usuario debe confirmar
    para continuar. Los campos "descriptivos" (categoría, descripción,
    entidad, tarjeta) nunca requieren esta advertencia, se editan
    siempre libremente.
  - Si el movimiento viene del canal legado del **Excel**
    (`origen = 'gmail_bot_excel'`), la advertencia es más específica y
    más fuerte que la genérica de "fuente automática" (ver casos
    borde): avisa que el cambio se puede perder en la próxima
    sincronización, no solo que "podría duplicarse".
  - Si el resultado de reclasificar el movimiento editado (mismo
    `enriquecer_movimiento()` que ya corre al insertar) da un
    `medio_pago`/`es_deuda` distinto al que tenía antes (ej. al
    corregir la descripción, deja de/empieza a contar como deuda de
    tarjeta), el sistema se lo muestra al usuario después de guardar
    -- nunca cambia esa clasificación en silencio.
- **Borrar** pide confirmación explícita (modal "¿Seguro? Esta acción
  no se puede deshacer -- no hay papelera en esta versión"). Si el
  movimiento viene de una fuente automática o ya fue conciliado, la
  confirmación incluye el aviso correspondiente (mismo criterio que en
  edición, ver casos borde).
- Editar/borrar siempre opera sobre la cuenta que se está viendo
  (`viendo_id()`) -- si un admin está viendo el perfil de otro usuario,
  ve y puede editar/borrar los movimientos de esa cuenta, con el mismo
  aviso ("Estás viendo/editando la cuenta de X") que ya usa
  `registrar.html`.

## Criterios de aceptación

- [ ] `routes/dashboard.py::api_registrar_movimiento` pasa
      `origen="app_manual"` (no `"manual"`) a `insertar_movimientos()`
      -- corregido como parte de este trabajo, con al menos un test que
      falle hoy y pase después (ej. registrar un movimiento manual vía
      la ruta HTTP, luego insertar uno automático que matchee en
      fecha+monto+tipo, y verificar que el manual termina con
      `referencia_bancaria` no nula).
- [ ] Un usuario puede editar categoría/descripción/entidad/tarjeta de
      CUALQUIER movimiento propio (manual, automático, conciliado o
      no) sin ninguna advertencia adicional a las validaciones básicas
      ya existentes (fecha y descripción no vacías, monto > 0).
- [ ] Editar fecha/monto/tipo/moneda de un movimiento manual sin
      conciliar (`origen='app_manual'`, `referencia_bancaria IS NULL`)
      se guarda directo, sin advertencia.
- [ ] Editar fecha/monto/tipo/moneda de un movimiento con
      `referencia_bancaria IS NOT NULL` requiere que el request incluya
      una confirmación explícita (ej. campo `confirmar_riesgo=true`);
      sin ella, el backend rechaza el cambio con un error claro (fuerza
      a que el frontend haya mostrado la advertencia antes de llegar
      acá -- no es solo un gate de UI). Al confirmarse, el guardado
      pone `referencia_bancaria = NULL` en la misma operación (ya no se
      puede garantizar que el dato sigue siendo lo que el banco
      confirmó).
- [ ] Editar fecha/monto/tipo/moneda de un movimiento con
      `origen != 'app_manual'` exige la misma confirmación explícita
      (`confirmar_riesgo=true`), sin bloquear el guardado una vez
      confirmado (a diferencia del caso anterior, acá no hay
      `referencia_bancaria` que limpiar -- el movimiento en sí ES el
      registro de la fuente automática).
- [ ] Un movimiento con `origen='gmail_bot_excel'` puede editarse y
      borrarse igual que cualquier otro, pero la advertencia que ve el
      usuario nombra explícitamente el riesgo real: que
      `actualizar_dashboard.py` (corre en cada deploy, ver
      `.github/workflows/deploy.yml`) borra y vuelve a insertar TODOS
      los movimientos de ese origen leyendo de nuevo el Excel, así que
      la edición/borrado se puede perder en la próxima sincronización
      si el dato sigue igual en el Excel de origen.
- [ ] Editar la descripción/tipo de un movimiento nunca reasigna
      `tarjeta_id` automáticamente, ni siquiera si el nuevo texto
      contiene unos últimos-4 dígitos que matchearían una tarjeta --
      `tarjeta_id` solo cambia si el usuario lo elige explícitamente en
      el selector de edición (mismo criterio ya establecido en
      `requisitos/2026-09-07_tarjetas-credito-cupo.md`: "nunca se
      adivina", ni al crear ni al editar).
- [ ] Si tras re-clasificar (mismo `enriquecer_movimiento()`) el
      `medio_pago`/`es_deuda` resultante cambia respecto al que tenía
      el movimiento antes de la edición, la respuesta del backend lo
      indica explícitamente (ej. `reclasificado: true` con valores
      viejo/nuevo) para que el frontend se lo muestre al usuario -- no
      se aplica en silencio.
- [ ] Un usuario puede borrar cualquier movimiento propio con
      confirmación explícita; el borrado es definitivo (hard delete),
      no hay papelera ni "deshacer" en esta versión -- dejarlo dicho en
      el copy de confirmación para que nadie asuma lo contrario.
- [ ] Borrar o editar un movimiento de OTRO usuario (id ajeno a
      `viendo_id()`) devuelve 404 ("ese movimiento no existe"), nunca
      un error que revele que existe pero pertenece a otra cuenta
      (mismo criterio que ya usa `api_borrar_tarjeta`/`api_editar_tarjeta`).
- [ ] Después de editar/borrar, `/api/dashboard-data` reflejado en el
      siguiente fetch del dashboard muestra el cambio sin necesitar
      recargar la página completa (ya es el comportamiento actual del
      dashboard dinámico, solo hay que re-disparar el fetch tras la
      acción).
- [ ] `pytest -q` en verde, incluyendo los casos nuevos de
      `test_conciliacion.py`/uno nuevo `test_editar_borrar_movimiento.py`
      antes de dar el cambio por terminado (regla ya vigente del
      proyecto).

## Casos borde a cubrir (específicos de este producto, no genéricos)

- **Conciliación (`referencia_bancaria`):** ver reglas explícitas
  arriba. Resumen para quien implemente: campos descriptivos siempre
  libres; campos de identidad (fecha/monto/tipo/moneda) en un
  movimiento conciliado requieren confirmación explícita del usuario Y
  limpian `referencia_bancaria` al guardar. Nunca se re-evalúa
  conciliación hacia atrás (no se busca un nuevo match automático tras
  editar) -- eso sería un alcance mucho mayor (reabrir el matching
  multiset de `insertar_movimientos()` fuera del flujo de inserción) y
  no lo pide el problema real que motiva esta feature.
- **Movimientos automáticos que "absorben" duplicados indefinidamente:**
  si se edita o borra un movimiento de origen automático que venía
  absorbiendo coincidencias de corridas repetidas de `leer_correo.py`
  (ver docstring de `insertar_movimientos()`), y la misma fuente se
  vuelve a correr, el movimiento puede reinsertarse como "nuevo" al no
  encontrar ya la fila que antes lo marcaba como duplicado. Esto es
  esperado (no es un bug a arreglar acá) pero DEBE comunicarse en el
  copy de la advertencia de borrado/edición -- el usuario no debe
  sorprenderse si un movimiento borrado "vuelve a aparecer" tras la
  próxima lectura de correo o resubida del mismo extracto.
- **Canal legado de Excel (`origen='gmail_bot_excel'`):** caso borde
  real y específico de este proyecto, no genérico -- ver criterio de
  aceptación dedicado arriba. `sincronizar_desde_excel()` hace
  `DELETE FROM movimientos WHERE origen='gmail_bot_excel'` y reinserta
  todo de cero desde el Excel en cada corrida de
  `actualizar_dashboard.py`, que se ejecuta en cada deploy a prod. Una
  edición o un borrado sobre estas filas puede revertirse solo, sin
  ninguna otra acción del usuario, si el Excel de origen no cambia.
- **`tarjeta_id` y reasignación automática:** confirmado explícitamente
  arriba -- nunca se re-evalúa la asociación por últimos-4 al editar
  descripción/otros campos, solo cambia por elección explícita del
  usuario en el selector. El selector de tarjeta en el formulario de
  edición ofrece las tarjetas ACTIVAS de `viendo_id()` más, si la
  tarjeta actualmente asignada al movimiento está ARCHIVADA, esa misma
  (marcada "(archivada)") para no perder visibilidad de a qué tarjeta
  pertenece un movimiento histórico -- pero no se puede re-seleccionar
  una tarjeta archivada distinta a la que ya tenía.
- **Reclasificación silenciosa (`medio_pago`/`es_deuda`):** editar la
  descripción de un movimiento puede hacer que `enriquecer_movimiento()`
  lo reclasifique (ej. agregar/quitar "T.Cred" en el texto cambia si
  cuenta como deuda de tarjeta). Esto afecta directamente
  `v_deuda_ledger` y `obtener_tarjetas_con_deuda()` (ambos leen
  `medio_pago`/`moneda` en vivo desde `movimientos`, son una VIEW y una
  consulta agregada -- no hay estado denormalizado que sincronizar,
  pero el usuario sí necesita enterarse de que su deuda total cambió
  como efecto colateral de arreglar un texto).
- **Moneda y deuda:** cambiar la `moneda` de un movimiento clasificado
  como `credito`/`avance_credito`/`pago_tarjeta_credito` entre COP y
  USD lo saca o lo mete de `v_deuda_ledger`/deuda por tarjeta (ambos
  filtran `moneda = 'COP'` a propósito). Es un caso de alto riesgo
  aritmético -- ver sección de riesgo abajo.
- **Aislamiento entre usuarios:** editar/borrar valida SIEMPRE que el
  movimiento pertenezca a `viendo_id()` antes de tocarlo (nunca confiar
  en el id que manda el cliente) -- 404 si no existe o es ajeno, mismo
  patrón que `api_editar_tarjeta`/`api_borrar_tarjeta`.
- **Estado vacío:** si `viendo_id()` no tiene ningún movimiento, la
  tabla "Todos los movimientos" ya maneja ese estado vacío hoy (ver
  `dashboard_finanzas.html` línea ~1409) -- no hay botones de
  editar/borrar que mostrar ni romper.
- **Paginación tras borrar:** si se borra el último movimiento de la
  última página visible, `renderTodosMovimientos()` ya recalcula
  `totalPaginas` y clampea `todosMovPagina` (líneas ~1398-1400) -- no
  hace falta lógica nueva de paginación, solo volver a llamar al
  render con los datos frescos tras la acción.
- **Cifrado:** no aplica -- esta feature no agrega ni toca ningún campo
  sensible/credencial (`cifrado.py` es para credenciales de
  autenticación reales, no para datos de movimientos, que ya viven en
  texto plano en toda la base, igual que se decidió para
  `tarjetas_credito`).
- **No hay papelera/deshacer en esta versión:** dejarlo explícito en el
  copy de confirmación de borrado. Si a futuro se vuelve un problema
  real (alguien borra por error algo importante), es candidato a una
  idea nueva aparte ("papelera de movimientos borrados, N días"), no se
  improvisa acá.

## A quién le corresponde

**Backend (`backend-engineer`):**
- Corregir `routes/dashboard.py::api_registrar_movimiento` para pasar
  `origen="app_manual"` en vez de `"manual"` a `insertar_movimientos()`
  (ver hallazgo del veredicto) -- con test de regresión.
- `db_finanzas.py`: `editar_movimiento(conn, usuario_id, movimiento_id,
  cambios: dict) -> tuple[bool, str | None]`, edición parcial (mismo
  criterio que `actualizar_tarjeta`/`actualizar_usuario`: solo se tocan
  los campos presentes en `cambios`). Debe:
  - Verificar pertenencia a `usuario_id` antes de nada (404 si no
    existe/es ajeno, a nivel de ruta).
  - Si `cambios` toca fecha/monto/tipo/moneda Y el movimiento existente
    tiene `referencia_bancaria IS NOT NULL` u `origen != 'app_manual'`,
    exigir `cambios["confirmar_riesgo"] is True`; si falta, devolver
    error sin aplicar nada.
  - Si se confirma un cambio de identidad sobre un movimiento con
    `referencia_bancaria` no nula, limpiarla (`= NULL`) en la misma
    transacción.
  - Recalcular `medio_pago`/`es_deuda` con `enriquecer_movimiento()`
    sobre el resultado final (mezcla de lo que no cambió + lo editado),
    y devolver si hubo reclasificación (viejo vs. nuevo) para que la
    ruta lo pase al frontend.
  - `tarjeta_id`: solo se actualiza si viene explícito en `cambios`,
    validado contra tarjetas ACTIVAS de `usuario_id` (reusar
    `obtener_tarjeta`), salvo que sea igual al `tarjeta_id` ya
    existente aunque esa tarjeta esté archivada (no forzar
    des-asignación de una tarjeta archivada solo por no tocarla).
- `db_finanzas.py`: `borrar_movimiento(conn, usuario_id,
  movimiento_id) -> bool` -- `DELETE FROM movimientos WHERE id = ? AND
  usuario_id = ?`, devuelve si borró algo. No hay restricción de FK
  entrante (nada referencia `movimientos.id`), es un delete simple.
- Rutas en `routes/dashboard.py` (mismo blueprint, mismo patrón que
  `api_registrar_movimiento`), siguiendo la convención ya usada en
  `routes/tarjetas.py`:
  - `POST /api/movimiento/<int:movimiento_id>/editar`
  - `POST /api/movimiento/<int:movimiento_id>/borrar` (exigir
    `confirmar=true` en el body como defensa adicional a nivel API, no
    solo confiar en que el frontend mostró el modal).
  - Ambas con `@login_required`, operando siempre sobre `viendo_id()`.
- Tests nuevos (`tests/test_editar_borrar_movimiento.py` o análogo)
  cubriendo: edición de campo descriptivo sin advertencia; edición de
  campo de identidad bloqueada sin `confirmar_riesgo`; edición
  confirmada que limpia `referencia_bancaria`; reclasificación
  reportada al cambiar descripción; borrado exitoso; borrado/edición
  de movimiento ajeno da 404; `tarjeta_id` nunca se re-infiere al
  editar descripción.

**Frontend (`frontend-dataviz`):**
- Botones de acción (editar/borrar) por fila SOLO en la tabla "📑 Todos
  los movimientos" (`dashboard_finanzas.html`, función
  `renderTodosMovimientos`) -- no en "Últimos movimientos"/"Mayores
  gastos"/"Mayores ingresos"/"Por moneda"/"Deuda tarjetas" (esas
  siguen usando `rowHTML()` sin cambios).
- Modal o vista de edición con los mismos campos que "Registrar
  movimiento" (`registrar.html`), precargada con los datos que ya
  están en el cliente (no hace falta pedir el movimiento de nuevo al
  servidor).
- Advertencias antes de confirmar, con el copy diferenciado que exige
  este documento: (a) genérica "puede duplicarse si se vuelve a
  detectar" para `origen != 'app_manual'`/conciliado, (b) específica y
  más fuerte para `origen = 'gmail_bot_excel'` nombrando el
  mecanismo de sincronización real. Enviar `confirmar_riesgo=true` al
  backend solo después de que el usuario confirme.
- Modal de confirmación de borrado con el mismo criterio de
  advertencias, y el aviso "esta acción no se puede deshacer".
- Banner "estás viendo/editando la cuenta de X" cuando un admin edita
  movimientos de otra cuenta (reusar el patrón ya existente en
  `registrar.html`).
- Re-fetch de `/api/dashboard-data` tras cada edición/borrado exitoso
  para refrescar toda la vista (KPIs, ledger, tarjetas, tabla) sin
  recargar la página.
- Aviso post-guardado (no bloqueante) si el backend informa
  `reclasificado: true`.

## Riesgo financiero/UX a vigilar

- El más importante: que la advertencia de "esto puede duplicarse/
  perderse" no se sienta como un tecnicismo que el usuario ignora sin
  leer -- tiene que quedar claro qué significa en plata real (ej. "si
  esto se vuelve a detectar, vas a ver el mismo gasto contado dos
  veces en tus totales"). `product-designer` debe auditar que el copy
  no sea genérico tipo "¿Estás seguro?" sin explicar la consecuencia
  real.
- Que limpiar `referencia_bancaria` al confirmar una edición de
  identidad no se perciba como "perdí la conciliación" sin explicación
  -- el usuario debe entender que reabre ese movimiento a ser
  matcheado de nuevo en el futuro, no que rompió algo.
- Que la reclasificación de `medio_pago`/`es_deuda` tras editar una
  descripción (que cambia si algo cuenta o no como deuda de tarjeta)
  se muestre con la misma seriedad que cualquier otro cambio de deuda
  -- no como un detalle técnico menor, es dinero que aparece o
  desaparece del KPI de deuda.
- Consistencia aritmética tras editar: verificar con datos de prueba
  reales que "Deuda actual estimada" y el desglose por tarjeta siguen
  cuadrando exactamente después de editar fecha/monto/moneda/tipo de
  movimientos de deuda -- mismo cuidado que ya se pidió en el
  requerimiento de tarjetas de crédito.
- Que borrar un movimiento nunca se sienta "seguro por defecto" dado
  que no hay papelera -- la confirmación debe ser inequívoca sobre que
  es irreversible.

## Ideas fuera de alcance para este ciclo (no evaluadas acá)

- **Papelera/deshacer de movimientos borrados.** Si el hard-delete sin
  red de seguridad resulta un problema real en la práctica, vale la
  pena evaluarlo como idea aparte (retención de N días antes de borrar
  definitivo) -- no se construye preventivamente acá, sería agregar
  costo de mantenimiento sin un problema confirmado todavía.
- **Búsqueda/filtro de movimientos por texto** para encontrar más
  rápido cuál editar en una lista larga -- el paginado actual alcanza
  para el volumen de datos de hoy; si se vuelve una fricción real, es
  una mejora de UX aparte, no parte de esta feature de CRUD.
