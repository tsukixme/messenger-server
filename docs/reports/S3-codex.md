# S3 — развёртывание сервера

Обновлено: 2026-10-02. **S3 завершён и проверен в объёме последнего решения владельца.**

## Сделано

- Подтверждено слияние [PR #1](https://github.com/tsukixme/messenger-server/pull/1) в `main`, коммит `17686e834ff496a3ce8affdfe3e35aaa3c478ba7`. Этот `main` склонирован на ВМ в `/home/tildes/messenger-server`.
- Создан отдельный Ed25519-ключ в `.local/ssh` проекта на Windows, вне Git. Приватный ключ не выводился; доступ к нему имеет только текущий пользователь Windows. Публичная часть добавлена на ВМ: `.ssh` — 700, `authorized_keys` — 600, владелец `tildes`. Вход по паролю не отключался.
- После двух ошибок Windows `ssh-keyscan` работа была остановлена по правилу владельца. Владелец разрешил другой способ: публичный host key прочитан из доверенной консоли VirtualBox, fingerprint сверён и сохранён в проектном `known_hosts`. Вход проверен с `StrictHostKeyChecking=yes`, `BatchMode=yes`, `IdentitiesOnly=yes`. После этого команды в ВМ выполняются только через SSH.
- Удалены проверенные собственные остатки S2 по точным именам: `/home/tildes/tildes-auth-pr1.1QXYx5`, контейнер `tildes-auth-pr1-9766-empty-secret`, образ `tildes-auth-pr1-9766-auth:latest`. Перед удалением проверены реальный путь, отсутствие симлинка, исходный коммит и ID объектов Docker.
- Создан `.env` с правами 600. Домен: `herbicide-ninth-reliance.ngrok-free.dev`; `DEV_MODE=false`. Временные `WA_APP_SECRET` и `WA_VERIFY_TOKEN` сгенерированы локально на ВМ без вывода. Токен ngrok владелец ввёл сам через скрытый ввод; `.env` игнорируется Git.
- Сгенерирована и настроена конфигурация Synapse. Запущены четыре сервиса: Synapse, auth, nginx, ngrok. Auth оставлен без изменений, со случайным секретом; реальный WhatsApp отложен владельцем.
- Созданы `scripts/create-user.sh` и `scripts/backup.sh` в отдельной ветке от `main`; открыт [draft PR #2](https://github.com/tsukixme/messenger-server/pull/2), коммит `4196771b9e4369e2dc13c4a073ed104275b6fc3a`. Скрипты уже установлены и проверены на ВМ; PR не слит.
- `create-user.sh`: видимый ввод логина, два скрытых ввода пароля, сравнение, штатная команда `register_new_matrix_user --no-admin --password-file /dev/stdin`. Пароль не передаётся в argv или переменных окружения и не печатается. Пустые пароли и пробелы по краям отклоняются, поскольку Synapse CLI сам обрезает whitespace.
- `backup.sh`: архивирует только `data/` и `data-auth/`, исключая `.env` на любом уровне. Копии в `/home/tildes/backups`, каталог 700, архивы 600; сохраняются последние пять архивов собственного точного шаблона имени. На время копирования останавливаются только ранее работавшие Synapse/auth, после операции они запускаются снова; проверка архива предшествует его публикации.
- Для владельца подготовлен `/home/tildes/messenger-server/.local/s3-owner-accounts.sh`: интерактивное создание admin, скрытый ввод пароля для записи admin-токена, создание четырёх обычных пользователей самим владельцем, скрытый ввод паролей demo1/demo2 для проверки внешнего login API. Помощники находятся в локальном игнорируемом каталоге; секреты в Git не попадают.
- 2026-10-02 по просьбе владельца ВМ запущена командой `VBoxManage startvm Ubuntu-Server-24.04 --type gui`. Сохранён адрес `10.80.247.84`, доступ по SSH работает; четыре контейнера запустились автоматически. Публичные проверки повторены успешно.
- Владелец сам создал admin и demo1–demo4 через интерактивный помощник. Проверены права: admin активен и имеет административные права; все четыре demo активны и обычные пользователи. Пароли не читались и не выводились. Admin-токен записан в `.env`; окружение auth обновлено, nginx перезагружен.
- Через публичный HTTPS API проверены login demo1/demo2, создание комнаты, приглашение и присоединение demo2, отправка сообщения demo1, получение того же события demo2 и его появление в `/sync`. Все запросы вернули HTTP 200. Тестовая комната покинута и скрыта из списков обоих пользователей.
- Временные API-сессии demo1/demo2 завершены через `/logout`, локальный файл их токенов удалён. Аккаунты сохранены. Создана итоговая копия с аккаунтами: `/home/tildes/backups/tildes-S3-20261002T043321196604Z.tar.gz`; сохраняются последние пять копий.

Изменённые файлы кода в PR #2: **только** `scripts/create-user.sh`, `scripts/backup.sh`. Файлы документации этого отчёта: `docs/reports/S3-codex.md`, `docs/HANDOFF.md`.

## Вывод проверки

| Проверка | Фактический результат |
|---|---|
| GitHub API PR #1 | `merged=true`, `state=closed`, merge commit соответствует указанному `main` |
| SSH по проектному ключу со строгим `known_hosts` | Exit 0; `id -un` → `tildes` |
| Docker Compose `up -d --build` | Exit 0; образ auth собран, четыре сервиса запущены |
| `docker compose ps`, включая после включения ВМ 2026-10-02 | Все четыре контейнера `Up`; Synapse после загрузки сначала `health: starting` |
| Локальный `curl --fail http://127.0.0.1:8008/_matrix/client/versions` | Exit 0, JSON с версиями Matrix |
| `docker compose exec -T nginx nginx -t` | Exit 0, syntax ok / test successful |
| Логи auth после первоначального запуска | `Application startup complete`, Uvicorn слушает 8000; отказа по секрету нет |
| Публичный `GET /_matrix/client/versions` | HTTP 200, валидный JSON |
| Публичный `GET /auth/health` | HTTP 200, `ok=true`, `dev_mode=false` |
| Публичный `GET /_synapse/admin/v2/users` | HTTP 403 |
| Публичный `POST /auth/dev/message` с корректным телом | HTTP 404 |
| Публичный `POST /auth/webhook` без подписи | HTTP 403 |
| `bash -n` обоих новых скриптов | Exit 0 |
| Проверка create-user с подставной командой Docker, без настоящей регистрации | Пароль только в stdin; его нет в stdout/stderr/argv; несовпадение и whitespace отклоняются до вызова Docker |
| Шесть реальных запусков backup | Сохранены последние пять архивов; посторонний контрольный файл сохранён; каталог 700, архивы 600; `.env` отсутствует, обе базы присутствуют |
| Чтение обеих SQLite-баз из последнего архива в отдельной тестовой среде | `PRAGMA integrity_check` → `ok` для обеих; содержимое не выводилось |
| `pytest -q` неизменённого auth | `13 passed in 0.48s` |
| Synapse Admin API, локально, после действий владельца | admin — HTTP 200, active/admin; demo1–demo4 — HTTP 200, active/non-admin; токен не выводился |
| Публичный `POST /_matrix/client/v3/login`, demo1 и demo2 | HTTP 200 для обоих; пароли введены владельцем скрыто, токены не выводились |
| Публичный `/account/whoami`, demo1 и demo2 | HTTP 200, ожидаемые Matrix ID |
| Публичные `/createRoom`, `/join/{roomId}`, `/rooms/{roomId}/send/m.room.message/{txnId}` | HTTP 200; demo2 присоединился, demo1 отправил контрольное сообщение |
| Публичные `/rooms/{roomId}/event/{eventId}` и `/sync`, demo2 | HTTP 200; совпали event ID, отправитель и текст сообщения |
| `/leave`, `/forget`, `/logout` для обоих тестовых клиентов | HTTP 200; временный файл токенов удалён |
| Итоговая копия после регистрации и обмена сообщениями | Архив опубликован, последние пять сохранены; `.env` отсутствует, обе базы присутствуют; обе извлечённые SQLite-копии проходят `integrity_check` |

Публичные запросы выполнялись из Windows через HTTPS-домен ngrok, с заголовком `ngrok-skip-browser-warning: true`. Это проверка API; открытие браузером и установка приложения на телефон относятся к S4 и пока не проверены.

Эквивалентные команды для повторения публичных проверок без секретов (выше приведены фактические результаты HTTP-запросов из Python):

```bash
curl -H 'ngrok-skip-browser-warning: true' https://herbicide-ninth-reliance.ngrok-free.dev/_matrix/client/versions
curl -H 'ngrok-skip-browser-warning: true' https://herbicide-ninth-reliance.ngrok-free.dev/auth/health
curl -o /dev/null -w '%{http_code}\n' https://herbicide-ninth-reliance.ngrok-free.dev/_synapse/admin/v2/users
curl -H 'Content-Type: application/json' -d '{"phone":"77000000001","text":"S3-disabled-route-check"}' https://herbicide-ninth-reliance.ngrok-free.dev/auth/dev/message
curl -H 'Content-Type: application/json' -d '{}' https://herbicide-ninth-reliance.ngrok-free.dev/auth/webhook
```

Для пустого тела `{}` маршрут dev/message отвечает 422 на проверке схемы FastAPI; с корректным телом — требуемый 404. Код auth по этому поводу не менялся.

Только несекретные строки конфигурации Synapse:

```yaml
server_name: herbicide-ninth-reliance.ngrok-free.dev
report_stats: false
public_baseurl: https://herbicide-ninth-reliance.ngrok-free.dev/
enable_registration: false
allow_guest_access: false
federation_domain_whitelist: []
# В существующем HTTP listener на 8008:
x_forwarded: true
```

Полный `homeserver.yaml` не публикуется: в нём есть секреты. Файл защищён правами 600 и доступен пользователю контейнера Synapse.

## Проблемы

- Блокирующих проблем для согласованного объёма S3 нет. Скрипты в PR #2 ожидают отдельного ревью Claude; PR не слит.
- Ошибка Windows `ssh-keyscan`: `choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com`. Обход через доверенную консоль согласован владельцем и проверен. [Описание ошибки разработчиками Windows OpenSSH](https://github.com/PowerShell/Win32-OpenSSH/issues/2140).
- При сборке Compose сообщил: `Docker Compose is configured to build using Bake, but buildx isn't installed`. Сборка обычным builder завершилась успешно; установки дополнительных компонентов не потребовалось.
- Резервная копия кратковременно прерывает обслуживание Synapse/auth и остаётся на той же ВМ. Архив содержит приватные базы и конфигурацию, хотя `.env` исключён; его содержимое в отчёт не выводится. SIGKILL или выключение ВМ не позволяют скрипту гарантировать перезапуск остановленных сервисов.
- Определение реального адреса клиента за прокси остаётся прежним: шаг 8 отложен явно владельцем. Правки nginx, Uvicorn и публикации порта по этому шагу не делались.

## Что дальше

1. Передать [PR #2](https://github.com/tsukixme/messenger-server/pull/2) Claude на ревью; не сливать самостоятельно.
2. Перейти к **S4** из `tildes-next.zip`: домен приложения, облачные сборки и раздача веб-версии. Для проверки клиентов использовать созданные владельцем demo-аккаунты; пароли вводит сам владелец.
3. По последнему решению владельца **не выполнять** S3 шаги 7 и 8, отложить S3 шаг 6в и **не выполнять S5**. Настройка Meta и интеграция входа по номеру сейчас не входят в работу.
