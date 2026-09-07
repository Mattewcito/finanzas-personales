# Qué se versiona en este repo, y por qué

> Repo público (`github.com/Mattewcito/finanzas-personales`). Cada archivo
> trackeado es visible para cualquiera que lo clone, para siempre (incluso
> si se borra después, sigue en el historial). Este documento justifica,
> categoría por categoría, por qué CADA archivo fuera de `src/`, `tests/`
> y `.claude/` (código y pruebas, ya evidentes) tiene sentido en un repo
> de software real -- no solo "porque no es un secreto".

Nota sobre `docs/`: hasta este archivo, la carpeta estaba vacía salvo
`docs/.gitkeep` -- confirmado con `git check-ignore -v docs/versionado.md`
(antes de este cambio, la regla `docs/*` del `.gitignore` bloqueaba
CUALQUIER archivo nuevo ahí, no solo datos). Era un placeholder sin uso
real, no una carpeta de documentación activa. Se agregó la excepción
`!docs/versionado.md` al `.gitignore` para que este archivo sí se pueda
versionar -- si a futuro se agregan más documentos técnicos, conviene
agregar cada excepción puntual (o cambiar a un patrón más permisivo) en
vez de dejar `docs/` bloqueada por accidente.

---

## 1. `.github/workflows/deploy.yml`

**Criterio:** ¿es reproducible sin él, y le sirve a cualquiera que clone el repo?

Es el pipeline de CI/CD real del proyecto: corre los tests en cada push/PR
y dispara el deploy a producción en push a `master`. Sin este archivo, la
automatización de build/test/deploy simplemente no existe -- no es
configuración de una máquina, es la definición del proceso de entrega que
cualquier colaborador necesita ver y entender (por qué el deploy solo
corre en `master`, por qué hay rollback automático, etc.). No contiene
secretos: los tokens (`GITHUB_TOKEN`, credenciales del runner) los
inyecta GitHub Actions en tiempo de ejecución, no viven en el archivo.
**Conclusión: sí se versiona.**

## 2. `.vscode/settings.json`

**Criterio:** ¿es configuración del PROYECTO (útil para cualquiera que lo abra
en ese editor) o configuración PERSONAL/de comportamiento de un asistente?

Contiene 3 líneas: la ruta de análisis de Python (`./src`, relativa, no
absoluta), qué carpetas ocultar en el explorador (`__pycache__`) y excluir
de buscar (`data/`). Es equivalente a un `.editorconfig`: cualquier
desarrollador que abra este repo en VS Code se beneficia exactamente
igual, sin decisiones de "cómo trabajar" involucradas -- es configuración
determinística y reproducible del entorno de edición.

**Por qué `.claude/agents/` NO aplica el mismo criterio:** el punto de
corte no es "¿es de una herramienta de IA?" sino "¿describe un
comportamiento/flujo de trabajo específico de una persona usando una
herramienta puntual, o configura el proyecto de forma neutral al
editor/asistente que use cada quien?". `.vscode/settings.json` no le dice
a nadie *cómo* trabajar, solo ajusta paths y exclusiones de UI.
`.claude/agents/*.md` en cambio son guiones de comportamiento completos
(personas, criterios de decisión, pipelines de varios pasos) que solo
tienen sentido si el colaborador usa exactamente Claude Code de la misma
forma que este desarrollador -- son análogos a snippets/macros
personales, no a config de proyecto. Esto es coherente con lo que ya dice
el propio `.gitignore`: `.claude/settings.json` (hooks de equipo) sí se
versiona, `.claude/agents/` (comportamiento personal del asistente) no.
**Conclusión: sí se versiona** (y el criterio que la distingue de
`.claude/agents/` es config-neutral-reproducible vs. guion de flujo de
trabajo de una persona con una herramienta específica).

## 3. `docs/.gitkeep`

**Criterio:** ¿tiene un uso real hoy, o es un placeholder vacío?

