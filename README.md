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
- ✅ **Dashboard responsive**: navegación adaptada a celular/tablet.
- ✅ **Cuentas de usuario**: acceso con usuario/contraseña, datos
  aislados por cuenta. Ver `src/crear_usuario.py` para dar de alta cuentas.
- ✅ **Despliegue automático**: cada push a `master` reconstruye y
  levanta el contenedor Docker solo, vía un runner de GitHub Actions
  instalado en esta misma PC (ver `.github/workflows/deploy.yml` y
  "Despliegue automático" abajo).
- ✅ **Perfil financiero por hábitos** (`src/perfil_financiero.py`): cada
  vez que se regenera el dashboard, se clasifica a cada usuario en un
  arquetipo (ahorrador, en alerta por deuda, ingresos irregulares, etc.)
  a partir de TODO su historial, con una descripción y consejos
  generados automáticamente por reglas (no IA). Se muestra en la sección
  "Tu perfil financiero" del dashboard.
- ✅ **Gráficos expandibles**: click en cualquier gráfico (o en el
  ranking de Top 5 categorías) para verlo en grande con una tabla de
  detalle debajo.
- 🔜 **Fase 2 — Documentos y DIAN**: guardar y vincular facturas,
  extractos y contratos a los movimientos.
- 🔜 **Fase 3 — Dashboard v2**: planificador de pago de deuda,
  presupuestos por categoría.

## Cómo se corre día a día

Dos carpetas, dos contenedores Docker, cada uno en su puerto -- ambos
siempre arriba (Docker los reinicia solo si se caen o si reiniciás la PC,
gracias a `restart: unless-stopped`):

| Carpeta | Contenedor | Puerto | Para qué |
|---|---|---|---|
| `C:\Finanzas personales` (esta, donde editás código) | `finanzas-app-dev` | 5001 | Probar cambios antes de subirlos |
| `C:\finanzas-deploy` (dedicada, nunca se edita a mano) | `finanzas-app-online` | 5002 | Versión estable, accesible por Tailscale |

Las dos comparten **solo la fuente real de datos** -- `finanzas.db` y el
Excel que escribe el bot de Gmail (`C:\Finanzas personales\data`) -- vía
montajes de archivo individuales en el `docker-compose.override.yml` de
`finanzas-deploy` (no se sube a git, es específico de esta máquina). El
dashboard generado (`dashboard_<id>.html`), el log y los uploads son
LOCALES a cada carpeta: cada una los regenera con su propio código, así
que lo que se ve en producción (5002) siempre es lo que ya está en
`master`, nunca algo que se esté probando en la carpeta de trabajo
(5001). `finanzas-deploy` regenera los suyos automáticamente después de
cada deploy (paso agregado en `.github/workflows/deploy.yml`); esta
carpeta lo hace vía la tarea programada diaria o corriendo
`actualizar_dashboard.py` a mano.

Para levantar/reconstruir cualquiera de las dos a mano:
```bash
cd "C:\Finanzas personales"   # o cd "C:\finanzas-deploy"
docker compose up -d --build
```

Para usar la versión online desde el celular: instalá la app de Tailscale
(App Store / Play Store), iniciá sesión con la misma cuenta que usaste en
la PC, y entrá a `http://<ip-de-tailscale-de-tu-pc>:5002` (la IP la ves
corriendo `tailscale ip -4` en la PC, o en la app de Tailscale).

## Pruebas automáticas y despliegue automático

El pipeline (`.github/workflows/deploy.yml`) tiene 2 pasos:

1. **`test`** -- corre en la nube de GitHub (gratis) en cada push y en
   cada Pull Request: instala dependencias y corre `pytest` (`tests/`).
   Cubre la clasificación caja-real/deuda, los parsers de notificaciones
   de Bancolombia, y la app (login, permisos, aislamiento de datos entre
   usuarios). Si algo falla acá, el PR queda marcado con una ❌ y el
   despliegue **no se ejecuta**.
