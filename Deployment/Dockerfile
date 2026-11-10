FROM node:25.9.0-slim AS assets

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY build/ ./build/
RUN npm run build


FROM python:3.12-slim

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN rm -rf build/ node_modules/ static/dist/
COPY --from=assets /app/static/dist/ ./static/dist/

# Build MkDocs documentation; source is removed afterwards, site stays at docs/build/site/
RUN pip install --no-cache-dir mkdocs-material \
    && cd docs/src && mkdocs build --site-dir /app/docs/build/site \
    && rm -rf docs/src

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "comaney.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