Es un placeholder sin uso real -- confirmado arriba: el `.gitignore`
(`docs/*` + solo `!docs/.gitkeep`) bloqueaba cualquier archivo que se
intentara meter ahí. No hay ninguna documentación viviendo en esa
carpeta ni referenciada desde el código o el README. **Hallazgo: mantenerla
solo por el `.gitkeep` no aporta nada -- o se usa de verdad (como se hace
ahora con este mismo archivo) o se elimina la carpeta.** Se decidió la
primera opción: agregar la excepción `!docs/versionado.md` y empezar a
usar `docs/` como el lugar real para documentación técnica que no
pertenece al `README.md` (que es de cara al usuario/onboarding) ni a notas
de decisiones de código (que van en comentarios). Si en el futuro no se
agrega ningún otro documento ahí, vale la pena reconsiderar y borrar la
carpeta entera.

## 4. `scripts/*.ps1`

**Criterio:** ¿son reproducibles en cualquier máquina, o dependen de rutas/
cuentas específicas de esta PC?

Los tres son *scripts de instalación* (se corren una vez para dejar algo
configurado en Windows: tareas programadas, el runner de CI/CD), no
código de la app -- tiene sentido que vivan en el repo porque documentan
*cómo* se configuró el entorno de producción/desarrollo, igual que un
Dockerfile documenta cómo se construye la imagen. Pero **inspeccionando
el contenido real (no solo el nombre), los tres tienen rutas absolutas
específicas de esta máquina y este usuario de Windows**, hallazgo que
señalo en vez de dar por bueno:

- `configurar_tarea_leer_correo.ps1` y `configurar_tareas_programadas.ps1`
  hardcodean `C:\Users\User\AppData\Local\Programs\Python\Python314\pythonw.exe`
  (usuario de Windows `User` + versión exacta de Python 3.14) y
  `C:\Finanzas personales\src` / `C:\Finanzas personales` como rutas
  literales.
- `instalar_runner_cicd.ps1` hardcodea `C:\actions-runner` y
  `C:\Program Files\GitHub CLI\gh.exe`.
- `configurar_tareas_programadas.ps1` además se auto-documenta como
  **OBSOLETO** desde que dev/prod corren en Docker con
  `restart: unless-stopped` -- se mantiene "como referencia" pero ya no
  es el mecanismo real en uso.

Ninguno contiene secretos (el token del runner se genera en tiempo de
ejecución vía `gh api`, no está hardcodeado). El hallazgo no es de
seguridad, es de **portabilidad/reproducibilidad**: si mañana este
proyecto corre en otra PC o con otro usuario de Windows, estos scripts
fallan o crean tareas apuntando a rutas inexistentes hasta que alguien
los edite a mano. Vale la pena documentarlo en el header de cada script
("editá estas 2 líneas si tu instalación de Python u usuario difieren")
o parametrizarlos, pero **no bloquea que sigan versionados**: siguen
siendo la referencia real y ejecutable de cómo se configuró el entorno,
más útil versionados-pero-editables que no versionados. **Conclusión: sí
se versionan, con el hallazgo de portabilidad marcado como 🟡.**

## 5. `tools/qa/playwright_utils.py`

**Criterio:** ¿es código reutilizable independiente de la herramienta que lo
invoca, o es la definición de comportamiento de un asistente puntual?

Es un módulo de Python real: funciones (`nueva_sesion`, `login`,
`hay_overflow_horizontal`, `capturar`, `crear_reporte_excel`) con lógica
de negocio propia (por qué el Dashboard vive en un iframe, cómo se arma
el Excel de bugs) que **cualquier desarrollador podría usar directamente
con `pip install -r requirements-qa.txt` y Playwright, sin Claude Code de
por medio** -- es tan código del proyecto como cualquier archivo de
`src/` o `tests/`, solo que vive en `tools/qa/` porque es tooling de QA en
vez de la app en sí.

`.claude/agents/qa-responsive.md`, en cambio, no es código: es la
instrucción en prosa de *cuándo y cómo* un agente de Claude Code debe
invocar estas funciones (criterios de severidad, cuándo reportar un bug,
el flujo de decisión completo). Es la diferencia entre una librería
(versionada, reutilizable por cualquiera) y el guion de un operador
específico de esa librería (no versionado, porque asume que quien lo lee
es Claude Code operando exactamente con ese pipeline). **Conclusión:
`playwright_utils.py` sí se versiona.**

## 6. El resto

**`Dockerfile`** -- define de forma determinística cómo se construye la
imagen (base `python:3.12-slim`, timezone, deps, `gunicorn --preload`).
Sin él nadie puede reproducir el contenedor. Ninguna ruta ni dato
específico de esta PC. **Sí se versiona.**

