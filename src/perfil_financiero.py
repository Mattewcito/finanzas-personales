"""
perfil_financiero.py
=====================
Motor de "perfil financiero" por usuario: analiza el historial COMPLETO
de movimientos de una cuenta y devuelve una clasificación de sus hábitos
financieros (un arquetipo), una descripción en lenguaje natural y una
lista corta de consejos accionables -- generado automáticamente a partir
de los datos, sin que nadie tenga que escribirlo a mano.

Se calcula UNA vez por usuario sobre TODO su historial (no por período
filtrado): un "hábito" es un patrón de largo plazo, no algo que tenga
sentido recalcular cada vez que alguien cambia el filtro de mes.
`actualizar_dashboard.py` lo inyecta en el dashboard igual que ya hace
con DATA/DEUDA_TARJETAS (ver marcador PERFIL_FINANCIERO en la plantilla).

Reglas de diseño (las mismas que ya rigen el resto del proyecto):
  - Nunca asume que hay datos: 0 movimientos, un usuario sin ingresos,
    sin deuda, sin gastos, etc. deben devolver un perfil válido, nunca
    lanzar una excepción ni dividir por cero.
  - La clasificación es determinística (reglas explícitas, no IA/ML) --
    se puede explicar y probar con pytest como cualquier otra función.
  - No es asesoría financiera profesional: los consejos son generales,
    igual que la advertencia que ya existe para la clasificación de
    deuda en el resto del dashboard.
"""

from __future__ import annotations

import datetime

# Categorías consideradas "esenciales" vs "discrecionales" por palabras
# clave -- mismo enfoque de clasificación por texto que ya usa
# clasificar_medio_pago() en db_finanzas.py (sin IA, ajustable a mano si
# aparecen categorías nuevas que no encajen bien).
CATEGORIAS_ESENCIALES = {
    "arriendo", "vivienda", "servicios", "mercado", "supermercado",
    "salud", "transporte", "educacion", "educación", "seguros",
}
CATEGORIAS_DISCRECIONALES = {
    "entretenimiento", "restaurantes", "comida", "ocio", "compras",
    "suscripciones", "viajes", "ropa", "tecnologia", "tecnología",
    "bares", "delivery",
}

UMBRAL_CONCENTRACION = 0.40      # 40% del gasto en una sola categoría
UMBRAL_USO_CREDITO_ALTO = 0.45   # 45% de los gastos cargados a crédito
UMBRAL_AHORRO_BUENO = 0.20       # 20% de ahorro sobre ingresos reales
UMBRAL_DISCRECIONAL_ALTO = 0.35  # 35% del gasto es discrecional


def _tipo_categoria(categoria: str) -> str:
    c = (categoria or "").strip().lower()
    if c in CATEGORIAS_ESENCIALES:
        return "esencial"
    if c in CATEGORIAS_DISCRECIONALES:
        return "discrecional"
    return "otro"


