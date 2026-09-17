"""
Pruebas de db_finanzas.eliminar_usuario() y de
routes/usuarios.py::api_eliminar_usuario (POST /api/eliminar-usuario/<id>).

Cobertura:
  - Función de DB: borra la fila del usuario y todos sus datos asociados
    (correo_config, vistas_ocultas, tarjetas_credito, presupuesto,
    presupuesto_categorias, metas_ahorro). Verifica que movimientos del
    usuario NO se eliminan (la función actual no los toca -- si en el
    futuro se decide eliminarlos también, este test fallará y hay que
    actualizar a propósito).
  - Ruta: control de acceso (sin sesión, usuario normal, auto-eliminación,
    único admin restante), 404 para usuario inexistente, y el happy path
    (eliminación exitosa verificada en BD).

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida. Ver el
docstring de tests/test_app_integration.py para el detalle.
"""
import pytest

import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ===========================================================================
# Helpers internos (sin Flask, operan directamente sobre la conexión)
# ===========================================================================

def _crear_usuario_normal(conn, suffix="x"):
    """Crea un usuario de rol 'usuario' y devuelve su id."""
    return db.crear_usuario(conn, f"user_{suffix}", f"clave-{suffix}-123", "usuario", f"Usuario {suffix}")


def _insertar_datos_asociados(conn, usuario_id: int) -> None:
    """Inserta una fila en cada tabla dependiente de usuario_id para que los
    tests puedan verificar que eliminar_usuario las borra todas."""
    import cifrado
    # correo_config (campos sensibles cifrados, igual que guardar_correo_config)
    conn.execute(
        """INSERT INTO correo_config
               (usuario_id, email, app_password, imap_host, imap_port, activo,
                frecuencia_tipo, frecuencia_minutos)
           VALUES (?, ?, ?, 'imap.gmail.com', 993, 1, 'intervalo', 30)""",
        (usuario_id, cifrado.cifrar("test@test.com"), cifrado.cifrar("app-pass")),
    )
    # vistas_ocultas
    conn.execute(
        "INSERT INTO vistas_ocultas (usuario_id, vista) VALUES (?, ?)",
        (usuario_id, "correo_automatico"),
    )
    # tarjetas_credito
    conn.execute(
        "INSERT INTO tarjetas_credito (usuario_id, nombre, cupo_total) VALUES (?, ?, ?)",
        (usuario_id, "Tarjeta Test", 5_000_000.0),
    )
    # presupuesto
    conn.execute(
        "INSERT INTO presupuesto (usuario_id, pct_necesidades, pct_gustos, pct_ahorro_deudas) VALUES (?, ?, ?, ?)",
        (usuario_id, 50.0, 30.0, 20.0),
    )
    # presupuesto_categorias
    conn.execute(
        "INSERT INTO presupuesto_categorias (usuario_id, categoria, balde) VALUES (?, ?, ?)",
        (usuario_id, "comida", "necesidades"),
    )
    # metas_ahorro
    conn.execute(
        "INSERT INTO metas_ahorro (usuario_id, nombre, monto_objetivo) VALUES (?, ?, ?)",
        (usuario_id, "Meta Test", 1_000_000.0),
    )
    conn.commit()


def _contar(conn, tabla: str, usuario_id: int) -> int:
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM {tabla} WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()["n"]


# ===========================================================================
# Tests de db_finanzas.eliminar_usuario() (capa de datos)
# ===========================================================================

