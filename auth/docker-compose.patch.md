# Что поправить в docker-compose.yml и .gitignore

В `docker-compose.yml`, в сервисе `auth`, добавить том для файла базы данных
(рядом с томом Synapse):

```yaml
  auth:
    build: ./auth
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data-auth:/data
    depends_on:
      - synapse
```

В `.gitignore` добавить строку:

```
data-auth/
```

В `.env.example` сменить значение по умолчанию (чтобы случайно не
опубликовать тестовый режим):

```
DEV_MODE=false
```

и в комментарий над `WA_APP_SECRET` добавить:

```
# ОБЯЗАТЕЛЬНО для публичного сервера: без него сервис откажется запускаться
# (кроме DEV_MODE=true для локальной проверки без реального WhatsApp)
```
