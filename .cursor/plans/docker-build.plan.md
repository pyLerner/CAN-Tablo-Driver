---
name: Docker сборка CAN-Tablo (итерация)
overview: Минимальный Debian-образ, Python и зависимости только через uv sync, сборка через Docker Compose, рабочий каталог /opt/can-tablo, non-root с группами, том data, TZ=UTC, без Nuitka/zstandard.
---

# План: Docker + Compose для CAN-Tablo-Driver

## Цели

- **Базовый образ:** минимальный Debian-подобный (`debian:*-slim`).
- **Python и зависимости:** только через **`uv sync`** (без системного Python как источника пакетов, кроме apt-библиотек для Pillow).
- **Сборка и запуск:** сценарий через **`docker compose`** (единый `compose.yaml` / `docker-compose.yml`).
- **Каталог проекта в контейнере:** **`/opt/can-tablo/`** (`WORKDIR /opt/can-tablo`).

## 1. Системные пакеты (apt) для Pillow

В Dockerfile после `apt-get update` установить минимальный набор **без recommends**:

- `libfreetype6`
- `libjpeg62-turbo` (или актуальное имя пакета для целевого Debian, например `libjpeg62-turbo` на bookworm/trixie)
- `libopenjp2-7`
- `zlib1g`
- при ошибках импорта Pillow — добавить недостающие `.so` по сообщению об ошибке

Флаг: `-y --no-install-recommends`.

## 2. Копирование проекта и `.dockerignore`

- Копировать в образ содержимое репозитория **без каталога `tests/`** (в Dockerfile: `COPY` с явным списком или `COPY src ...` + `COPY pyproject.toml` + `COPY run_api_server.py` + … без `tests`).
- Добавить **[`.dockerignore`](.dockerignore)** с исключениями:
  - `.git`
  - `.venv`
  - `__pycache__`
  - `logs/`
  - `*.pyc`
  - `.cursor`
  - крупные артефакты (например `dist/`, `build/`, `*.egg-info`, кэши линтеров и т.д. по необходимости)

Цель — уменьшить контекст сборки и слои.

## 3. Зависимости: без Nuitka и zstandard

- В **[`pyproject.toml`](pyproject.toml)** убрать **`nuitka`** из основных `dependencies` (и не добавлять **`zstandard`**, если не требуется явно).
- Проверить транзитивные зависимости: при появлении `zstandard` как transitive — при необходимости зафиксировать версии альтернатив или отключить optional extras у прямых зависимостей (уточнить при сборке через `uv tree`).

После правок: **`uv lock`** и закоммитить **`uv.lock`** для воспроизводимого `uv sync --frozen` в образе.

## 4. Установка через uv в образе

- Установить бинарник **`uv`** (копирование из `ghcr.io/astral-sh/uv` или официальный инсталлятор — как в принятом Dockerfile).
- `WORKDIR /opt/can-tablo`
- `uv python install 3.13` (или версия из `requires-python`) при отсутствии подходящего Python в базовом образе.
- **`uv sync --frozen --no-dev`** (или без `--frozen` до появления lock — на этапе реализации предпочтительно `--frozen`).

## 5. Точка входа

Требование: **`uv run run_api_server --config /opt/can-tablo/etc/config.toml`**

- Для имени команды **`run_api_server`** без `python ...` в **[`pyproject.toml`](pyproject.toml)** нужна секция **`[project.scripts]`**, например:
  - `run_api_server = "run_api_server:main"`
- Пакет/модуль должен быть **устанавливаемым** вместе с проектом (`uv sync` ставит проект в venv). Потребуется минимальная конфигурация **build-backend** (например **hatchling**) с включением **`run_api_server.py`** как модуля в корне проекта (`py-modules` или аналог).
- В **Compose** задать `command` или `entrypoint` оболочкой, например:
  - `["sh", "-c", "uv run run_api_server --config /opt/can-tablo/etc/config.toml"]`
  - либо `ENTRYPOINT` + `CMD` в Dockerfile.

