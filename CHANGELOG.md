# Changelog

Все заметные изменения проекта фиксируются в этом файле.

Формат опирается на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Версии соотносятся с ветками/тегами образов Docker, где это уместно.

## [Unreleased]

_(нет незафиксированных изменений документации сверх релиза ниже)_

## [2-static-antistorm] — 2026-08-05

Ветка: `2026-08-05-CONTINUES-PACKING-MASK-ANTISTORM`.  
Образ Docker: `can-tablo-driver:2-static-antistorm`.

База: continuous packing из `API-one-tablo-and-color-config` + антишторм / статика из линии AntiStorm **без** перехода на row-padded маску.

### Added

- Секция конфига `[send]`: `min_interval`, `on_duplicate` (`skip` | `send`).
- `DisplaySendScheduler`: coalescing (last-write-wins), дедупликация, пауза `min_interval` между успешными отправками.
- Долгоживущий `DisplayTransport` для сериализованной отправки по CAN/ISO-TP.
- Флаги `[display].animate` и `[display].debug`; `[logs].loglevel`; поля `animate` / `debug` / `loglevel` в `POST .../config/set`.
- Усечение текста `truncate_text_to_width` при `animate=false` (только opcode `0x0001`).
- Deploy-пайплайн: `docker/build-off-board.sh`, `docker/docker-compose.prod.yml`, `docker/systemd/can0-setup.service`.
- Установка на плату: `docker/install-old-docker.sh` (предпочтительно **docker-compose v1**, fallback на `docker compose`).
- Тесты: `tests/test_send_scheduler.py`, `tests/test_loglevel.py`, `tests/test_truncate_text.py`; обновлён `tests/test_api.py`.
- `CHANGELOG.md`; актуализированы README и `docs/API_LEDDISPLAYS_V2.md`.

### Changed

- `PUT .../values/update` ставит задачу в scheduler вместо прямой фоновой отправки без dedup.
- Docker-конфиг по умолчанию: `animate = false`, `debug = true`, `loglevel = "DEBUG"`, `[send] min_interval = 300`, `on_duplicate = "skip"`.
- Тег образа и compose: `can-tablo-driver:2-static-antistorm`.

### Fixed / preserved

- Упаковка маски остаётся **непрерывной**: `N = ceil(width × height / 8)`; строки могут начинаться внутри байта (не `ceil(width/8)×height`).

### Deployment

```bash
# сборка bundle на dev (linux/arm64)
./docker/build-off-board.sh

# на целевой плате
sudo ./install-old-docker.sh --copy-to-opt --enable-service
```

## [1-static] — ранее

Ветка / линия `API-one-tablo-and-color-config`.

### Added

- Модель «один контроллер — одно табло», зоны `[display.N]`, REST API V2.
- Непрерывная упаковка битовой маски области.
- Расширенная палитра RGB (в т.ч. белый) и маппинг на wire-код цвета.
- Базовый Docker-образ / тег `can-tablo-driver:1-static`.

### Notes

- Без секции `[send]` и без флага `animate` в конфиге (скролл по переполнению мог включаться всегда по правилам разметки).