class TestEliminarUsuarioDB:

    def test_eliminar_usuario_borra_la_fila_de_usuarios(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim1")
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert db.obtener_usuario(conn, victim_id) is None
        conn.close()

    def test_eliminar_usuario_borra_correo_config(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim2")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "correo_config", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "correo_config", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_borra_vistas_ocultas(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim3")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "vistas_ocultas", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "vistas_ocultas", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_borra_tarjetas_credito(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim4")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "tarjetas_credito", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "tarjetas_credito", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_borra_presupuesto(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim5")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "presupuesto", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "presupuesto", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_borra_presupuesto_categorias(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim6")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "presupuesto_categorias", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "presupuesto_categorias", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_borra_metas_ahorro(self, app_ctx):
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim7")
        _insertar_datos_asociados(conn, victim_id)
        assert _contar(conn, "metas_ahorro", victim_id) == 1
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        assert _contar(conn, "metas_ahorro", victim_id) == 0
        conn.close()

    def test_eliminar_usuario_sin_datos_asociados_no_falla(self, app_ctx):
        """Un usuario recién creado, sin ninguna fila en las tablas
        dependientes, no debe lanzar ninguna excepción al eliminarse."""
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "victim8")
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)  # no debe lanzar
        conn.close()

        conn = db.conectar()
        assert db.obtener_usuario(conn, victim_id) is None
        conn.close()

    def test_eliminar_usuario_con_id_inexistente_no_falla(self, app_ctx):
        """La función no lanza si el id no existe -- es idempotente desde
        el punto de vista de la DB (DELETE WHERE no lanza si no hay filas)."""
        flaskapp, admin_id, _ = app_ctx
        conn = db.conectar()
        db.eliminar_usuario(conn, 999999)  # no debe lanzar
        conn.close()

    def test_eliminar_usuario_no_toca_movimientos_de_otros_usuarios(self, app_ctx):
        """Los movimientos de otros usuarios no deben verse afectados."""
        flaskapp, admin_id, user_id = app_ctx
        # Insertar un movimiento para admin (el que sobrevive)
        conn = db.conectar()
        db.insertar_movimientos(
            conn,
            [{"fecha": "2026-01-01", "tipo": "gasto", "categoria": "otros",
              "moneda": "COP", "monto": 1000.0, "descripcion": "Del admin",
              "entidad": "Test"}],
            origen="manual",
            usuario_id=admin_id,
        )
        victim_id = _crear_usuario_normal(conn, "victim9")
        conn.close()

        conn = db.conectar()
        db.eliminar_usuario(conn, victim_id)
        conn.close()

        conn = db.conectar()
        movs = db.obtener_movimientos(conn, usuario_id=admin_id)
        conn.close()
        assert len(movs) == 1
        assert movs[0]["descripcion"] == "Del admin"


# ===========================================================================
# Tests de POST /api/eliminar-usuario/<usuario_id> (ruta Flask)
# ===========================================================================

