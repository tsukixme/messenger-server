# Пилот: свой мессенджер (Matrix + FluffyChat) с входом через WhatsApp

Пошаговая инструкция — в документе, который прилагается к этому архиву.

Коротко:
1. cp .env.example .env  и заполните NGROK_DOMAIN, NGROK_AUTHTOKEN, SERVER_NAME
2. Сгенерируйте конфигурацию Synapse (этап 3 инструкции)
3. docker compose up -d synapse  -> создайте администратора и получите токен
4. Впишите SYNAPSE_ADMIN_TOKEN в .env  ->  docker compose up -d --build
5. Проверка: https://ВАШ-ДОМЕН/auth/health

Состав:
- docker-compose.yml  — все сервисы
- auth/               — сервис входа (Python, FastAPI)
- nginx/default.conf  — маршрутизация /_matrix -> Synapse, /auth -> сервис входа
- flutter/phone_login_page.dart — экран входа для вашего форка FluffyChat
