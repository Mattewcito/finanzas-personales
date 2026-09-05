"""
Pruebas unitarias de la clasificación caja-real vs. deuda de tarjeta --
la lógica más importante del proyecto (si esto se rompe, el dashboard
entero da números mal).
"""
import db_finanzas as db


def test_compra_con_tarjeta_de_credito():
    assert db.clasificar_medio_pago("Compra en TEMU COM con T.Cred *2011") == "credito"


def test_compra_con_tarjeta_debito():
    assert db.clasificar_medio_pago("Compra en UBER RIDES con T.Deb *3167") == "debito"


def test_avance_de_credito():
    assert db.clasificar_medio_pago("Avance T.Credito *2011 a cuenta *5360") == "avance_credito"


def test_pago_de_tarjeta():
    assert db.clasificar_medio_pago("Pago tarjeta Mastercard *2011") == "pago_tarjeta_credito"


def test_transferencia_generica_es_debito_por_defecto():
    assert db.clasificar_medio_pago("Transferencia a cuenta *60963448182") == "debito"


def test_texto_vacio_no_rompe():
    assert db.clasificar_medio_pago("") == "debito"
    assert db.clasificar_medio_pago(None) == "debito"


def test_avance_reclasifica_a_ingreso_marcado_como_deuda():
    """El caso más delicado: un avance de tarjeta ENTRA a la cuenta (es
    caja) pero es deuda, no ingreso real -- no debe mezclarse con salario."""
    row = {"tipo": "gasto", "categoria": "otros", "monto": 200000,
           "descripcion": "Avance T.Credito *2011 a cuenta *5360"}
    out = db.enriquecer_movimiento(row)
    assert out["tipo"] == "ingreso"
    assert out["es_deuda"] is True
    assert out["categoria"] == "avance_credito"


def test_compra_a_credito_es_deuda_no_gasto_real():
    row = {"tipo": "gasto", "categoria": "compras", "monto": 50000,
           "descripcion": "Compra en TEMU COM con T.Cred *2011"}
    out = db.enriquecer_movimiento(row)
    assert out["es_deuda"] is True


def test_compra_a_debito_es_gasto_real():
    row = {"tipo": "gasto", "categoria": "comida", "monto": 20000,
           "descripcion": "Compra en TOSTAO con T.Deb *8058"}
    out = db.enriquecer_movimiento(row)
    assert out["es_deuda"] is False


def test_pago_de_tarjeta_no_es_deuda_es_caja_real():
    """Pagar la tarjeta SÍ es plata real que sale de la cuenta -- abona
    deuda, no la genera."""
    row = {"tipo": "gasto", "categoria": "otros", "monto": 100000,
           "descripcion": "Pago tarjeta Mastercard *2011"}
    out = db.enriquecer_movimiento(row)
    assert out["es_deuda"] is False
    assert out["categoria"] == "pago_tarjeta_credito"
