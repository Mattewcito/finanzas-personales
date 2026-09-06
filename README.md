# Finanzas Personales

Sistema personal para organizar ingresos, gastos y deuda de tarjetas de
crédito, con foco en salir de deudas y automatizar el registro de
movimientos. Todo corre **local** — la base de datos y el dashboard no
dependen de internet para funcionar. Las fuentes de datos (lectura de
correo, extractos bancarios) sí pueden usar internet, pero son
reemplazables/opcionales por diseño.

## Estado actual

- ✅ **Fase 0 — Base de datos real**: los datos viven en `data/finanzas.db`
  (SQLite), no en el Excel. El Excel es un canal de ingesta EN
  TRANSICIÓN hacia salida (`src/actualizar_dashboard.py` lo sincroniza
  a la BD solo si sigue existiendo -- si no, no hace nada): el bot
  externo de Gmail que lo escribía se está reemplazando por
  `leer_correo.py`, que ya inserta directo a la BD.
- ✅ **Dashboard dinámico**: el dashboard (`dashboard/dashboard_finanzas.html`)
  es un único archivo estático que le pide sus datos a
  `GET /api/dashboard-data` al cargar, respetando la sesión (y, si sos
  admin, la cuenta que estés viendo). Ya no hay "regenerar" ni archivos
  HTML por usuario en disco -- cualquier cambio en la BD se ve apenas
  se recarga la página.
