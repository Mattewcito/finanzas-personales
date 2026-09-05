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
- ✅ **App con interfaz** (`src/app.py`): servidor Flask con menú lateral
  colapsable — Dashboard (embebido) y Cargar extractos (subir Excel/PDF
  desde el navegador, se inserta con dedup y regenera el dashboard solo).
- ✅ **Docker + Tailscale**: la app corre dockerizada (puerto 5002,
  `docker-compose.yml`) para poder verla desde el celular/tablet estando
  fuera de casa, **sin exponerla a internet público** — el acceso es vía
  [Tailscale](https://tailscale.com) (red privada gratuita entre tus
  propios dispositivos). Se evaluó exposición pública real (dominio +
  HTTPS + login) pero se descartó: muchos ISPs residenciales usan CGNAT
  (no dan IP pública) y expondría la PC a internet sin necesidad, cuando
  Tailscale da el mismo resultado sin ese riesgo.
- 🔜 **Dashboard responsive**: falta adaptar el layout para pantallas de
  celular/tablet (hoy está pensado para escritorio).
- 🔜 **Fase 2 — Documentos y DIAN**: guardar y vincular facturas,
  extractos y contratos a los movimientos.
- 🔜 **Fase 3 — Dashboard v2**: planificador de pago de deuda,
  presupuestos por categoría.

## Cómo se corre día a día

Dos versiones corriendo en paralelo, cada una en su puerto:

| | Comando | Puerto | Alcance |
|---|---|---|---|
| Desarrollo (probar cosas nuevas) | `iniciar_app.bat` o tarea `FinanzasDev` | 5001 | Solo esta PC (`127.0.0.1`) |
| Estable (Docker) | `docker compose up -d` o tarea `FinanzasDocker` | 5002 | Esta PC + cualquier dispositivo con Tailscale |

Ambas tareas programadas (`FinanzasDev`, `FinanzasDocker`) se crean una
sola vez corriendo `scripts/configurar_tareas_programadas.ps1` **como
administrador** (clic derecho → Ejecutar con PowerShell, o desde una
PowerShell elevada) — de ahí en más arrancan solas al iniciar sesión en
Windows. Ese script también abre el puerto 5002 en el firewall (el 5001
queda cerrado a propósito, solo local).

Para usar la versión Docker desde el celular: instalá la app de Tailscale
(App Store / Play Store), iniciá sesión con la misma cuenta que usaste en
la PC, y entrá a `http://<ip-de-tailscale-de-tu-pc>:5002` (la IP la ves
corriendo `tailscale ip -4` en la PC, o en la app de Tailscale).

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
