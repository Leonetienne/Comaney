FROM python:3.12-slim

ARG NODE_VERSION=25.9.0
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    curl \
    && curl -fsSL https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.gz \
       | tar -xz -C /usr/local --strip-components=1 --no-same-ow  ner \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt package.json ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN npm install
RUN npm run build && rm -rf node_modules/ build/

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
