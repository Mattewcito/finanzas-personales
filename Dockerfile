# Imagen liviana con Python. La app (Flask) es puro código Python + HTML,
# no necesita nada más pesado.
FROM python:3.12-slim

# Zona horaria de Colombia (UTC-5, sin horario de verano) -- sin esto, la
# imagen base queda en UTC y CUALQUIER timestamp (datetime.now() en Python,
# datetime('now','localtime') en SQLite, los logs) queda corrido 5 horas
# respecto a la hora real del usuario. Afecta tanto lo que se MUESTRA
# ("última corrida") como la lógica de "una vez al día a las X" de
# leer_correo.py, que compara contra la hora que el usuario configuró
# pensando en su propia hora local.
ENV TZ=America/Bogota
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# gunicorn: servidor WSGI real para producción (Flask trae uno propio, pero
# avisa que no es para dejarlo corriendo expuesto de forma permanente). Solo
# se usa acá adentro del contenedor -- no en requirements.txt porque no
# corre nativo en Windows (donde seguís usando "py app.py" para desarrollo).
RUN pip install --no-cache-dir gunicorn

# El código se copia a la imagen (no cambia en caliente).
# data/ y dashboard/ NO se copian acá -- se montan como volúmenes en
# docker-compose.yml, porque son los datos reales que cambian todo el tiempo.
COPY src/ ./src/

ENV RUNNING_IN_DOCKER=1
ENV HOST=0.0.0.0
ENV PORT=5001

WORKDIR /app/src
EXPOSE 5001

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "app:app"]