class TestApiEliminarUsuario:

    # -----------------------------------------------------------------------
    # Control de acceso
    # -----------------------------------------------------------------------

    def test_sin_sesion_redirige_a_login(self, client, app_ctx):
        _, admin_id, user_id = app_ctx
        resp = client.post(f"/api/eliminar-usuario/{user_id}")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_usuario_normal_recibe_403(self, client, app_ctx):
        _, admin_id, user_id = app_ctx
        login(client, "user_test", "clave-user-456")
        resp = client.post(f"/api/eliminar-usuario/{admin_id}")
        assert resp.status_code == 403
        assert resp.get_json()["ok"] is False

    # -----------------------------------------------------------------------
    # Reglas de negocio
    # -----------------------------------------------------------------------

    def test_admin_no_puede_eliminarse_a_si_mismo(self, client, app_ctx):
        _, admin_id, user_id = app_ctx
        login(client, "admin_test", "clave-admin-123")
        resp = client.post(f"/api/eliminar-usuario/{admin_id}")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "mismo" in data["error"].lower() or "vos" in data["error"].lower()

    def test_no_puede_eliminarse_el_unico_admin_restante(self, client, app_ctx):
        """La ruta cuenta admins en la BD en el momento de la petición. Para
        que `len(admins) <= 1` se dispare (y devuelva 400) la víctima debe ser
        admin y debe ser el ÚNICO admin existente en la BD al momento del
        request.

        Escenario: admin_A inicia sesión (session.rol = 'admin'). Luego su
        rol en la BD se degrada a 'usuario' sin cerrar sesión, dejando solo
        a admin_B como admin en la BD. Cuando admin_A intenta borrar a
        admin_B, la ruta ve: session.rol='admin' (pasa el guard), el target
        no es admin_A (pasa el auto-borrado), admin_B es admin en la BD, y
        len(admins)==1 → 400."""
        flaskapp, admin_id, user_id = app_ctx

        # Crear el segundo admin (la víctima que NO se debe poder borrar)
        conn = db.conectar()
        victima_admin_id = db.crear_usuario(
            conn, "admin_victima", "clave-victima-999", "admin", "Admin Víctima"
        )
        conn.close()

        # Loguear como admin_test (session.rol queda "admin")
        login(client, "admin_test", "clave-admin-123")

        # Degradar admin_test en la BD a 'usuario' SIN cerrar sesión:
        # ahora el único admin en la BD es victima_admin_id.
        conn = db.conectar()
        db.actualizar_usuario(conn, admin_id, rol="usuario")
        conn.close()

        # Intentar borrar al único admin restante en la BD → debe dar 400
        resp = client.post(f"/api/eliminar-usuario/{victima_admin_id}")

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "administrador" in data["error"].lower() or "admin" in data["error"].lower()

        # La víctima no debe haber sido eliminada
        conn = db.conectar()
        assert db.obtener_usuario(conn, victima_admin_id) is not None
        conn.close()

    def test_usuario_inexistente_da_404(self, client, app_ctx):
        login(client, "admin_test", "clave-admin-123")
        resp = client.post("/api/eliminar-usuario/999999")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False

    # -----------------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------------

    def test_admin_puede_eliminar_usuario_normal(self, client, app_ctx):
        flaskapp, admin_id, user_id = app_ctx
        login(client, "admin_test", "clave-admin-123")

        resp = client.post(f"/api/eliminar-usuario/{user_id}")

        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        conn = db.conectar()
        assert db.obtener_usuario(conn, user_id) is None
        conn.close()

    def test_admin_puede_eliminar_otro_admin_cuando_quedan_dos(self, client, app_ctx):
        """Con 2 admins, eliminar uno deja 1 → permitido (la regla solo
        bloquea si el resultado sería 0 admins)."""
        flaskapp, admin_id, user_id = app_ctx
        conn = db.conectar()
        segundo_admin_id = db.crear_usuario(
            conn, "admin2_ok", "clave-admin2-ok1", "admin", "Admin Dos OK"
        )
        conn.close()

        login(client, "admin_test", "clave-admin-123")
        resp = client.post(f"/api/eliminar-usuario/{segundo_admin_id}")

        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        conn = db.conectar()
        assert db.obtener_usuario(conn, segundo_admin_id) is None
        conn.close()

    def test_eliminar_usuario_borra_sus_datos_asociados_via_ruta(self, client, app_ctx):
        """Verificación end-to-end: después de llamar a la ruta, los datos
        asociados del usuario eliminado no deben quedar en la BD."""
        flaskapp, admin_id, _ = app_ctx

        # Crear víctima con datos en todas las tablas dependientes
        conn = db.conectar()
        victim_id = _crear_usuario_normal(conn, "e2e_victim")
        _insertar_datos_asociados(conn, victim_id)
        conn.close()

        login(client, "admin_test", "clave-admin-123")
        resp = client.post(f"/api/eliminar-usuario/{victim_id}")
        assert resp.status_code == 200

        conn = db.conectar()
        assert db.obtener_usuario(conn, victim_id) is None
        for tabla in ("correo_config", "vistas_ocultas", "tarjetas_credito",
                      "presupuesto", "presupuesto_categorias", "metas_ahorro"):
            assert _contar(conn, tabla, victim_id) == 0, (
                f"Tabla '{tabla}' todavía tiene filas del usuario eliminado"
            )
        conn.close()

    def test_respuesta_es_json_con_ok_true(self, client, app_ctx):
        """La ruta debe devolver Content-Type application/json con ok=True."""
        flaskapp, admin_id, user_id = app_ctx
        login(client, "admin_test", "clave-admin-123")

        resp = client.post(f"/api/eliminar-usuario/{user_id}")

        assert resp.content_type.startswith("application/json")
        assert resp.get_json() == {"ok": True}
