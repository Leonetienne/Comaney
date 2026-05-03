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
       | tar -xz -C /usr/local --strip-components=1 --no-same-owner \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt package*.json ./
RUN pip install --no-cache-dir -r requirements.txt && npm ci

COPY . .

RUN npm run build:css && chmod +x entrypoint.sh && rm -rf build/ node_modules/

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "comaney.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