Конфиг **`/opt/can-tablo/etc/config.toml`** — монтируется с хоста (том на `etc/`), пути внутри TOML к данным должны указывать на **`/opt/can-tablo/data/...`** (шрифты, `text-in.json`, при необходимости относительные пути от корня проекта согласовать с mount).

## 6. Пользователь non-root и устройства

- Создать пользователя (например `can-tablo`) с **фиксированным UID/GID** (через build-args или стандартные значения), не запускать процесс от root.
- В **docker compose** для сервиса:
  - `user: "${UID}:${GID}"` **или** заранее согласованные uid/gid в образе.
  - **`group_add`**: типично **`dialout`** для **`/dev/ttyACM*`**; для CAN-узлов (`/dev/can*`, `/dev/vcan*`) — проверить GID устройств на хосте (`ls -l /dev/vcan0`) и добавить соответствующую группу (часто совпадает с `dialout` или отдельная группа `can` — **задать по факту хоста**).
- Проброс устройств: директива **`devices`** в compose с нужными путями **или** политика без `privileged`, если достаточно прав на узлы.
- Для **SocketCAN** с интерфейсами на хосте часто нужен **`network_mode: host`** — указать в плане реализации compose как основной вариант для `python-can` + `vcan0`/`can0`.

## 7. Том `data`

- Каталог данных хоста монтируется в **`/opt/can-tablo/data`** (read-write).
- В `config.toml`: `[TextIn]`, шрифты, опционально пути логов — вести в **`/opt/can-tablo/data/...`** (или подкаталоги `data/fonts`, `data/text-in.json` по соглашению).

## 8. Часовой пояс UTC

- **Не** монтировать `/etc/localtime` с хоста.
- В образе и в compose: **`ENV TZ=UTC`** (и при необходимости установить пакет **`tzdata`** в минимальной конфигурации с `DEBIAN_FRONTEND=noninteractive`, выбрав `Etc/UTC` при интерактивных скриптах — для slim обычно достаточно `TZ=UTC` + tzdata noninteractive).

## 9. Очистка кэшей после установки

После `apt-get install` и `uv sync` в том же слое Dockerfile:

- `apt-get clean`
- `rm -rf /var/lib/apt/lists/*`
- очистить кэши **uv** при наличии (переменные `UV_*`, каталоги кэша в `$HOME` или `/root` — удалить явно в builder/final stage)
- не оставлять промежуточные артефакты сборки в финальном слое (multi-stage: в runtime только venv + нужные файлы)

## 10. Артефакты репозитория (при выполнении плана)

| Файл | Назначение |
|------|------------|
| `Dockerfile` | multi-stage: deps + `uv sync`, финальный slim-слой |
| `compose.yaml` | build, volumes (`etc`, `data`, опционально `logs`, `docs`), `user`/`group_add`, `devices`, `network_mode`, `environment` |
| `.dockerignore` | как в п.2 |
| правки `pyproject.toml` | scripts `run_api_server`, удаление nuitka; pruned deps |
| `uv.lock` | после `uv lock` |
| `README.md` (кратко) | пример `docker compose up --build`, требования к путям и правам на `/dev` |

## Порядок задач (todos)

1. Обновить `pyproject.toml`: убрать Nuitka (и zstandard), добавить `[project.scripts]` `run_api_server`, hatchling + включение `run_api_server.py`.
2. `uv lock`, проверить отсутствие zstandard при необходимости.
3. Добавить `.dockerignore`.
4. Написать `Dockerfile` (`/opt/can-tablo`, apt для Pillow, uv, `uv sync --frozen --no-dev`, non-root user, очистка кэшей, `TZ=UTC`).
5. Написать `compose.yaml` (тома `etc`, `data`, устройства, группы, при необходимости `network_mode: host`).
6. Краткая документация в README.
