"""
Сервис входа по номеру телефона с подтверждением через WhatsApp.

Схема ("обратная" проверка, бесплатно):
  1. Приложение -> POST /auth/start {phone}        -> получает код и ссылку wa.me
  2. Пользователь отправляет код в WhatsApp на номер компании
  3. Meta -> POST /auth/webhook                     -> сервис видит номер отправителя и код
  4. Приложение опрашивает GET /auth/status/{id}    -> получает логин и пароль Matrix
  5. Приложение входит в Synapse обычным логином

Сессии и история запросов хранятся в SQLite (файл DB_PATH), поэтому
переживают перезапуск контейнера.

Изменения по сравнению с первой версией (пилотной, в памяти):
  - WA_APP_SECRET обязателен, если DEV_MODE выключен: без него сервис не
    запустится. Раньше при пустом секрете проверка подписи молча
    пропускалась, и запрос на /auth/webhook принимался без проверки,
    кто его прислал.
  - Данные пережили перезапуск (SQLite вместо памяти).
  - Добавлено простое ограничение числа запросов с одного IP-адреса в
    /auth/start, отдельно от уже существующего ограничения на номер.
  - Если Synapse не ответил при выдаче пароля, сессия остаётся
    подтверждённой и доступной для повторной попытки, а не теряется.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
import time
from collections import defaultdict
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("auth")

SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
SERVER_NAME = os.environ.get("SERVER_NAME", "")
ADMIN_TOKEN = os.environ.get("SYNAPSE_ADMIN_TOKEN", "")
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"
DB_PATH = os.environ.get("DB_PATH", "/data/auth.db")

WA_BUSINESS_NUMBER = re.sub(r"\D", "", os.environ.get("WA_BUSINESS_NUMBER", ""))
WA_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.environ.get("WA_APP_SECRET", "")
WA_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")

CODE_TTL = 10 * 60             # код живёт 10 минут
MAX_STARTS_PER_HOUR = 5        # не больше 5 попыток входа с одного номера в час
MAX_STARTS_PER_IP_HOUR = 30    # и не больше 30 попыток в час с одного IP-адреса, суммарно

# Без этой проверки подписи сервис принимал бы на /auth/webhook что угодно
# от кого угодно, выдавая себя за сообщение из WhatsApp. Поэтому секрет
# обязателен всегда, кроме локальной проверки с DEV_MODE=true.
if not DEV_MODE and not WA_APP_SECRET:
    sys.exit(
        "WA_APP_SECRET не задан. Без него /auth/webhook примет сообщение "
        "от кого угодно, а не только от WhatsApp. Задайте WA_APP_SECRET в "
        ".env, или включите DEV_MODE=true только для локальной проверки "
        "без реального WhatsApp (не для публичного сервера)."
    )

db = Database(DB_PATH)
_ip_starts: dict[str, list[float]] = defaultdict(list)  # IP -> времена запросов (только в памяти)

app = FastAPI(title="WhatsApp login for Matrix (pilot)")


# ---------- вспомогательное ----------

def normalize_phone(raw: str) -> str:
    """'8 701 123-45-67', '+7 701...', '701...' -> '77011234567'.

    Внимание: любые 10 цифр трактуются как номер с кодом 7 (Казахстан/
    Россия), включая номера других стран такой же длины. Для пилота в
    Казахстане это приемлемо, но при выходе за пределы СНГ формат нужно
    будет уточнять по коду страны, а не по одной лишь длине номера.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 11 <= len(digits) <= 15:
        raise HTTPException(400, "Неверный номер телефона")
    return digits


def _check_ip_rate_limit(ip: str) -> None:
    """Минимальная защита от перегрузки запросами: лимит в памяти, на один процесс.

    Это не замена полноценному rate-limiter (например, при нескольких
    запущенных копиях сервиса у каждой будет свой счётчик), но для пилота
    с одним контейнером этого достаточно, чтобы один источник не мог
    поставить в очередь произвольное количество номеров.
    """
    now = time.time()
    recent = [t for t in _ip_starts[ip] if now - t < 3600]
    if len(recent) >= MAX_STARTS_PER_IP_HOUR:
        raise HTTPException(429, "Слишком много запросов с этого адреса, попробуйте позже")
    recent.append(now)
    _ip_starts[ip] = recent


def new_code(active: set[str]) -> str:
    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in active:
            return code


async def handle_incoming(sender: str, text: str) -> bool:
    """Сообщение пришло в WhatsApp: ищем в нём код и сверяем номер отправителя."""
    await db.cleanup(time.time())
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text or "")
    if not match:
        return False
    code = match.group(1)
    sender = normalize_phone(sender)
    result = await db.mark_verified_by_code(code, sender)
    if result is None:
        return False
    if result == "wrong_phone":
        log.warning("Код %s пришёл с чужого номера %s", code, sender)
        return False
    log.info("Номер %s подтверждён (сессия %s)", sender, result[:8])
    return True


