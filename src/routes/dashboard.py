"""
routes/dashboard.py
=====================
Blueprint del dashboard: verlo, registrar un movimiento a mano, y cargar
extractos (Excel/PDF). Ver auth.py para el patrón de Blueprints elegido.
"""
import datetime
import io
import sys
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, send_from_directory, send_file

import db_finanzas as db
import perfil_financiero
from auth import login_required, viendo_id, requiere_vista_visible

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import reconciliar_extractos as rex  # parsers de PDF ya construidos y probados

UPLOADS_DIR = db.DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# La plantilla del dashboard ya NO se "hornea" con datos por usuario --
# es un único archivo estático que pide sus datos por AJAX a
# /api/dashboard-data al cargar (ver dashboard/dashboard_finanzas.html,
# función iniciarDashboard()). Ver el commit que introdujo esto para el
# porqué del cambio: el modelo viejo (un dashboard_<id>.html generado
# por usuario, escrito en disco) es lo que causaba que dev/producción
# se pisaran entre sí al compartir esa carpeta, y necesitaba un paso de
# "regenerar" manual cada vez que cambiaban los datos.
DASHBOARD_DIR = db.PROJECT_ROOT / "dashboard"

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
@requiere_vista_visible("dashboard", por_viendo=True)
def home():
    return render_template("dashboard.html", activo="dashboard")


@dashboard_bp.route("/vista/dashboard")
@login_required
@requiere_vista_visible("dashboard", por_viendo=True)
def vista_dashboard():
    return send_from_directory(DASHBOARD_DIR, "dashboard_finanzas.html")


@dashboard_bp.route("/api/dashboard-data")
@login_required
@requiere_vista_visible("dashboard", por_viendo=True)
def api_dashboard_data():
    """Todo lo que el dashboard necesita para el perfil que se esté
    viendo ahora mismo (respeta viendo_id(), igual que cualquier otra
    ruta): movimientos, ledger de deuda, y el perfil financiero por
    hábitos -- calculado al vuelo, no desde un archivo pre-generado.

    "perfil" viene en None si la cuenta vista tiene oculta la sub-vista
    "perfil_financiero" (ver db_finanzas.VISTAS_DISPONIBLES) -- es la
    única sub-vista cuyo cálculo nos ahorramos server-side. El resto de
    las sub-vistas ocultables ("insights", "deuda", "analisis",
    "movimientos") no cambian nada de lo que arma esta ruta: viajan
    igual en "movimientos"/"ledger_deuda"/"tarjetas" y se esconden del
    lado del cliente. El dashboard (dashboard_finanzas.html) recibe la
    lista completa de sub-vistas ocultas en "vistas_ocultas" para poder
    esconder esas secciones ahí, ya que ese HTML es un archivo
    estático, no una plantilla que se pueda filtrar acá.

    "tarjetas" (2026-09-07, ver
    requisitos/2026-09-07_tarjetas-credito-cupo.md) vive DENTRO de la
    sub-vista "deuda" ya existente -- no es una sub-vista nueva propia:
    {"activas": [...], "sin_asignar": <float>}. Si el usuario tiene 0
    tarjetas registradas, "activas" viaja como lista vacía y "deuda" se
    ve exactamente igual que antes de esta feature (el agregado global
    en "ledger_deuda" no cambia en nada).

    "presupuesto"/"categoria_balde"/"metas_ahorro" (2026-09-08, ver
    requisitos/2026-09-08_presupuesto-ahorro-deudas.md): el período
    filtrado NO se calcula acá -- igual que el resto de esta ruta
    (movimientos/ledger_deuda/tarjetas), viaja el histórico completo y
    es el frontend quien ya filtra "movimientos" por el período elegido
    (ver dashboard_finanzas.html::renderDashboard()); con
    "categoria_balde" (mapeo categoría->balde) y "presupuesto" (los 3
    porcentajes) el propio frontend puede recalcular presupuestado/real/
    diferencia por balde para CUALQUIER período sin pedir nada más al
    servidor. "metas_ahorro" sí es siempre acumulado histórico (el
    avance hacia una meta no tiene sentido "por período"). Si la cuenta
    vista nunca configuró presupuesto ni tiene categorías/metas propias
    todavía, estas 3 claves igual vienen con una forma válida (defaults
    50/30/20, mapeo vacío, lista vacía) -- nunca None/NaN, cumple el
    caso borde "cuenta nueva sin presupuesto configurado todavía" del
    documento de requisitos."""
    with db.conexion() as conn:
        movimientos = db.obtener_movimientos(conn, usuario_id=viendo_id())
        ledger_deuda = db.obtener_ledger_deuda(conn, usuario_id=viendo_id())
        vistas_ocultas_viendo = db.vistas_ocultas_de(conn, viendo_id())
        tarjetas = db.obtener_tarjetas_con_deuda(conn, usuario_id=viendo_id())
        presupuesto = db.obtener_presupuesto(conn, usuario_id=viendo_id())
        categoria_balde = db.obtener_mapeo_categorias(conn, usuario_id=viendo_id())
        metas_ahorro = db.obtener_metas_ahorro(conn, usuario_id=viendo_id())

    perfil = None
    if "perfil_financiero" not in vistas_ocultas_viendo:
        perfil = perfil_financiero.generar_perfil(movimientos, ledger_deuda)

    return jsonify(
        movimientos=movimientos,
        ledger_deuda=ledger_deuda,
        perfil=perfil,
        tarjetas=tarjetas,
        presupuesto=presupuesto,
        categoria_balde=categoria_balde,
        metas_ahorro=metas_ahorro,
        generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
        vistas_ocultas=sorted(vistas_ocultas_viendo),
    )


