# syntax=docker/dockerfile:1
FROM python:3.12-alpine AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1 PRECOS_DB=/data/precos.sqlite PRECOS_CONFIG=/app/config.yaml PORT=8080
WORKDIR /app
COPY --from=build /install /usr/local
# Config padrão; na plataforma ela é montada por cima, e editar uma meta vira um PR só.
COPY config.yaml ./config.yaml
# O runtime só executa `python -m precos`: sem pip/setuptools/wheel, menos superfície e menos CVE embutido.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/lib/python3.12/site-packages/wheel* /usr/local/bin/pip* /usr/local/bin/wheel* \
    && mkdir /data && chown 65534:65534 /data
# nobody (65534): o mesmo grupo que lê os segredos montados pela plataforma (ADR 0014).
USER 65534:65534
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=3s --start-period=15s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["python", "-m", "precos", "run"]