- ✅ **Fase 1 — Ingesta local de correo, configurable desde la interfaz**
  (`src/leer_correo.py` + `src/routes/correo.py`): lee las notificaciones
  de Bancolombia directo de Gmail por IMAP (contraseña de aplicación, no
  navegador automatizado — Google bloquea logins por navegador
  controlado), las parsea con expresiones regulares (sin IA) y las
  inserta en la base de datos con dedup por (fecha, monto). Cada persona
  configura su propio correo dedicado desde el menú **"Correo
  automático"** (incluye una guía paso a paso en un popup de ayuda) — sin
  tocar archivos ni la terminal. Ahí mismo cada quien elige cada cuánto
  se sincroniza (cada X minutos, o una vez al día a una hora fija), puede
  pausarlo, probarlo (vista previa sin insertar nada) o forzar una
  sincronización inmediata. Una sola tarea programada procesa todas las
  cuentas activas en cada corrida, cada una asignada a su usuario y
  aislada de las demás (si una falla, no detiene a las otras). Cubre
  compras (débito/crédito), QR, transferencias, Bre-B, nómina y avances
  de tarjeta. Corre sola cada 5 min vía la tarea programada
  "FinanzasLeerCorreo" (`scripts/configurar_tarea_leer_correo.ps1`, cada
  cuenta respeta su propia frecuencia igual — ver "Configurar la lectura
  de correo" abajo), con su propio log (`data/leer_correo.log`). **Nu
  queda pendiente** (solo manda extractos mensuales, no alertas por
  movimiento — se sigue cubriendo con `reconciliar_extractos.py`).
- ✅ **App con interfaz** (`src/app.py`, blueprints en `src/auth.py` y
  `src/routes/`): servidor Flask con menú lateral colapsable — Dashboard
  (embebido, dinámico) y Cargar extractos (subir Excel/PDF desde el
  navegador, se inserta con dedup, visible al instante).
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
  vez que el dashboard pide sus datos, se clasifica a ese usuario en un
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
Excel, mientras siga activo (`C:\Finanzas personales\data`) -- vía
montajes de archivo individuales en el `docker-compose.override.yml` de
`finanzas-deploy` (no se sube a git, es específico de esta máquina). El
dashboard ya es dinámico (lee la BD por API, no hay ningún HTML
generado que compartir), así que lo que se ve en producción (5002)
siempre refleja el código de `master`, nunca lo que se esté probando en
la carpeta de trabajo (5001) -- ambas leen la misma BD, cada una con su
propia versión del código.

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
│   │   ├── usuarios.py          # blueprint: alta/edición de cuentas, editar el propio perfil
│   │   └── correo.py            # blueprint: configurar la lectura automática de correo (propia cuenta)
│   ├── db_finanzas.py           # esquema, clasificación de movimientos, sincronización, consultas
│   ├── perfil_financiero.py     # clasifica a cada usuario en un arquetipo de hábitos + consejos
│   ├── actualizar_dashboard.py  # sincroniza finanzas.db desde el Excel, mientras siga activo
│   ├── migrar_a_sqlite.py       # migración/reset puntual de la base de datos
│   ├── crear_usuario.py         # alta de cuentas por línea de comandos
│   ├── leer_correo.py           # ingesta de notificaciones bancarias por Gmail/IMAP (config en la tabla correo_config)
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
Tarea de Windows "FinanzasLeerCorreo" (cada 5 min)
   -> corre src/leer_correo.py --aplicar
      -> lee correo_config (tabla en finanzas.db) y descarta las cuentas
         a las que todavía no les toca según SU frecuencia configurada
      -> para cada cuenta que sí le toca: lee por IMAP su correo dedicado
      -> parsea cada alerta de Bancolombia (regex, sin IA)
      -> inserta directo en data/finanzas.db (dedup por fecha+monto)
En cualquier momento, al abrir el dashboard:
   -> el navegador pide GET /api/dashboard-data
      -> Flask consulta finanzas.db (ya enriquecida: medio de pago, deuda)
      -> devuelve movimientos + ledger de deuda + perfil financiero, siempre al día
```

Ruta vieja, en transición hacia salida (solo mientras el Excel siga
activo -- ver "Configurar la lectura de correo" arriba):

```
Gmail (bot externo) -- escribe data/finanzas_personales.xlsx
Tarea de Windows "ActualizarDashboardFinanzas"
   -> corre src/actualizar_dashboard.py -> sincroniza el Excel a finanzas.db
```

Una vez que `leer_correo.py` cubra a todos los usuarios y se borre el
Excel, tanto `actualizar_dashboard.py` como esa tarea programada y el
bot externo de Gmail dejan de tener trabajo que hacer -- se pueden borrar.

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
py actualizar_dashboard.py  # sincroniza finanzas.db desde el Excel (si sigue activo)
```

## Configurar la lectura de correo (Fase 1)

**Multiusuario, autoservicio desde la interfaz:** cada persona de la
casa tiene (o puede tener) su propio correo Gmail **dedicado solo a
notificaciones bancarias** (no su correo personal), y sus movimientos
quedan SOLO en su propia cuenta de Finanzas Personales — nunca mezclados
con los de otro. No hace falta editar ningún archivo ni usar la
terminal: cada quien entra a su cuenta y configura la suya desde el menú
**"Correo automático"**.

Esa página tiene un botón **"❓ Cómo configurar esto, paso a paso"** con
la guía completa (crear el correo dedicado, cambiar el correo de
notificaciones en Bancolombia, activar verificación en 2 pasos y generar
la contraseña de aplicación en
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
Una vez con esos datos a mano:

1. Completá correo dedicado + contraseña de aplicación (16 caracteres,
   con o sin espacios) en el formulario.
2. Elegí cuándo sincronizar: **"cada N minutos"** o **"una vez al día a
   una hora fija"**.
3. Usá **"Probar conexión"** — conecta por IMAP y muestra una vista
   previa de lo que encontraría, sin insertar nada todavía.
4. Si se ve bien, **"Guardar cambios"**. Desde ahí podés además
   **"Sincronizar ahora"** (fuerza una corrida inmediata, sin esperar a
   la frecuencia elegida), pausarlo (checkbox "Automatización activa",
   sin perder la configuración) o eliminarlo del todo.

Toda esta configuración (correo, contraseña de aplicación, host/puerto
IMAP, frecuencia, y el resultado de la última corrida) vive en la tabla
`correo_config` de `data/finanzas.db` — una fila por usuario, nunca
visible entre cuentas ni siquiera para un admin "viendo" otro perfil (la
página siempre opera sobre la cuenta con la que se inició sesión). La
contraseña de aplicación se guarda en texto plano ahí (no se puede
hashear: `leer_correo.py` necesita el valor real para conectarse por
IMAP) — mismo nivel de confianza que ya tenía el archivo local que
existía antes de esta página; la interfaz nunca la vuelve a mostrar una
vez guardada.

**Automatizarlo** (para que corra solo, sin tener que apretar
"Sincronizar ahora" cada vez): corré una única vez
`scripts/configurar_tarea_leer_correo.ps1` — crea la tarea programada de
Windows "FinanzasLeerCorreo", que revisa cada 5 minutos todas las
cuentas activas y procesa solo las que ya les toca según SU PROPIA
frecuencia (el intervalo corto de la tarea es solo para que esa
frecuencia elegida se respete de verdad; no hace que se sincronice más
seguido de lo configurado). No hace falta volver a tocar este script
cuando alguien agrega o cambia su configuración desde la web. Cada
corrida deja renglones en `data/leer_correo.log`, etiquetados por
usuario.

La categoría de cada compra se asigna por palabras clave en el nombre del
comercio (sin IA) — es un mejor esfuerzo. Se puede corregir directamente
en la base de datos; no afecta los totales de ingreso/gasto/deuda.

## Seguridad

`data/` y `docs/` están en `.gitignore` — nunca se suben a GitHub.
Ninguna credencial (API keys, contraseñas de correo) va escrita en texto
plano en el código: siempre por variable de entorno, archivo local
ignorado por git, o (la contraseña de aplicación de cada quien, desde
2026-09-06) en `data/finanzas.db` — mismo archivo local fuera de git que
ya guarda el resto de los datos, nunca expuesta de vuelta en la interfaz
una vez guardada.

