# Llevar la app al nivel de Lukas -- con foco móvil, sin perder la web

## Veredicto
**Revisado, con ajustes** (2026-09-18). Respondiste los cuatro puntos y
el plan quedó ajustado abajo (ver "Tus respuestas"). Sigue en pausa
hasta que elijas cómo se instala la app -- es lo único que falta
decidir para arrancar la Fase 1.

Lo único que ya se construyó es el primer punto de la Fase 1 (que la app
se pueda instalar en el celular, ver abajo). Vive en la rama
`lukas/fase-1-pwa`, **sin mezclar a `dev` ni a producción**: si el plan
cambia, se descarta sin tocar nada de lo que ya funciona.

Es el pedido más grande hasta ahora: no es una funcionalidad, es la
dirección del producto. Por eso va en fases, cada una usable por sí
sola, en vez de meses sin ver nada.

La mayor parte de lo que hace Lukas se puede construir. Una parte NO,
porque depende de ser una app nativa de iPhone -- abajo está explicado
cuál y por qué. Y hay un punto que es decisión tuya antes de la Fase 2:
cómo se resuelve la "inteligencia" para registrar gastos hablando o
escribiendo, porque la regla del proyecto es usar solo herramientas
gratuitas.

## Tus respuestas (2026-09-18) y cómo cambian el plan

**1. "¿Cómo se instalará? ¿App Store, Play Store, ambas?"**
Por defecto, **ninguna de las dos tiendas**: se instala desde el
navegador del celular, gratis. Ver "Cómo se instala" más abajo, con las
opciones de tienda y lo que cuesta cada una. *Falta tu decisión.*

**2. "No usaremos la IA, no aún."**
La Fase 2 queda en pausa salvo las etiquetas con #, que no usan IA.
Dictar por voz, sacarle foto a la factura, escribirlo "como hablás" y
"aprende de vos" esperan a que decidas retomarla.

**3. "Más que presupuesto, diría alertas de límite por categorías."**
La Fase 3 cambia de enfoque: ya no es un presupuesto por categoría, son
**límites por categoría con aviso** -- ponés "Restaurantes: $400.000 al
mes" y la app te avisa cuando vas por el 80% y cuando te pasaste. Sale
"exportar presupuesto a PDF" (no hay presupuesto que exportar), y
"seguro para gastar" pasa a "más adelante".

**4. "Pagos programados, solo si hay notificaciones al celular con días
de anticipación."**
La Fase 4 queda condicionada a eso, y es viable gratis (ver
"Notificaciones al celular" abajo): un aviso tipo *"En 3 días vence el
arriendo, $1.200.000"*, con cuántos días antes lo elegís vos.

**Consecuencia importante de 3 y 4:** las alertas de límite y los
recordatorios de pago necesitan **notificaciones al celular**, y eso a
su vez necesita dos cosas: que la app esté **instalada** (Fase 1) y que
se sirva por **HTTPS** (el Cloudflare Tunnel que ya estaba pendiente de
infraestructura). Así que el HTTPS deja de ser un "algún día" y pasa a
ser el primer paso.

### Cómo se instala

| Camino | Cómo | Costo | Comentario |
|---|---|---|---|
| **Desde el navegador** *(recomendado)* | iPhone: Safari → Compartir → "Agregar a pantalla de inicio". Android: Chrome muestra "Instalar app" | Gratis | Queda con ícono propio y a pantalla completa, como cualquier app. Se actualiza sola al instante, sin pasar por ninguna tienda. |
| **Play Store** | Se empaqueta la misma app web (Trusted Web Activity, con Bubblewrap, que es gratuito) | US$25 una sola vez (cuenta de desarrollador de Google) | Viable. Rompe la regla de "solo gratuito" por ese pago único: decisión tuya. |
| **App Store** | Hace falta una envoltura nativa | US$99 **por año** (Apple Developer) | No recomendado: además del costo, Apple suele rechazar apps que son "solo un sitio web adentro" (regla 4.2 de "funcionalidad mínima"). |

Las tres opciones son **la misma app y el mismo código**: elegir una
tienda más adelante no obliga a rehacer nada.