def calcular_metricas(movimientos: list[dict], ledger_deuda: list[dict] | None = None) -> dict:
    """Calcula las métricas de hábitos financieros a partir del
    historial de un usuario. Nunca lanza excepciones: con 0 movimientos
    (o sin ingresos, sin gastos, sin deuda) devuelve una estructura
    válida con los campos en 0 o None en vez de reventar."""
    ledger_deuda = ledger_deuda or []

    cop = [m for m in movimientos if m.get("moneda") == "COP"]
    ingresos_reales = [m for m in cop if m.get("tipo") == "ingreso" and not m.get("es_deuda")]
    gastos_caja = [m for m in cop if m.get("tipo") == "gasto" and not m.get("es_deuda")]
    gastos_credito = [m for m in cop if m.get("tipo") == "gasto" and m.get("es_deuda")]
    avances = [m for m in cop if m.get("categoria") == "avance_credito"]

    total_ingresos = sum(m["monto"] for m in ingresos_reales)
    total_gastos_caja = sum(m["monto"] for m in gastos_caja)
    total_gastos_credito = sum(m["monto"] for m in gastos_credito)
    total_gastos = total_gastos_caja + total_gastos_credito

    tasa_ahorro = ((total_ingresos - total_gastos_caja) / total_ingresos) if total_ingresos else None
    uso_credito_ratio = (total_gastos_credito / total_gastos) if total_gastos else 0.0

    # Concentración: qué tanto pesa la categoría de gasto más grande sobre el total.
    por_categoria: dict[str, float] = {}
    for m in gastos_caja + gastos_credito:
        cat = (m.get("categoria") or "otros").strip().lower()
        por_categoria[cat] = por_categoria.get(cat, 0.0) + m["monto"]
    categoria_top = max(por_categoria.items(), key=lambda kv: kv[1]) if por_categoria else None
    concentracion_categoria = (categoria_top[1] / total_gastos) if (categoria_top and total_gastos) else 0.0

    # % del gasto en categorías discrecionales (lo más fácil de recortar).
    gasto_discrecional = sum(v for k, v in por_categoria.items() if _tipo_categoria(k) == "discrecional")
    pct_discrecional = (gasto_discrecional / total_gastos) if total_gastos else 0.0

    # Regularidad de ingresos: en cuántos meses distintos hubo al menos
    # un ingreso real, sobre el total de meses con CUALQUIER movimiento.
    meses_con_movimiento = {m["fecha"][:7] for m in cop if m.get("fecha")}
    meses_con_ingreso = {m["fecha"][:7] for m in ingresos_reales if m.get("fecha")}
    regularidad_ingresos = (len(meses_con_ingreso) / len(meses_con_movimiento)) if meses_con_movimiento else None

    # Tendencia de deuda: compara el saldo acumulado al inicio y al final
    # del ledger (umbral del 5% para no marcar como "tendencia" ruido mínimo).
    tendencia_deuda = "sin_datos"
    saldo_actual = ledger_deuda[-1]["saldo_acumulado"] if ledger_deuda else 0.0
    if len(ledger_deuda) >= 2:
        saldo_inicial = ledger_deuda[0]["saldo_acumulado"]
        if saldo_inicial == 0:
            tendencia_deuda = "creciente" if saldo_actual > 0 else "estable"
        elif saldo_actual > saldo_inicial * 1.05:
            tendencia_deuda = "creciente"
        elif saldo_actual < saldo_inicial * 0.95:
            tendencia_deuda = "decreciente"
        else:
            tendencia_deuda = "estable"
    elif ledger_deuda:
        tendencia_deuda = "estable"

    return {
        "n_movimientos": len(movimientos),
        "total_ingresos": total_ingresos,
        "total_gastos_caja": total_gastos_caja,
        "total_gastos_credito": total_gastos_credito,
        "total_gastos": total_gastos,
        "tasa_ahorro": tasa_ahorro,
        "uso_credito_ratio": uso_credito_ratio,
        "categoria_top": categoria_top[0] if categoria_top else None,
        "concentracion_categoria": concentracion_categoria,
        "pct_gasto_discrecional": pct_discrecional,
        "regularidad_ingresos": regularidad_ingresos,
        "tendencia_deuda": tendencia_deuda,
        "saldo_deuda_actual": saldo_actual,
        "n_avances_credito": len(avances),
    }


