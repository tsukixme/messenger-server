## Сделано

2026-10-02: после прямого сообщения владельца «Claude одобрил» выполнены
слияния в указанном порядке:

1. [messenger #3, REUSE](https://github.com/tsukixme/messenger/pull/3),
   merge `2f7bf3f2090f189e02b20ae4afaba2e4d591c231`.
2. [messenger #2, сборки](https://github.com/tsukixme/messenger/pull/2),
   merge `cdbcbcca46132351a1f58b9def6ecf0a9b420a10`, после обновления
   ветки из main и успешных Check licenses / code_tests.
3. [messenger-server #2, скрипты](https://github.com/tsukixme/messenger-server/pull/2),
   merge `baf2e46292ba3b12151444ade3aadac9597860aa`.

На перезагруженной ВМ сначала проверен `docker compose ps`. В каталог
`/home/tildes/messenger-server/web` размещён уже проверенный web-артефакт
[run 36970952993](https://github.com/tsukixme/messenger/actions/runs/36970952993),
commit `1c4e5073880086f45349a70421ebe63d0b0f9224`.
Код приложения совпадает с main merge; отличаются workflow/REUSE/docs.
Предыдущего web-каталога не было, чужие данные не перезаписывались.
Перенос выполнен через SSH с прежним строгим known_hosts.

## Вывод проверки

- Compose ps до и после переноса: `auth`, `nginx`, `ngrok` — Up;
  `synapse` — Up (healthy). Сервисы не перезапускались.
- Перед server #2 повторён изолированный Linux прогон:
  `python3 -m unittest discover -s tests -v`, **7/7 OK**.
  Реальные аккаунты и резервные копии в этом прогоне не создавались.
- В обновлённом app PR #2 [code_tests](https://github.com/tsukixme/messenger/actions/runs/36974265753/job/110734573826)
  success, включая Check licenses, оба analyze и Flutter tests.
- Внешний web ZIP сверён с digest GitHub; внутренний ZIP SHA-256:
  `9500302c97f6058d0188906abcd4caa8ed3f77891fc1872b511388be5c93a21b`.
  Проверены пути, типы ZIP-записей, дубликаты, CRC и свободное место.
- После распаковки и после размещения независимо проверены все **133 файла**.
  SHA-256 канонического JSON списка относительных путей/хешей:
  `bad6345e9f797924b9ec9e92d94ea0f0fbaf03cdb355fe5d7344ab00672e0e8a`.
  Список совпал с локальным эталоном, каталоги имеют 755, файлы 644.
- Автоматическая [сборка main 36974966270](https://github.com/tsukixme/messenger/actions/runs/36974966270)
  запущена на app merge commit `cdbcbcca`; пока выполняется.

## Проблемы

Размещение файлов не означает публикацию web. [Серверный PR #3](https://github.com/tsukixme/messenger-server/pull/3)
оставлен открытым по прямому указанию владельца: nginx/Compose не применялись.
Runtime-скрипты ВМ также пока не обновлялись из слитого server #2.
Установка на телефоны, публичный браузерный вход, E2EE и обмен на устройствах
не проверены. Завершение нового main build и остальных upstream jobs
успешным не объявляется.

## Что дальше

Серверный PR #3 оставлять открытым до отдельного разрешения владельца.
После разрешённой публикации проверить публичную страницу и сценарии
двух устройств. Обновлённые скрипты устанавливать отдельно, не создавая
новые аккаунты без поручения. WhatsApp, шаги S3 6в/7/8 и S5 отложены.
