# S2 — применение auth-update.zip

Дата: 2026-10-01. Ветка: `auth-hardening`.
Статус: пакет применён, pytest пройден; проверка Docker не выполнена.
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
- Локальный `.env` не создавался; настоящие секреты не использовались.
  `git check-ignore -v` подтверждает исключение `.env`,
  `data-auth/auth.db` и Python bytecode. ВМ остаётся у владельца.

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

## Проблемы

- Docker CLI не найден в PATH и в стандартных каталогах Docker Desktop.
  На ВМ Docker также ещё не установлен по сообщению владельца.
  `docker compose build auth`, `docker compose up -d auth` и просмотр
  контейнерных логов **не выполнялись**. PR должен оставаться черновиком
  до проверки пункта 5 README; завершение процесса Python не доказывает
  успешную сборку образа. Compose использует `restart: unless-stopped`,
  поэтому отказ запуска приложения может проявляться повторными
  перезапусками контейнера; фактическое поведение здесь не проверено.
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
2. После готовности Docker и отдельного разрешения на работу с окружением
   выполнить пункт 5 README в локальном окружении, без публикации сервиса:
   собрать образ и проверить отказ приложения при выключенном dev mode
   и пустом `WA_APP_SECRET`, приложить логи без секретов.
3. Передать PR архитектору для ревью. Слияние требует решения владельца;
   текущий PR сам по себе не означает завершения S1/S2 или развёртывания.