def clasificar_perfil(metricas: dict) -> dict:
    """Aplica reglas explícitas -- en orden de prioridad, lo más urgente
    primero -- sobre las métricas ya calculadas para decidir un
    arquetipo, una descripción en lenguaje natural y consejos cortos.
    100% determinístico (nada de IA), así que es tan fácil de probar con
    pytest como cualquier otra función del proyecto."""
    m = metricas

    if m["n_movimientos"] == 0:
        return {
            "arquetipo": "Sin datos suficientes",
            "descripcion": (
                "Todavía no hay movimientos registrados para generar un perfil. "
                "En cuanto registres o cargues tus primeros movimientos, este panel se completa solo."
            ),
            "consejos": ["Registrá tu primer movimiento o cargá un extracto para empezar a ver tu perfil financiero."],
        }

    consejos: list[str] = []

    if m["uso_credito_ratio"] >= UMBRAL_USO_CREDITO_ALTO and m["tendencia_deuda"] == "creciente":
        arquetipo = "En alerta por deuda de tarjeta"
        descripcion = (
            f"El {m['uso_credito_ratio']*100:.0f}% de tus gastos se están cargando a tarjeta de crédito y tu saldo "
            "de deuda viene creciendo. Es el patrón que más rápido se sale de control si no se atiende."
        )
        consejos += [
            "Priorizá pagar más del mínimo de la tarjeta este mes si es posible.",
            "Evitá nuevas compras a crédito hasta que el saldo empiece a bajar.",
        ]

    elif m["total_ingresos"] == 0:
        arquetipo = "Sin ingresos registrados"
        descripcion = (
            "Tu historial solo tiene gastos -- no hay ningún ingreso real registrado todavía, "
            "así que este panel no puede calcular una tasa de ahorro real."
        )
        consejos.append("Si tenés ingresos que no se están registrando (efectivo, otra cuenta), agregalos manualmente para tener el panorama completo.")

    elif m["tasa_ahorro"] is not None and m["tasa_ahorro"] < 0:
        arquetipo = "Gastando más de lo que ingresa"
        descripcion = (
            f"Tus gastos de caja real superan tus ingresos reales (tasa de ahorro de {m['tasa_ahorro']*100:.0f}%). "
            "Vale la pena revisar qué se puede recortar antes de que dependa de crédito."
        )
        consejos.append("Revisá primero el gasto discrecional (lo no esencial) -- suele ser lo más fácil de ajustar rápido.")

    elif m["regularidad_ingresos"] is not None and m["regularidad_ingresos"] < 0.5:
        arquetipo = "Ingresos irregulares"
        descripcion = (
            "Tus ingresos no aparecen todos los meses de forma constante -- esto hace más importante tener un "
            "colchón para los meses flojos."
        )
        consejos.append("Si podés, apartá una parte de los meses con ingreso alto como fondo para los meses sin ingreso.")

    elif m["concentracion_categoria"] >= UMBRAL_CONCENTRACION and m["categoria_top"]:
        arquetipo = f"Gasto concentrado en {m['categoria_top']}"
        descripcion = (
            f'La categoría "{m["categoria_top"]}" concentra el {m["concentracion_categoria"]*100:.0f}% de tu gasto '
            "total. No es necesariamente malo, pero vale la pena confirmar que sea intencional."
        )
        consejos.append(f'Si "{m["categoria_top"]}" no es una prioridad de largo plazo, ponerle un tope mensual puede liberar bastante margen.')

    elif m["tasa_ahorro"] is not None and m["tasa_ahorro"] >= UMBRAL_AHORRO_BUENO:
        arquetipo = "Ahorrador consciente"
        descripcion = (
            f"Estás ahorrando cerca del {m['tasa_ahorro']*100:.0f}% de tus ingresos reales -- un hábito sólido "
            "comparado con el patrón más común de gastar casi todo lo que entra."
        )
        consejos.append("Con este ritmo de ahorro ya podés evaluar metas concretas (fondo de emergencia, adelantar deuda, invertir el excedente).")

    else:
        arquetipo = "Equilibrado"
        descripcion = "Tus ingresos y gastos de caja real están relativamente balanceados, sin una señal de alerta dominante en tus datos."
        consejos.append('Revisá de vez en cuando el detalle por categoría -- es la forma más simple de encontrar margen extra sin sentir que te estás "privando" de algo.')

    if m["pct_gasto_discrecional"] >= UMBRAL_DISCRECIONAL_ALTO:
        consejos.append(f"El {m['pct_gasto_discrecional']*100:.0f}% de tu gasto es discrecional (no esencial) -- es tu palanca más rápida si necesitás ajustar algo.")

    if m["n_avances_credito"] > 0:
        consejos.append("Usaste avances de efectivo de tarjeta de crédito -- suelen tener el interés más alto de todos los productos de crédito; evitalos si tenés otra opción.")

    return {"arquetipo": arquetipo, "descripcion": descripcion, "consejos": consejos[:4]}


def generar_perfil(movimientos: list[dict], ledger_deuda: list[dict] | None = None) -> dict:
    """Punto de entrada único: calcula métricas + clasifica. Es lo único
    que necesita llamar actualizar_dashboard.py para cada usuario."""
    metricas = calcular_metricas(movimientos, ledger_deuda)
    perfil = clasificar_perfil(metricas)
    perfil["metricas"] = metricas
    perfil["generado_en"] = datetime.datetime.now().isoformat(timespec="seconds")
    return perfil
