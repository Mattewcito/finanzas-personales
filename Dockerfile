# Imagen liviana con Python. La app (Flask) es puro código Python + HTML,
# no necesita nada más pesado.
FROM python:3.12-slim

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
