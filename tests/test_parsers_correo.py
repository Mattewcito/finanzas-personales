"""
Pruebas de los parsers de notificaciones de Bancolombia (leer_correo.py).
Usan textos reales (anonimizados/recortados) que ya vimos fallar antes --
cada caso acá es un formato que en algún momento rompió el parser.
"""
import leer_correo as lc


def test_compra_con_tarjeta_credito_formato_latino():
    texto = ('¡Listo! Todo salió bien con tus movimientos Bancolombia: '
             'Compraste COP758.976,00 en TEMU COM con tu T.Cred *2011, '
             'el 03/09/2026 a las 11:26.')
    r = lc.parsear_alerta_bancolombia(texto)
    assert r is not None
    assert r["monto"] == 758976.0
    assert r["fecha"] == "2026-09-03"
    assert r["moneda"] == "COP"
    assert "T.Cred" in r["descripcion"]


def test_compra_en_dolares():
    texto = ('¡Listo! Todo salió bien con tus movimientos Bancolombia: '
              'Compraste USD20,00 en ANTHROPIC* CLAUDE SU con tu T.Cred *2011, '
              'el 24/08/2026 a las 07:50.')
    r = lc.parsear_alerta_bancolombia(texto)
    assert r["moneda"] == "USD"
    assert r["monto"] == 20.0


def test_avance_de_credito():
    texto = ('¡Listo! Todo salió bien con tus movimientos Bancolombia: '
              'Hiciste un avance de $200000 en tu SUC VIRTUAL el 11:28 '
              '21/08/2026 desde tu T.Credito *2011 a la cuenta *5360.')
    r = lc.parsear_alerta_bancolombia(texto)
    assert r["monto"] == 200000.0
    assert r["categoria"] == "avance_credito"


def test_pago_qr():
    texto = ('¡Listo! Todo salió bien con tus movimientos Bancolombia: '
              'EMANUEL LOPEZ PASOS pagaste $19000.00 por codigo QR desde tu '
              'cuenta *5360 a la llave 0046104279 el 01/09/2026 a las 13:30.')
    r = lc.parsear_alerta_bancolombia(texto)
    assert r["monto"] == 19000.0
    assert r["tipo"] == "gasto"


def test_pago_recibido_nomina_se_categoriza_como_salario():
    texto = ('¡Listo! Todo salió bien con tus movimientos Bancolombia: '
              'Recibiste un pago de Nomina de EMPRESA SAS por $2026374.00 en '
              'tu cuenta de Ahorros el 31/08/2026 a las 09:22.')
    r = lc.parsear_alerta_bancolombia(texto)
    assert r["tipo"] == "ingreso"
    assert r["categoria"] == "salario"


def test_evento_no_financiero_se_ignora():
    """Activar/desactivar una tarjeta no es un movimiento -- no debe
    generar ningún registro."""
    texto = ('Por tu seguridad ¡Ya está lista! Bancolombia: Apagaste tu '
              'tarjeta credito *4112 el 03/09/2026 a las 11:43.')
    assert lc.parsear_alerta_bancolombia(texto) is None


def test_monto_formato_plano_con_coma_de_miles():
    """Este caso rompió el parser una vez: algunas alertas usan coma
    como separador de miles en vez de venir sin separador."""
    assert lc._parsear_monto_plano("7,500.00") == 7500.0


def test_monto_formato_plano_sin_separador():
    assert lc._parsear_monto_plano("1750000") == 1750000.0


def test_monto_formato_latino():
    assert lc._parsear_monto_latino("1.234.567,89") == 1234567.89
