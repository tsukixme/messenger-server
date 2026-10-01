# S2 — применение auth-update.zip

Дата: 2026-10-01. Ветка: `auth-hardening`.
Статус: пакет применён, pytest пройден; сборка Docker и отказ запуска
контейнера без секрета подтверждены на ВМ 2026-10-01.
Открыт [черновой PR #1](https://github.com/tsukixme/messenger-server/pull/1).
Это отчёт подготовки PR, готовность развёртывания S2 не подтверждается.

## Сделано

- Пакет владельца применён в отдельной ветке `messenger-server` от
  `cdb82be55728f578736af33a60d1de9f7748f95c`, строго по
  [README-for-codex.md](../../auth/README-for-codex.md) и
  [docker-compose.patch.md](../../auth/docker-compose.patch.md).
- SHA-256 исходного ZIP:
  `a7979e0a75965c0a30940516f784012aec95b7307fd3074eaa9a19183b2e60ab`.
  Все 9 файлов `auth/` в рабочей копии сверены с распакованным пакетом
  по SHA-256: совпадение побайтовое. Код, тесты и инструкции автора
  дополнительно не редактировались. `requirements.txt` совпадает
  с исходным Git-содержимым и не образует изменения в PR.
- В compose добавлен том `./data-auth:/data` для `auth`; в `.gitignore`
  добавлен `data-auth/`. В `.env.example` установлено `DEV_MODE=false`
  и добавлен ровно предусмотренный комментарием пакета текст о секрете.
- Предыдущий отчёт архитектора сохранён отдельно в репозитории приложения:
  [T22-Claude.md](https://github.com/tsukixme/messenger/blob/main/docs/reports/T22-Claude.md).
  Его независимая проверка и незавершённая часть Flutter-аудита описаны в
  [T22-codex-review.md](https://github.com/tsukixme/messenger/blob/main/docs/reports/T22-codex-review.md).
  Авторские 16 проверок с заглушками не являются приведённым ниже pytest-прогоном.
- При первоначальной проверке на Windows `.env` не создавался;
  настоящие секреты не использовались.
  `git check-ignore -v` подтверждает исключение `.env`,
  `data-auth/auth.db` и Python bytecode. По последующему прямому поручению
  владельца выполнена изолированная Docker-проверка на его ВМ; после
  проверки управление возвращено владельцу.

Изменённые и добавленные файлы PR:

- `.env.example`
- `.gitignore`
- `docker-compose.yml`
- `auth/Dockerfile`
- `auth/app.py`
- `auth/db.py`
- `auth/test_app.py`
- `auth/pytest.ini`
- `auth/requirements-dev.txt`
- `auth/README-for-codex.md`
- `auth/docker-compose.patch.md`
- `docs/reports/S2-codex.md`

## Вывод проверки

Зависимости установлены в отдельное окружение вне Git командой
`python -m pip install -r requirements.txt -r requirements-dev.txt`.
Среда: Windows, Python 3.12.14; FastAPI 0.115.14, httpx 0.27.2,
pytest 8.4.2, pytest-asyncio 0.24.0, Uvicorn 0.32.1.
Из каталога `auth` выполнено `python -m pytest test_app.py -v`.
Использованы фиктивные настройки и SQLite вне репозитория;
вызовы WhatsApp/Synapse в тестах подменены. Код выхода: **0**.
Полный вывод:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.14, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\user\Documents\Tildes\.local\venvs\auth-hardening\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\user\Documents\Tildes\.local\worktrees\auth-hardening\auth
configfile: pytest.ini
plugins: anyio-4.15.1, asyncio-0.24.0
asyncio: mode=Mode.AUTO, default_loop_scope=None
collecting ... collected 13 items

test_app.py::test_start_creates_session_and_returns_code PASSED          [  7%]
test_app.py::test_start_rejects_invalid_phone PASSED                     [ 15%]
test_app.py::test_status_pending_until_verified PASSED                   [ 23%]
test_app.py::test_status_unknown_session_returns_410 PASSED              [ 30%]
test_app.py::test_webhook_rejects_missing_signature PASSED               [ 38%]
test_app.py::test_webhook_rejects_wrong_signature PASSED                 [ 46%]
test_app.py::test_webhook_accepts_correct_signature_and_confirms_matching_phone PASSED [ 53%]
test_app.py::test_webhook_ignores_code_from_wrong_sender PASSED          [ 61%]
test_app.py::test_dev_message_disabled_when_dev_mode_false PASSED        [ 69%]
test_app.py::test_start_rate_limited_after_5_attempts_per_phone PASSED   [ 76%]
test_app.py::test_start_rate_limited_per_ip_across_different_phones PASSED [ 84%]
test_app.py::test_session_survives_matrix_failure_and_succeeds_on_retry PASSED [ 92%]
test_app.py::test_status_returns_credentials_once_then_410 PASSED        [100%]

============================= 13 passed in 0.48s ==============================
```

Дополнительно выполнены 3 проверки загрузки ASGI-приложения отдельными
процессами через `uvicorn.Config('app:app', log_level='error').load()`.
Слушающие сокеты не открывались; это проверка загрузки приложения,
а не работающего HTTP-сервера или Docker:

| Окружение | Код выхода | Результат |
|---|---|---|
| `DEV_MODE=false`, секрет пуст | 1 | Сообщение `WA_APP_SECRET не задан`; SQLite-файл не создан. |
| `DEV_MODE=false`, фиктивный тестовый секрет | 0 | ASGI-приложение загружено. |
| `DEV_MODE=true`, секрет пуст | 0 | ASGI-приложение загружено; это разрешённое исключение для локальной разработки. |

### Docker на Ubuntu-Server-24.04

По прямому поручению владельца проверка выполнена на ВМ `10.80.247.84`
через консоль VirtualBox, в существующей сессии пользователя `tildes`.
SSH-ключевой доступ не настраивался. Среда: Docker Engine 29.1.3,
Linux/amd64, Compose `2.40.3+ds1-0ubuntu1~24.04.1`.

В отдельный каталог `/home/tildes/tildes-auth-pr1.1QXYx5/repo` клонирован
PR #1; checkout закреплён на
`9766aabf19f3bfa8a0d60e284b9aa8c93d285ebc`.
Создан только тестовый `.env` с `DEV_MODE=false`, пустыми `WA_APP_SECRET`,
`NGROK_DOMAIN` и `NGROK_AUTHTOKEN`. Настоящий `.env` проекта не читался.
До и после проверки `git status --porcelain` в этой копии пуст.
SHA-256 файлов Dockerfile/app.py/db.py/requirements.txt и compose на ВМ
сопоставлены с Git-содержимым PR: все пять совпали.

Выполнено:

```sh
BUILDKIT_PROGRESS=plain docker compose -p tildes-auth-pr1-9766 build auth
```

Код выхода сборки: **0**. Итог build log: `auth Built`.
Образ: `tildes-auth-pr1-9766-auth:latest`;
ID, полученный через `docker image inspect`:
`sha256:f428869dee2e22925f4f4dc99ed1fdba48bc0da415b822821d250475cd828652`.
Именно этот ID использован для запуска:

```sh
docker run -d --name tildes-auth-pr1-9766-empty-secret --restart=no --network=none \
  -e DEV_MODE=false -e WA_APP_SECRET= \
  sha256:f428869dee2e22925f4f4dc99ed1fdba48bc0da415b822821d250475cd828652
docker wait tildes-auth-pr1-9766-empty-secret
docker inspect --format '{{json .State}}' tildes-auth-pr1-9766-empty-secret
docker logs tildes-auth-pr1-9766-empty-secret
```

`docker run -d` вернул **0**: контейнер успешно создан и запущен.
`docker wait` вернул значение **1**; `.State.ExitCode=1`,
`.State.Status=exited`, `Running=false`, `OOMKilled=false`, `Error=""`.
`StartedAt=2026-10-01T12:28:49.543786674Z`,
`FinishedAt=2026-10-01T12:28:50.156860798Z`: контейнер завершился примерно
за **0,61 с** по timestamps Docker State. Это ожидаемый отказ приложения.

Полный лог контейнера:

```text
WA_APP_SECRET не задан. Без него /auth/webhook примет сообщение от кого угодно, а не только от WhatsApp. Задайте WA_APP_SECRET в .env, или включите DEV_MODE=true только для локальной проверки без реального WhatsApp (не для публичного сервера).
```

Через inspect дополнительно подтверждены: `RestartCount=0`, restart policy
`no`, network `none`, опубликованных портов и mounts нет. Список других
работающих контейнеров до и после одинаков. Тестовый контейнер оставлен
в состоянии `exited` для просмотра владельцем; образ сохранён.
Временный HTTP-сервер для получения только тестовых логов остановлен:
порт 18641 после проверки отвечает `ConnectionRefused`.
Доказательства сохранены вне Git в проектной `.local/auth-docker-evidence`.

## Проблемы

- Сборка образа и отказ контейнера без секрета проверены. Полный
  `docker compose up -d auth` не выполнялся: проверка проведена отдельным
  контейнером того же образа без зависимостей, сети и production volumes.
  Штатная политика compose `restart: unless-stopped` не проверялась;
  одноразовый тест использовал `restart=no`, чтобы зафиксировать завершение.
  Эта проверка не подтверждает работоспособность всего стека.
- Реальные Meta/WhatsApp, Synapse, nginx, ngrok и телефоны не проверялись.
  SQLite после перезапуска процесса/контейнера, TTL и конкуренция не
  включены в предоставленные 13 pytest-тестов.
- Выдача данных и удаление сессии в пакете разделены сетевым вызовом:
  последовательный тест «один раз, затем 410» не доказывает атомарную
  выдачу при параллельных запросах. Подсчёт/запись попытки номера также
  отдельные операции. Код пакета оставлен без изменений.
- IP-лимит использует `request.client.host`; получение IP пользователя
  через nginx и доверие forwarded-заголовкам в Docker не проверены.
  IP-история хранится в памяти и сбрасывается при перезапуске.
  Эти ограничения указаны для ревью; дополнительные исправления
  не входят в поручение владельца.

## Что дальше

1. PR открыт с этим отчётом, ссылками на T22 и инструкцию пакета,
   перечнем файлов и фактическим выводом pytest; остаётся черновиком.
2. Запрошенные сборка и отказ контейнера без секрета выполнены на ВМ;
   результаты добавлены выше. Дальнейшие интеграционные проверки всего
   стека выполняются отдельным поручением после готовности окружения.
3. Передать PR архитектору для ревью. Слияние требует решения владельца;
   текущий PR сам по себе не означает завершения S1/S2 или развёртывания.