### Notificaciones al celular
Son las notificaciones push estándar de la web ("Web Push"): no pasan
por ninguna tienda y se envían con herramientas gratuitas (`pywebpush`,
código abierto; los servicios de push de Google y Apple no cobran).

- **Android:** funcionan en Chrome.
- **iPhone:** funcionan desde iOS 16.4, **solo si la app está agregada a
  la pantalla de inicio** -- en Safari común no llegan. Es una regla de
  Apple, no nuestra.
- En los dos casos hace falta HTTPS.

## De dónde sale esto
Nos mostraste Lukas (App Store Colombia, 4,9 estrellas, "control de
gastos") como la referencia de lo que querés que sea la app. Lo
revisamos entero: su propuesta es que registrar un gasto cueste casi
cero esfuerzo -- dictarlo, sacarle foto a la factura, escribirlo como
si fuera un chat -- y que el presupuesto te frene ANTES de pasarte, no
que te cuente después que te pasaste.

La diferencia que pediste: el foco es el celular, pero la web sigue
siendo el lugar para ver el dashboard con calma y para administrar.
Lukas es solo iPhone; esta app es las dos cosas.

## Qué ya tenemos y Lukas NO tiene (las "grandes diferencias")
Esto no se toca, es la ventaja:

- **Importación automática desde el correo de tu banco.** Lukas no
  integra ningún banco colombiano; acá los movimientos entran solos
  desde las alertas de Bancolombia. Es su "registrar sin abrir la app",
  pero mejor, porque no depende de pagar con Apple Pay.
- **Extractos bancarios en PDF**, de ahorros y de tarjeta, con la
  cédula para desbloquearlos.
- **Tarjetas de crédito con cupo, deuda y conciliación** contra el
  extracto oficial.
- **Multiusuario con administración** (familia, perfiles, visibilidad
  de vistas). Lukas es de una sola persona.
- **Dashboard web completo**, presupuesto por baldes 50/30/20 y perfil
  financiero.

## Lo que Lukas tiene y vamos a construir

### Fase 1 -- Que se sienta como una app en el celular
*Sin decisiones pendientes. El primer punto ya está hecho en la rama
`lukas/fase-1-pwa`; el resto espera tu revisión.*

- **Instalable en la pantalla de inicio** (PWA): se abre a pantalla
  completa, sin la barra del navegador, con su ícono. Al mantener
  presionado el ícono aparece "Registrar gasto" -- el equivalente web
  al widget de registro rápido de Lukas.
- **Modo privado**: ocultar los montos con un toque, para abrir la app
  en público sin mostrar cuánta plata tenés.
- **Exportar movimientos a CSV**, con la fecha local correcta (Lukas lo
  menciona explícitamente; nosotros acabamos de tener justo ese bug con
  el horario de la noche).
- **Registros frecuentes**: un toque para cargar el café, el pasaje o el
  almuerzo de siempre.
- *(Ya en curso en otra sesión: editar y borrar un movimiento.)*

### Fase 2 -- Registrar sin fricción
*En pausa: decidiste no usar IA por ahora. Solo sigue vivo lo que no la
necesita (las etiquetas con #).*

- **Escribirlo como hablás**: "almuerzo 25 lucas ayer con nequi" y la
  app entiende monto, fecha, categoría y medio de pago. Con el
  vocabulario de acá: lucas, palos, mil, ayer, anteayer, el lunes.
- **Dictarlo por voz**, y pasa por el mismo intérprete.
- **Aprende de vos**: sugiere la categoría según lo que ya cargaste
  antes con palabras parecidas, y mejora cuando la corregís.
- **Foto de la factura**: lee el total y el comercio. Honestamente, con
  herramientas gratuitas la calidad en facturas arrugadas o térmicas es
  limitada; lo vamos a presentar como ayuda, no como magia.
- **Etiquetas con #**, para filtrar después ("#viaje-cartagena").

### Fase 3 -- Alertas de límite por categoría
*Ajustada a tu respuesta: límites con aviso, no un presupuesto.*
- **Un límite por categoría** ("Restaurantes: $400.000 al mes"),
  independiente de los baldes 50/30/20, que siguen como están.
- **Aviso al 80% y aviso al pasarte**, en la app y como notificación al
  celular.
- **Ciclo mensual o quincenal**: acá la mayoría cobra por quincena.
- *Más adelante, si lo querés:* "seguro para gastar" (cuánto te queda
  hoy/esta semana sin pasarte de ningún límite).

### Fase 4 -- Pagos programados
*Condicionada a tu respuesta: solo con recordatorio al celular.*
- **Recordatorio al celular N días antes** de cada pago (vos elegís
  cuántos): "En 3 días vence el arriendo, $1.200.000".
- Gastos e ingresos que se repiten (arriendo, suscripciones, nómina
  quincenal) con confirmación cuando llegan.
- **Detección automática**: "parece que pagás esto todos los meses,
  ¿lo programo?".
- Cambiar un monto "de acá en adelante" sin reescribir el historial.

### Fase 5 -- Análisis y detalle
- Detalle de cada movimiento en formato recibo.
- Evolución de cada categoría en el tiempo, con qué la explica.
- Cierre de mes con el saldo que pasa al siguiente.
- Categorías con ícono y color, y un set predefinido para arrancar sin
  configurar nada.

### Fase 6 -- Multi-moneda de verdad
*Depende de la decisión sobre USD que ya estaba pendiente.*
- Tasas de cambio automáticas, de una fuente gratuita que incluya el
  peso colombiano (varias fuentes gratuitas conocidas no lo incluyen).
- Totales consolidados en una moneda de referencia.

## Lo que NO se puede en una app web (y qué hacemos en su lugar)
Esto no es falta de ganas: son permisos que el iPhone solo le da a las
apps nativas de la App Store.

| Lukas | Por qué no en web | En su lugar |
|---|---|---|
| Detecta solo los pagos con Apple Pay | Solo lo ven las apps nativas | La importación por correo del banco, que ya existe y no depende de Apple Pay |
| Widgets en la pantalla de inicio | iOS no permite widgets a apps web | Atajo "Registrar gasto" al mantener presionado el ícono |
| Siri y automatizaciones | Idem | -- |
| Mapa de dónde pagaste | Viene del dato de Apple Pay | Se podría pedir la ubicación al registrar, si lo querés |
| Doble toque en la espalda del iPhone | Idem | -- |

**Tampoco aplica:** la suscripción Pro (esto no se vende), el modo
invitado sin cuenta (choca con el modelo multiusuario con admin) y el
"100% sin internet" (la app vive en un servidor; lo que sí se puede es
que un registro hecho sin señal quede en cola y se suba después).

## ~~La decisión que necesitamos de vos antes de la Fase 2~~ (ya tomada: sin IA por ahora)
La "inteligencia" de Lukas para registrar hablando o escribiendo es un
modelo de IA. La regla del proyecto es usar solo herramientas
gratuitas, y las APIs de IA se pagan por uso. Hay tres caminos:

1. **Intérprete propio, gratuito** *(recomendado para empezar)*. Reglas
   en español colombiano más aprendizaje de tu propio historial. Cubre
   bien el caso común ("almuerzo 25 lucas") y es instantáneo, sin mandar
   tus datos a nadie. Le cuesta con frases raras.
2. **API de IA paga**. Entiende casi cualquier cosa, incluidas fotos
   difíciles. Rompe la regla de "solo gratuito" y manda tus movimientos
   a un tercero.
3. **Modelo de IA local**, corriendo en tu propia PC. Gratis y privado,
   pero pesado para la máquina donde vive la app, y más lento.

## Qué necesitamos de vos para seguir
- **Cómo se instala** (ver la tabla de arriba). Con "desde el navegador"
  se puede arrancar ya; las tiendas se pueden sumar después sin rehacer
  nada.
- **Para las notificaciones**, que avancemos con el HTTPS (Cloudflare
  Tunnel), que ya estaba en la lista de infraestructura.
- *(USD: ya se resolvió la parte mínima -- los dólares se muestran
  aparte y con aviso. La conversión real sigue siendo la Fase 6.)*
