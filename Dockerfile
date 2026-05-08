FROM python:3.13-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml /app/

RUN python - <<'PY'
import pathlib
import tomllib

data = tomllib.loads(pathlib.Path("/app/pyproject.toml").read_text(encoding="utf-8"))
deps = data.get("project", {}).get("dependencies", [])
pathlib.Path("/app/requirements.txt").write_text("\n".join(deps) + "\n", encoding="utf-8")
PY

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r /app/requirements.txt

COPY run_api_server.py /app/
COPY src /app/src

FROM python:3.13-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    CAN_TABLO_HOME=/app \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libfreetype6 \
        libjpeg62-turbo \
        libopenjp2-7 \
        zlib1g \
        tzdata \
    && ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime \
    && echo "Etc/UTC" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
    && rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/requirements.txt /app/requirements.txt
COPY --from=builder /app/run_api_server.py /app/
COPY --from=builder /app/src /app/src
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin cantablo \
    && chown -R cantablo:cantablo /app /opt/venv

USER cantablo

EXPOSE 7070

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "run_api_server.py", "--config", "/app/etc/config.toml"]
