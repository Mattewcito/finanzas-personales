# Finanzas Personales

Sistema personal para organizar ingresos, gastos y deuda de tarjetas de
crédito, con foco en salir de deudas y automatizar el registro de
movimientos. Todo corre **local** — la base de datos y el dashboard no
dependen de internet para funcionar. Las fuentes de datos (lectura de
correo, extractos bancarios) sí pueden usar internet, pero son
reemplazables/opcionales por diseño.

## Estado actual

- ✅ **Fase 0 — Base de datos real**: los datos viven en `data/finanzas.db`
  (SQLite), no en el Excel. El Excel se mantiene como fuente de entrada
  (todavía es lo único que actualiza el bot de lectura de correo viejo) y
  se sincroniza automáticamente a la base de datos cada vez que se
  regenera el dashboard.
- 🚧 **Fase 1 — Ingesta local de correo** (`src/leer_correo.py`): lee las
  notificaciones de Bancolombia directo de Gmail por IMAP (contraseña de
  aplicación, no navegador automatizado — Google bloquea logins por
  navegador controlado), las parsea con expresiones regulares (sin IA) y
  las inserta en la base de datos con dedup por (fecha, monto). Cubre
  compras (débito/crédito), QR, transferencias, Bre-B, nómina y avances
  de tarjeta. **Nu queda pendiente** (solo manda extractos mensuales, no
  alertas por movimiento — se sigue cubriendo con `reconciliar_extractos.py`).
  Ver "Configurar la lectura de correo" abajo.
- 🔜 **Fase 2 — Documentos y DIAN**: guardar y vincular facturas,
  extractos y contratos a los movimientos.
- 🔜 **Fase 3 — Dashboard v2**: planificador de pago de deuda,
  presupuestos por categoría.

## Estructura

```
Finanzas personales/
├── data/                        # NUNCA se sube a git — información real
│   ├── finanzas_personales.xlsx #   Excel fuente (lo escribe el bot de correo)
│   └── finanzas.db              #   base de datos SQLite (fuente de verdad para el dashboard)
├── dashboard/
│   └── dashboard_finanzas.html  # dashboard offline, abrir con doble clic
├── src/
│   ├── db_finanzas.py           # esquema, clasificación de movimientos, sincronización, consultas
│   ├── actualizar_dashboard.py  # corre a diario: sincroniza + regenera el dashboard
│   ├── migrar_a_sqlite.py       # migración/reset puntual de la base de datos
│   └── tools/
│       └── reconciliar_extractos.py  # parseo de extractos PDF -> Excel, con dedup por (fecha, monto)
├── docs/                        # (futuro) facturas, extractos, contratos escaneados — NUNCA se sube a git
└── requirements.txt
```

## Cómo funciona el flujo diario

```
Gmail (tarea externa, 8:00 AM)
   -> escribe data/finanzas_personales.xlsx
Tarea de Windows "ActualizarDashboardFinanzas" (9:30 AM)
   -> corre src/actualizar_dashboard.py
      -> sincroniza el Excel a data/finanzas.db
      -> consulta la base de datos ya enriquecida (medio de pago, deuda)
      -> regenera dashboard/dashboard_finanzas.html
```

## Modelo de datos: caja real vs. deuda de tarjeta

Cada movimiento se clasifica automáticamente por patrones de texto en la
descripción (ej. "T.Cred", "T.Deb", "Avance") en:

- `debito` — gasto real de caja (débito, efectivo, transferencias)
- `credito` — compra a tarjeta de crédito: es deuda nueva, **no** sale de
  la cuenta todavía
- `avance_credito` — adelanto de efectivo de la tarjeta: entra a la
  cuenta pero es deuda, no ingreso real
- `pago_tarjeta_credito` — pago que abona la tarjeta: sí es caja real

Esto evita mezclar "cuánto gasté" con "cuánta deuda adquirí", que era el
problema original que descuadraba el dashboard.

> ⚠️ La clasificación es una herramienta de organización personal, no
> asesoría tributaria. Antes de usar estos números para declarar renta,
> verificalos con tu contador.

## Cómo correr algo a mano

Requiere Python 3.11+ y las dependencias de `requirements.txt`:

```bash
py -m pip install -r requirements.txt
cd src
py migrar_a_sqlite.py       # sincroniza/verifica la base de datos
py actualizar_dashboard.py  # sincroniza + regenera el dashboard
```

## Configurar la lectura de correo (Fase 1)

1. Activá verificación en 2 pasos en tu cuenta de Google (si no la tenés).
2. Generá una contraseña de aplicación en
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   (elegí "Otra" y ponele un nombre como "Finanzas IMAP").
3. Copiá `data/credenciales_correo.example.json` a `data/credenciales_correo.json`
   y completá tu correo y esa contraseña (16 caracteres, con o sin espacios).
   Ese archivo **nunca se sube a git** — vive en `data/`.
4. Probá primero en modo reporte (no escribe nada):
   ```bash
   cd src
   py leer_correo.py --dias 30
   ```
5. Si los movimientos que muestra son correctos, aplicá:
   ```bash
   py leer_correo.py --dias 30 --aplicar
   ```

La categoría de cada compra se asigna por palabras clave en el nombre del
comercio (sin IA) — es un mejor esfuerzo. Se puede corregir directamente
en la base de datos; no afecta los totales de ingreso/gasto/deuda.

## Seguridad

`data/` y `docs/` están en `.gitignore` — nunca se suben a GitHub.
Ninguna credencial (API keys, contraseñas de correo) va escrita en texto
plano en el código: siempre por variable de entorno o archivo local
ignorado por git.
