"""
Pruebas unitarias del motor de "perfil financiero" por hábitos
(src/perfil_financiero.py). Son pruebas 100% puras -- sin BD, sin Flask,
sin fixtures de app.py -- porque calcular_metricas/clasificar_perfil/
generar_perfil no hacen ningún tipo de IO.

Convención de datos: los dicts de movimientos usan exactamente el shape
de db_finanzas.obtener_movimientos() (fecha, tipo, categoria, moneda,
monto, descripcion, entidad, medio_pago, es_deuda) y los de ledger de
deuda el shape de db_finanzas.obtener_ledger_deuda() (fecha,
tipo_movimiento, monto, descripcion, entidad, saldo_acumulado).
"""
import perfil_financiero as pf


def mov(fecha, tipo, categoria, monto, es_deuda=False, moneda="COP",
        medio_pago="debito", descripcion="mov", entidad="Banco"):
    return {
        "fecha": fecha,
        "tipo": tipo,
        "categoria": categoria,
        "moneda": moneda,
        "monto": monto,
        "descripcion": descripcion,
        "entidad": entidad,
        "medio_pago": medio_pago,
        "es_deuda": es_deuda,
    }


def ledger_mov(fecha, saldo, tipo_movimiento="credito", monto=0.0):
    return {
        "fecha": fecha,
        "tipo_movimiento": tipo_movimiento,
        "monto": monto,
        "descripcion": "mov deuda",
        "entidad": "Banco",
        "saldo_acumulado": saldo,
    }


# ----------------------------- Casos vacíos / bordes -----------------------------

def test_lista_vacia_da_sin_datos_suficientes_sin_excepciones():
    metricas = pf.calcular_metricas([])
    assert metricas["n_movimientos"] == 0
    assert metricas["total_ingresos"] == 0
    assert metricas["tasa_ahorro"] is None
    assert metricas["regularidad_ingresos"] is None
    assert metricas["tendencia_deuda"] == "sin_datos"
    assert metricas["saldo_deuda_actual"] == 0.0

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Sin datos suficientes"
    assert perfil["consejos"]

    completo = pf.generar_perfil([])
    assert completo["arquetipo"] == "Sin datos suficientes"


def test_generar_perfil_lista_vacia_no_lanza_excepcion_y_devuelve_claves_base():
    completo = pf.generar_perfil([])
    for clave in ("arquetipo", "descripcion", "consejos", "metricas"):
        assert clave in completo
    assert isinstance(completo["consejos"], list)
    assert len(completo["consejos"]) <= 4


def test_un_solo_movimiento_de_ingreso_no_rompe_nada():
    """Caso borde de lista de 1 elemento: un único ingreso, sin ningún
    gasto -- tasa de ahorro del 100%, sin división por cero en
    concentración de categoría (no hay gasto)."""
    movimientos = [mov("2025-01-05", "ingreso", "salario", 2_000_000)]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["n_movimientos"] == 1
    assert metricas["total_gastos"] == 0
    assert metricas["tasa_ahorro"] == 1.0
    assert metricas["concentracion_categoria"] == 0.0
    assert metricas["regularidad_ingresos"] == 1.0

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Ahorrador consciente"


def test_un_solo_movimiento_de_gasto_sin_ingreso_no_rompe_nada():
    movimientos = [mov("2025-01-05", "gasto", "mercado", 50_000)]
    completo = pf.generar_perfil(movimientos)
    assert completo["arquetipo"] == "Sin ingresos registrados"
    assert completo["metricas"]["n_movimientos"] == 1


# ----------------------------- Sin ingresos -----------------------------