@dashboard_bp.route("/registrar")
@login_required
def registrar():
    with db.conexion() as conn:
        db.crear_esquema(conn)
        categorias = db.obtener_categorias(conn, usuario_id=viendo_id())
        entidades = db.obtener_entidades(conn, usuario_id=viendo_id())
        # Tarjetas ACTIVAS de viendo_id() -- para el selector opcional de
        # "a qué tarjeta pertenece este movimiento" (ver
        # requisitos/2026-09-07_tarjetas-credito-cupo.md). Las archivadas
        # no se ofrecen como destino de movimientos nuevos.
        tarjetas = db.obtener_tarjetas(conn, usuario_id=viendo_id(), solo_activas=True)
    return render_template("registrar.html", activo="registrar", categorias=categorias,
                            entidades=entidades, tarjetas=tarjetas)


@dashboard_bp.route("/api/registrar-movimiento", methods=["POST"])
@login_required
def api_registrar_movimiento():
    fecha = request.form.get("fecha", "").strip()
    tipo = request.form.get("tipo", "gasto").strip()
    monto_raw = request.form.get("monto", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    categoria = request.form.get("categoria", "").strip() or "otros"
    moneda = request.form.get("moneda", "COP").strip()
    entidad = request.form.get("entidad", "").strip() or "Manual"
    tarjeta_id_raw = request.form.get("tarjeta_id", "").strip()
    meta_ahorro_id_raw = request.form.get("meta_ahorro_id", "").strip()

    if not fecha or not descripcion:
        return jsonify(ok=False, error="Falta fecha o descripción."), 400
    try:
        monto = float(monto_raw)
    except ValueError:
        return jsonify(ok=False, error="El monto no es un número válido."), 400
    if monto <= 0:
        return jsonify(ok=False, error="El monto tiene que ser mayor a 0."), 400

    movimiento = {
        "fecha": fecha, "tipo": tipo, "categoria": categoria,
        "moneda": moneda, "monto": monto, "descripcion": descripcion, "entidad": entidad,
    }

    with db.conexion() as conn:
        db.crear_esquema(conn)
        # tarjeta_id es OPCIONAL -- si se manda, nunca se confía en el
        # valor crudo del formulario: tiene que pertenecer a una tarjeta
        # ACTIVA de viendo_id() (nunca de otro usuario, nunca archivada).
        # Ver requisitos/2026-09-07_tarjetas-credito-cupo.md.
        if tarjeta_id_raw:
            try:
                tarjeta_id = int(tarjeta_id_raw)
            except ValueError:
                return jsonify(ok=False, error="tarjeta_id inválido."), 400
            tarjeta = db.obtener_tarjeta(conn, usuario_id=viendo_id(), tarjeta_id=tarjeta_id)
            if not tarjeta or not tarjeta["activa"]:
                return jsonify(ok=False, error="Esa tarjeta no existe o no está activa."), 400
            movimiento["tarjeta_id"] = tarjeta_id
        # meta_ahorro_id es OPCIONAL -- mismo criterio exacto que
        # tarjeta_id de arriba (2026-09-08, ver
        # requisitos/2026-09-08_presupuesto-ahorro-deudas.md): si se
        # manda, tiene que pertenecer a una meta ACTIVA de viendo_id().
        # Este es el mecanismo completo de "el aporte a una meta se
        # registra como un movimiento más" -- no hay un endpoint aparte
        # de "aportar", es este mismo formulario con una meta elegida.
        if meta_ahorro_id_raw:
            try:
                meta_ahorro_id = int(meta_ahorro_id_raw)
            except ValueError:
                return jsonify(ok=False, error="meta_ahorro_id inválido."), 400
            meta = db.obtener_meta_ahorro(conn, usuario_id=viendo_id(), meta_id=meta_ahorro_id)
            if not meta or not meta["activa"]:
                return jsonify(ok=False, error="Esa meta de ahorro no existe o no está activa."), 400
            movimiento["meta_ahorro_id"] = meta_ahorro_id
        # "app_manual" (no "manual") -- TODA la lógica de conciliación de
        # insertar_movimientos() (y los tests que la cubren) compara
        # contra el literal exacto "app_manual" para decidir qué fila
        # puede "absorber" una coincidencia automática posterior
        # (correo/PDF/Excel) y guardarle referencia_bancaria. Con
        # "manual" ese matching nunca se disparaba para movimientos
        # cargados a mano por un usuario real -- bug de producción
        # corregido 2026-09-07 (ver
        # requisitos/2026-09-07_editar-borrar-movimiento.md).
        stats = db.insertar_movimientos(conn, [movimiento], origen="app_manual", usuario_id=viendo_id())

    # El dashboard ya no se regenera a mano -- /api/dashboard-data lee la
    # BD en cada carga de página, así que este movimiento ya está
    # disponible ni bien el navegador vuelva a pedirlo.
    return jsonify(ok=True, **stats)


def _es_true(valor_form: str | None) -> bool:
    """"true"/"1"/"on"/"yes" (sin importar mayúsculas) cuentan como
    confirmación explícita -- cualquier otra cosa (incluido ausente) no.
    Usado para confirmar_riesgo/confirmar, nunca se asume True por
    default."""
    return (valor_form or "").strip().lower() in ("true", "1", "on", "yes")


@dashboard_bp.route("/api/movimiento/<int:movimiento_id>/editar", methods=["POST"])
@login_required
def api_editar_movimiento(movimiento_id):
    """Edición parcial de UN movimiento propio de viendo_id() -- ver
    requisitos/2026-09-07_editar-borrar-movimiento.md. La validación de
    negocio (gate de confirmar_riesgo, limpieza de referencia_bancaria,
    reclasificación, tarjeta_id nunca re-inferido) vive en
    db.editar_movimiento(); acá solo se arma `cambios` a partir del
    form y se traduce el resultado a códigos HTTP.

    Aislamiento: SIEMPRE viendo_id() (contenido/datos de una cuenta,
    igual que tarjetas/registrar-movimiento), nunca
    session["usuario_id"] a secas -- un admin viendo el perfil de otro
    usuario edita los movimientos de ESA cuenta.

    "no existe / es ajeno" da 404 ANTES de intentar nada más (nunca un
    error que revele que existe pero es de otra cuenta), mismo criterio
    que api_editar_tarjeta()."""
    with db.conexion() as conn:
        db.crear_esquema(conn)
        existente = db.obtener_movimiento(conn, usuario_id=viendo_id(), movimiento_id=movimiento_id)
        if existente is None:
            return jsonify(ok=False, error="Ese movimiento no existe."), 404

        # Edición parcial: solo se incluye en `cambios` lo que el form
        # realmente mandó -- el criterio de "¿esto exige
        # confirmar_riesgo?" lo decide db.editar_movimiento() comparando
        # VALORES contra lo ya guardado, no la mera presencia de estas
        # claves (ver su docstring): así reenviar el formulario completo
        # precargado, tocando solo un campo descriptivo, nunca dispara
        # la advertencia de fecha/monto/tipo/moneda.
        cambios = {}
        for campo in ("fecha", "tipo", "monto", "moneda", "descripcion"):
            if campo in request.form:
                cambios[campo] = request.form.get(campo, "").strip()
        if "categoria" in request.form:
            cambios["categoria"] = request.form.get("categoria", "").strip() or "otros"
        if "entidad" in request.form:
            cambios["entidad"] = request.form.get("entidad", "").strip() or "Manual"
        if "tarjeta_id" in request.form:
            # tarjeta_id NUNCA se re-infiere acá -- solo cambia si esta
            # clave viene explícita en el form (selector del modal de
            # edición), nunca por texto/descripción. "" es des-asignar.
            cambios["tarjeta_id"] = request.form.get("tarjeta_id", "").strip()
        cambios["confirmar_riesgo"] = _es_true(request.form.get("confirmar_riesgo"))

        resultado = db.editar_movimiento(conn, usuario_id=viendo_id(), movimiento_id=movimiento_id, cambios=cambios)
        resultado["advertencia"] = db.advertencia_riesgo_movimiento(existente)

    if resultado["ok"]:
        return jsonify(**resultado)
    status = 404 if resultado["error"] == "Ese movimiento no existe." else 400
    return jsonify(**resultado), status


@dashboard_bp.route("/api/movimiento/<int:movimiento_id>/borrar", methods=["POST"])
@login_required
def api_borrar_movimiento(movimiento_id):
    """Hard delete DEFINITIVO de un movimiento propio de viendo_id() --
    sin papelera, sin deshacer. Exige `confirmar=true` en el body como
    defensa adicional a nivel API (no solo confiar en que el frontend
    mostró el modal de confirmación) -- mismo criterio que
    api_borrar_tarjeta(), reforzado acá porque este documento en
    particular insiste en que el borrado es irreversible."""
    with db.conexion() as conn:
        db.crear_esquema(conn)
        existente = db.obtener_movimiento(conn, usuario_id=viendo_id(), movimiento_id=movimiento_id)
        if existente is None:
            return jsonify(ok=False, error="Ese movimiento no existe."), 404

        if not _es_true(request.form.get("confirmar")):
            return jsonify(
                ok=False,
                error="Confirmá el borrado (confirmar=true) -- es definitivo, no hay papelera en esta versión.",
                advertencia=db.advertencia_riesgo_movimiento(existente),
            ), 400

        db.borrar_movimiento(conn, usuario_id=viendo_id(), movimiento_id=movimiento_id)

    return jsonify(ok=True, advertencia=db.advertencia_riesgo_movimiento(existente))


@dashboard_bp.route("/cargar-extractos")
@login_required
def cargar_extractos():
    return render_template("cargar_extractos.html", activo="cargar")


@dashboard_bp.route("/plantilla-excel")
@login_required
def plantilla_excel():
    """Excel vacío (con un ejemplo) en el formato exacto que espera la
    opción "Excel" de Cargar extractos -- para que nadie tenga que
    adivinar las columnas."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "movimientos"
    ws.append(list(db.CAMPOS_ESPERADOS))
    ws.append(["2026-01-15", "gasto", "comida", "COP", 25000, "Ejemplo: Mercado", "Bancolombia"])
    ws.append(["2026-01-15", "ingreso", "salario", "COP", 2000000, "Ejemplo: Nomina", "Bancolombia"])

    for col in ws.columns:
        letra = col[0].column_letter
        ancho = max(len(str(c.value)) for c in col) + 2
        ws.column_dimensions[letra].width = ancho

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="plantilla_movimientos.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@dashboard_bp.route("/api/cargar-extracto", methods=["POST"])
@login_required
def api_cargar_extracto():
    archivo = request.files.get("archivo")
    tipo = request.form.get("tipo", "")
    if not archivo or not archivo.filename:
        return jsonify(ok=False, error="No se recibió ningún archivo."), 400

    destino = UPLOADS_DIR / archivo.filename
    archivo.save(destino)

    try:
        if tipo == "excel":
            movimientos = _leer_excel_generico(destino)
        elif tipo == "pdf_ahorros":
            crudos = rex.parse_savings_statement(destino)
            movimientos = [rex.normalizar_savings(m) for m in crudos]
        elif tipo == "pdf_tarjeta":
            marca = (request.form.get("marca") or "Credito").strip()
            ultimos4 = (request.form.get("ultimos4") or "").strip()
            if not ultimos4:
                return jsonify(ok=False, error="Falta indicar los últimos 4 dígitos de la tarjeta."), 400
            crudos = rex.parse_card_statement(destino, ultimos4)
            movimientos = [rex.normalizar_card(m, marca) for m in crudos]
        else:
            return jsonify(ok=False, error=f"Tipo de archivo desconocido: {tipo!r}"), 400
    except Exception as e:
        return jsonify(ok=False, error=f"No pude leer el archivo: {e}"), 400

    if not movimientos:
        return jsonify(ok=False, error="No encontré movimientos en ese archivo."), 400

    with db.conexion() as conn:
        db.crear_esquema(conn)
        stats = db.insertar_movimientos(conn, movimientos, origen=f"upload_{tipo}", usuario_id=viendo_id())

    return jsonify(ok=True, **stats)


def _leer_excel_generico(path) -> list[dict]:
    """Lee un .xlsx con las mismas columnas que la tabla movimientos
    (fecha, tipo, categoria, moneda, monto, descripcion, entidad), en la
    primera hoja del archivo."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    rows = []
    headers = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else h for h in row]
            continue
        if row[0] is None:
            continue
        d = dict(zip(headers, row))

        fecha = d.get("fecha")
        if isinstance(fecha, (datetime.datetime, datetime.date)):
            d["fecha"] = fecha.strftime("%Y-%m-%d")
        elif fecha is not None:
            d["fecha"] = str(fecha)

        monto = d.get("monto")
        d["monto"] = float(monto) if monto is not None else 0.0

        for campo in db.CAMPOS_ESPERADOS:
            d.setdefault(campo, "")

        rows.append(d)
    return rows