2. **`deploy`** -- solo corre si `test` pasó Y el push fue directo a
   `master` (no en PRs). Se ejecuta en el runner instalado en esta PC:
   actualiza `C:\finanzas-deploy` y reconstruye el contenedor. Si después
   de desplegar el contenedor no responde bien (`/health`), el pipeline
   **revierte solo** al commit anterior y reconstruye con esa versión --
   así un despliegue roto no te deja sin dashboard.

Correr las pruebas a mano:
```bash
py -m pip install -r requirements-dev.txt
pytest -v
```

Cómo funciona el runner: hay un [runner de GitHub Actions](https://docs.github.com/actions/hosting-your-own-runners)
instalado como servicio de Windows en esta misma PC (`C:\actions-runner`).
GitHub le avisa a ese servicio cuando hay un push (conexión saliente, no
hace falta abrir ningún puerto), y el paso de despliegue corre sobre
`C:\finanzas-deploy` -- nunca sobre la carpeta de trabajo, para no pisar
nada que estés probando ahí.

Instalación (una sola vez):
1. `git clone` este repo en `C:\finanzas-deploy` (carpeta dedicada, aparte
   de donde trabajás normalmente).
2. Crear ahí su propio `docker-compose.override.yml` (puerto 5002,
   apuntando a la base de datos real de `C:\Finanzas personales\data`).
3. `scripts/instalar_runner_cicd.ps1` **como administrador** -- instala el
   runner como servicio de Windows para que quede corriendo siempre,
   incluso después de reiniciar la PC.

Para ver el estado o los logs de las corridas: pestaña "Actions" del
repositorio en GitHub.

## Estructura

```
Finanzas personales/
├── data/                        # NUNCA se sube a git — información real
│   ├── finanzas_personales.xlsx #   Excel fuente (lo escribe el bot de correo)
│   └── finanzas.db              #   base de datos SQLite (fuente de verdad para el dashboard)
├── dashboard/
│   └── dashboard_finanzas.html  # plantilla del dashboard (sin datos), versionada en git
├── src/
│   ├── app.py                   # raíz de la app Flask: crea el objeto Flask y registra los blueprints
│   ├── auth.py                  # blueprint de autenticación (login/logout/cambiar de perfil)
│   ├── routes/
│   │   ├── dashboard.py         # blueprint: ver el dashboard, registrar movimientos, cargar extractos
│   │   └── usuarios.py          # blueprint: alta/edición de cuentas, editar el propio perfil
│   ├── db_finanzas.py           # esquema, clasificación de movimientos, sincronización, consultas
│   ├── perfil_financiero.py     # clasifica a cada usuario en un arquetipo de hábitos + consejos
│   ├── actualizar_dashboard.py  # corre a diario: sincroniza + regenera el dashboard de cada usuario
│   ├── migrar_a_sqlite.py       # migración/reset puntual de la base de datos
│   ├── crear_usuario.py         # alta de cuentas por línea de comandos
│   ├── leer_correo.py           # ingesta local de notificaciones bancarias por Gmail/IMAP
│   ├── templates/                # plantillas Jinja de la interfaz (login, registrar, cargar extractos, etc.)
│   └── tools/
│       └── reconciliar_extractos.py  # parseo de extractos PDF -> movimientos, con dedup por (fecha, monto)
├── tests/                        # pytest: clasificación, parsers de correo, integración de la app
├── docs/                        # (futuro) facturas, extractos, contratos escaneados — NUNCA se sube a git
└── requirements.txt
```

Patrón de diseño: **Flask Blueprints** -- cada área del producto (auth,
dashboard, usuarios) vive en su propio archivo/blueprint en vez de tener
todas las rutas en un único `app.py`; `app.py` queda como raíz delgada
que solo arma la app y los registra. Ver la cabecera de `src/app.py` y
`src/auth.py` para el detalle de qué vive en cada uno.

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

