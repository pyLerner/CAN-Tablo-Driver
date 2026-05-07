FROM debian:bookworm-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/app/.uv-python

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libfreetype6 \
        libjpeg62-turbo \
        libopenjp2-7 \
        zlib1g \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv python install 3.13

COPY pyproject.toml uv.lock README.md /app/
COPY run_api_server.py /app/
COPY src /app/src

RUN uv sync --frozen --no-dev

RUN uv cache prune \
    && rm -rf /root/.cache/uv /tmp/uv-* 2>/dev/null || true

FROM debian:bookworm-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    CAN_TABLO_HOME=/app \
    UV_PROJECT=/app \
    UV_PYTHON_INSTALL_DIR=/app/.uv-python \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        iproute2 \
        libfreetype6 \
        libjpeg62-turbo \
        libopenjp2-7 \
        zlib1g \
        tzdata \
    && ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime \
    && echo "Etc/UTC" > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=builder /app/.uv-python /app/.uv-python
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml /app/uv.lock /app/
COPY --from=builder /app/run_api_server.py /app/
COPY --from=builder /app/src /app/src
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin cantablo \
    && chown -R cantablo:cantablo /app

USER cantablo

EXPOSE 7070

ENTRYPOINT ["/app/entrypoint.sh"]
