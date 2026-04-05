# =============================================================================
# Многостадийная сборка CAN-Tablo-Driver: минимальный Debian, зависимости через uv.
# Рабочий каталог в контейнере: /opt/can-tablo
# =============================================================================

# -----------------------------------------------------------------------------
# Стадия 1 (builder): ставим Python через uv, собираем виртуальное окружение.
# В финальный образ переносим только .venv и каталог src/ (каталог tests/ не в контексте — см. .dockerignore).
# -----------------------------------------------------------------------------

FROM debian:bookworm-slim AS builder

# Неинтерактивный apt и явный UTC (без монтирования localtime с хоста).
# Python от uv по умолчанию ставится в /root/.local/share/uv — symlink из .venv ведёт туда; при USER cantablo
# обход /root даёт Permission denied при canonicalize. Держим интерпретатор под /opt/can-tablo (см. COPY .uv-python).
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/can-tablo/.uv-python

WORKDIR /opt/can-tablo

# Системные .so для Pillow (имена пакетов — для Debian bookworm).
# ca-certificates + curl — для возможных HTTPS-загрузок uv; минимальный набор.
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

# Официальный статический бинарник uv (Astral).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Интерпретатор Python 3.13 под requires-python в pyproject.toml (в slim-образе apt может не дать нужную версию).
RUN uv python install 3.13

# Слой кэша: пока не менялись зависимости, пересборка быстрее.
COPY pyproject.toml uv.lock README.md ./

# Точка входа и исходники приложения (без tests — исключены .dockerignore).
COPY run_api_server.py ./
COPY src ./src

# Прод-зависимости; --frozen гарантирует соответствие uv.lock.
RUN uv sync --frozen --no-dev

# Убираем кэш uv, чтобы не раздувать промежуточные артефакты и привычку к «грязным» слоям.
RUN uv cache prune \
    && rm -rf /root/.cache/uv /tmp/uv-* 2>/dev/null || true

# -----------------------------------------------------------------------------
# Стадия 2 (runtime): только runtime-библиотеки, venv, код; процесс не под root.
# -----------------------------------------------------------------------------

FROM debian:bookworm-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    CAN_TABLO_HOME=/opt/can-tablo \
    UV_PROJECT=/opt/can-tablo \
    UV_PYTHON_INSTALL_DIR=/opt/can-tablo/.uv-python \
    UV_NO_CACHE=1 \
    PATH="/opt/can-tablo/.venv/bin:${PATH}"

WORKDIR /opt/can-tablo

# Те же библиотеки, что нужны wheel Pillow в рантайме; tzdata — для корректной работы libc со смещением UTC.
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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# uv оставляем для команды «uv run …» (требование сценария); --no-sync не трогает lock при старте.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY --from=builder /opt/can-tablo/.uv-python /opt/can-tablo/.uv-python
COPY --from=builder /opt/can-tablo/.venv /opt/can-tablo/.venv
COPY --from=builder /opt/can-tablo/pyproject.toml /opt/can-tablo/uv.lock ./
COPY --from=builder /opt/can-tablo/run_api_server.py ./
COPY --from=builder /opt/can-tablo/src ./src

# UID 1000 должен совпадать с user: в compose, иначе поправьте оба места.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin cantablo \
    && chown -R cantablo:cantablo /opt/can-tablo

USER cantablo

# Подсказка для оператора; реальный порт задаётся [api-server].port в config.toml.
EXPOSE 8000

# Конфиг ожидается смонтированным с хоста: /opt/can-tablo/etc/config.toml
CMD ["uv", "run", "--no-sync", "run_api_server", "--config", "/opt/can-tablo/etc/config.toml"]
