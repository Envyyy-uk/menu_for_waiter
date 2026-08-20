FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

COPY backend /srv/backend
COPY frontend /srv/frontend
COPY seed_menu.json /srv/seed_menu.json

WORKDIR /srv/backend
ENV PYTHONPATH=/srv/backend

CMD ["./entrypoint.sh"]