def test_solo_gastos_sin_ningun_ingreso_da_sin_ingresos_registrados():
    movimientos = [
        mov("2025-01-05", "gasto", "mercado", 100_000),
        mov("2025-02-10", "gasto", "transporte", 50_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["total_ingresos"] == 0
    assert metricas["tasa_ahorro"] is None

    perfil = pf.clasificar_perfil(metricas)
    # No debe caer en "Ingresos irregulares" ni reventar por división por cero.
    assert perfil["arquetipo"] == "Sin ingresos registrados"
    assert perfil["arquetipo"] != "Ingresos irregulares"


# ----------------------------- Gasta más de lo que ingresa -----------------------------

def test_gasta_mas_de_lo_que_ingresa_da_tasa_ahorro_negativa():
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 1_000_000),
        mov("2025-01-15", "gasto", "mercado", 1_300_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["tasa_ahorro"] < 0

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Gastando más de lo que ingresa"


# ----------------------------- Ingresos irregulares -----------------------------

def test_ingresos_solo_en_algunos_meses_da_ingresos_irregulares():
    """Ingreso grande en un solo mes de tres -- ingresos totales positivos
    y hasta con tasa de ahorro alta, pero la regularidad debe pesar más
    (se chequea antes que "ahorrador consciente" en la prioridad)."""
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 3_000_000),
        mov("2025-01-20", "gasto", "mercado", 500_000),
        mov("2025-02-10", "gasto", "transporte", 500_000),
        mov("2025-03-12", "gasto", "salud", 500_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["total_ingresos"] > 0
    assert metricas["regularidad_ingresos"] < 0.5

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Ingresos irregulares"


# ----------------------------- Concentración de gasto -----------------------------

def test_alta_concentracion_de_gasto_en_una_categoria():
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 2_000_000),
        mov("2025-01-10", "gasto", "entretenimiento", 1_000_000),
        mov("2025-01-15", "gasto", "mercado", 200_000),
        mov("2025-01-20", "gasto", "transporte", 200_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["concentracion_categoria"] >= pf.UMBRAL_CONCENTRACION
    assert metricas["categoria_top"] == "entretenimiento"

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Gasto concentrado en entretenimiento"


# ----------------------------- Ahorrador consciente -----------------------------

def test_ahorrador_consciente_sin_otras_alertas():
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 2_000_000),
        mov("2025-01-10", "gasto", "mercado", 400_000),
        mov("2025-01-15", "gasto", "transporte", 400_000),
        mov("2025-01-20", "gasto", "salud", 400_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["tasa_ahorro"] >= pf.UMBRAL_AHORRO_BUENO
    assert metricas["concentracion_categoria"] < pf.UMBRAL_CONCENTRACION

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Ahorrador consciente"


# ----------------------------- Equilibrado -----------------------------

def test_equilibrado_cuando_ninguna_regla_de_alerta_se_dispara():
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 2_000_000),
        mov("2025-01-10", "gasto", "mercado", 600_000),
        mov("2025-01-15", "gasto", "transporte", 600_000),
        mov("2025-01-20", "gasto", "salud", 600_000),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert 0 <= metricas["tasa_ahorro"] < pf.UMBRAL_AHORRO_BUENO
    assert metricas["concentracion_categoria"] < pf.UMBRAL_CONCENTRACION
    assert metricas["regularidad_ingresos"] >= 0.5

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "Equilibrado"


# ----------------------------- Prioridad: deuda de tarjeta gana a todo lo demás -----------------------------

def test_alerta_de_deuda_de_tarjeta_gana_a_cualquier_otra_regla():
    """Se arma un escenario que ADEMÁS dispararía "Gastando más de lo que
    ingresa" (tasa de ahorro negativa), gasto discrecional alto y uso de
    avances -- la alerta de deuda de tarjeta debe ganar por ser la regla
    de mayor prioridad, y los consejos deben quedar acotados a 4."""
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 1_000_000),
        mov("2025-01-10", "gasto", "entretenimiento", 1_200_000, es_deuda=False),
        mov("2025-01-15", "gasto", "compras", 1_200_000, es_deuda=True, medio_pago="credito"),
        mov("2025-01-20", "ingreso", "avance_credito", 500_000, es_deuda=True, medio_pago="avance_credito"),
    ]
    ledger = [
        ledger_mov("2025-01-01", saldo=1_000_000),
        ledger_mov("2025-01-15", saldo=2_200_000),
    ]

    metricas = pf.calcular_metricas(movimientos, ledger)
    assert metricas["uso_credito_ratio"] >= pf.UMBRAL_USO_CREDITO_ALTO
    assert metricas["tendencia_deuda"] == "creciente"
    assert metricas["tasa_ahorro"] < 0  # también dispararía "Gastando más de lo que ingresa"

    perfil = pf.clasificar_perfil(metricas)
    assert perfil["arquetipo"] == "En alerta por deuda de tarjeta"
    assert perfil["arquetipo"] != "Gastando más de lo que ingresa"
    assert len(perfil["consejos"]) <= 4


# ----------------------------- Ledger de deuda ausente -----------------------------

def test_ledger_deuda_none_no_rompe_y_queda_sin_datos():
    movimientos = [mov("2025-01-05", "ingreso", "salario", 1_000_000)]
    metricas = pf.calcular_metricas(movimientos, ledger_deuda=None)
    assert metricas["tendencia_deuda"] == "sin_datos"
    assert metricas["saldo_deuda_actual"] == 0.0


def test_ledger_deuda_lista_vacia_no_rompe_y_queda_sin_datos():
    movimientos = [mov("2025-01-05", "ingreso", "salario", 1_000_000)]
    metricas = pf.calcular_metricas(movimientos, ledger_deuda=[])
    assert metricas["tendencia_deuda"] == "sin_datos"
    assert metricas["saldo_deuda_actual"] == 0.0


# ----------------------------- Movimientos en otra moneda quedan excluidos -----------------------------

def test_movimientos_en_otra_moneda_no_afectan_las_metricas():
    """Solo se consideran movimientos en COP -- un ingreso en USD no debe
    sumarse a total_ingresos ni afectar la tasa de ahorro."""
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 1_000_000, moneda="COP"),
        mov("2025-01-10", "gasto", "mercado", 1_000_000, moneda="COP"),
        mov("2025-01-12", "ingreso", "freelance", 10_000, moneda="USD"),
    ]
    metricas = pf.calcular_metricas(movimientos)
    assert metricas["total_ingresos"] == 1_000_000
    assert metricas["n_movimientos"] == 3  # n_movimientos cuenta el total crudo


# ----------------------------- generar_perfil: contrato de salida -----------------------------

def test_generar_perfil_siempre_devuelve_las_claves_esperadas():
    movimientos = [
        mov("2025-01-05", "ingreso", "salario", 2_000_000),
        mov("2025-01-10", "gasto", "mercado", 600_000),
    ]
    completo = pf.generar_perfil(movimientos)
    for clave in ("arquetipo", "descripcion", "consejos", "metricas"):
        assert clave in completo
    assert isinstance(completo["arquetipo"], str) and completo["arquetipo"]
    assert isinstance(completo["descripcion"], str) and completo["descripcion"]
    assert isinstance(completo["consejos"], list)
    assert len(completo["consejos"]) <= 4
    assert isinstance(completo["metricas"], dict)