**`docker-compose.yml`** -- define cómo se orquesta el contenedor
(volúmenes relativos `./data`, `./dashboard`, política de reinicio). A
propósito NO tiene puertos fijos ni nombres de contenedor específicos de
máquina -- eso vive en `docker-compose.override.yml`, que sí está
correctamente excluido en `.gitignore` (comentario propio: "rutas
absolutas, nombres de contenedor -- nunca deben subirse"). Buena
separación ya existente entre lo genérico (versionado) y lo específico de
cada entorno (no versionado). **Sí se versiona.**

**`requirements.txt` / `requirements-dev.txt` / `requirements-qa.txt`** --
tres archivos separados a propósito, cada uno con una razón distinta
confirmada leyendo su contenido:
- `requirements.txt`: dependencias de producción de la app
  (Flask, openpyxl, pdfplumber, cryptography, werkzeug) -- lo que se
  instala dentro de la imagen Docker real.
- `requirements-dev.txt`: `-r requirements.txt` + `pytest` -- entorno de
  CI/tests (usado explícitamente en `deploy.yml`, job `test`). Separado
  para no meter `pytest` en la imagen de producción.
- `requirements-qa.txt`: solo `playwright`, deliberadamente aislado
  porque descarga un binario de navegador de ~150-300MB que no tiene
  ningún motivo para viajar en la imagen Docker (ver comentario propio en
  el archivo) -- se instala una sola vez en la máquina que corre QA
  responsive, nunca en el contenedor.

Los tres son manifiestos de dependencias reproducibles (no rutas ni
secretos), cada uno resuelve un entorno distinto real. **Los tres se
versionan.**

**`README.md`** -- onboarding estándar de cualquier repo público: qué es
el proyecto, estado actual, cómo se usa. Le sirve a cualquiera que lo
clone sin contexto previo. **Sí se versiona.**

**`CLAUDE.md`** -- a diferencia de `.claude/agents/*.md`, este archivo no
es un guion de comportamiento de agentes; codifica reglas de PROCESO real
del proyecto (cuándo se puede pushear a `dev` vs. `master`, separación de
entornos dev/prod, qué nunca tocar en producción) que cualquier humano
que colabore necesita conocer, equivalente a un `CONTRIBUTING.md`. Que su
nombre esté pensado para que Claude Code lo lea automáticamente no lo
vuelve config personal -- el contenido es política de equipo legible por
cualquiera. **Sí se versiona.**

**`.gitignore` / `.dockerignore`** -- son, literalmente, la definición de
qué NO debe viajar a git ni a la imagen; necesarios para que cualquier
colaborador nuevo entienda (y respete) esas reglas sin tener que
descubrirlas por prueba y error. **Se versionan.**

**`iniciar_app.bat`** -- usa `%~dp0` (ruta relativa a la ubicación del
propio script) y detecta si existe `py` o `python`, sin ninguna ruta
absoluta ni específica de usuario. Funciona igual en cualquier Windows
donde se clone el repo. **Sí se versiona.**

**`dashboard/dashboard_finanzas.html`** -- es el frontend real de la app
(la página que consume `GET /api/dashboard-data`), no un dato ni un
artefacto generado -- se monta como volumen en `docker-compose.yml` para
poder editarlo sin reconstruir la imagen, pero eso es una decisión de
despliegue, no cambia que sea código fuente del producto. Sin él, la ruta
`/vista/dashboard` no tiene nada que servir. **Sí se versiona**, con el
mismo criterio que `src/`.

---

## Principio general

Se versiona lo que es **reproducible y neutral a la máquina/persona que
lo ejecuta, y que cualquier colaborador (humano, sin depender de una
herramienta de IA en particular) necesita para construir, correr, testear
o desplegar el producto** -- código, configuración de build/CI/editor
determinística, dependencias declaradas y documentación de proceso. NO se
versiona lo que es **específico de una máquina/usuario** (rutas de
usuario de Windows, overrides de Docker), **un dato real** (finanzas,
credenciales, claves), o **el guion de comportamiento de un asistente de
IA operado por una persona puntual** (`.claude/agents/`) -- esto último
porque no ayuda a nadie que no use esa herramienta exactamente de la
misma forma, a diferencia del código o la config de proyecto genuina que
sí reutiliza cualquiera.