async def ensure_matrix_user(phone: str) -> tuple[str, str]:
    """Создаёт пользователя в Synapse (или обновляет пароль) и возвращает логин и пароль."""
    if not ADMIN_TOKEN or not SERVER_NAME:
        raise HTTPException(500, "Не заданы SYNAPSE_ADMIN_TOKEN или SERVER_NAME")
    # Synapse не разрешает логины только из цифр, поэтому добавляем букву u
    user_id = f"@u{phone}:{SERVER_NAME}"
    password = secrets.token_urlsafe(24)
    url = f"{SYNAPSE_URL}/_synapse/admin/v2/users/{quote(user_id)}"
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        exists = (await client.get(url, headers=headers)).status_code == 200
        body = {"password": password, "logout_devices": False}
        if not exists:
            body["displayname"] = f"+{phone}"
        r = await client.put(url, headers=headers, json=body)
        if r.status_code not in (200, 201):
            log.error("Synapse ответил %s: %s", r.status_code, r.text)
            raise HTTPException(502, "Не удалось создать пользователя в Synapse")
    log.info("%s пользователь %s", "Обновлён" if exists else "Создан", user_id)
    return user_id, password


async def send_whatsapp_text(to: str, text: str) -> None:
    """Ответ пользователю в WhatsApp (необязательно). Внутри 24-часового окна после его сообщения."""
    if not (WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID):
        return
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload,
                                  headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"})
            if r.status_code >= 300:
                log.warning("Ответ в WhatsApp не отправлен: %s %s", r.status_code, r.text)
    except httpx.HTTPError as e:
        log.warning("Ответ в WhatsApp не отправлен: %s", e)


# ---------- API для приложения ----------

class StartRequest(BaseModel):
    phone: str


@app.post("/auth/start")
async def start(req: StartRequest, request: Request):
    now = time.time()
    await db.cleanup(now)
    phone = normalize_phone(req.phone)

    client_ip = request.client.host if request.client else "unknown"
    _check_ip_rate_limit(client_ip)

    recent = await db.count_recent_starts(phone, now - 3600)
    if recent >= MAX_STARTS_PER_HOUR:
        raise HTTPException(429, "Слишком много попыток, попробуйте через час")
    await db.record_start(phone, now)

    sid = secrets.token_urlsafe(16)
    active = await db.active_codes()
    code = new_code(active)
    await db.create_session(sid, phone, code, now + CODE_TTL, now)
    wa_link = f"https://wa.me/{WA_BUSINESS_NUMBER}?text={quote('Код ' + code)}" if WA_BUSINESS_NUMBER else None
    log.info("Новый вход: +%s, код %s", phone, code)
    return {"session_id": sid, "code": code, "wa_link": wa_link, "expires_in": CODE_TTL}


@app.get("/auth/status/{sid}")
async def status(sid: str):
    await db.cleanup(time.time())
    s = await db.get_session(sid)
    if not s:
        raise HTTPException(410, "Сессия истекла, начните заново")
    if not s["verified"]:
        return {"verified": False}
    try:
        user_id, password = await ensure_matrix_user(s["phone"])
    except HTTPException:
        # Намеренно НЕ удаляем сессию здесь: если Synapse на мгновение
        # недоступен, подтверждённый номер не должен теряться — приложение
        # сможет повторить запрос статуса без повторного ввода кода.
        raise
    await db.delete_session(sid)  # логин и пароль выдаются один раз
    return {"verified": True, "user_id": user_id, "password": password}


# ---------- webhook WhatsApp (Meta) ----------

@app.get("/auth/webhook")
async def webhook_verify(request: Request):
    """Meta проверяет адрес webhook при его подключении."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == WA_VERIFY_TOKEN and WA_VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Неверный verify token")


@app.post("/auth/webhook")
async def webhook(request: Request):
    raw = await request.body()
    if WA_APP_SECRET:
        expected = "sha256=" + hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(403, "Неверная подпись")
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") != "text":
                    continue
                sender = msg.get("from", "")
                try:
                    ok = await handle_incoming(sender, msg["text"].get("body", ""))
                except HTTPException:
                    continue
                if ok:
                    await send_whatsapp_text(sender, "Номер подтверждён. Вернитесь в приложение.")
    return {"status": "ok"}  # Meta ждёт ответ 200, иначе будет повторять


# ---------- тестовый режим (без WhatsApp) ----------

class DevMessage(BaseModel):
    phone: str
    text: str


@app.post("/auth/dev/message")
async def dev_message(msg: DevMessage):
    """Имитирует сообщение в WhatsApp. Работает только при DEV_MODE=true."""
    if not DEV_MODE:
        raise HTTPException(404, "Not found")
    return {"verified": await handle_incoming(msg.phone, msg.text)}


@app.get("/auth/health")
async def health():
    return {"ok": True, "dev_mode": DEV_MODE, "whatsapp_number_set": bool(WA_BUSINESS_NUMBER)}
