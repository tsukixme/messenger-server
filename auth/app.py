"""
Сервис входа по номеру телефона с подтверждением через WhatsApp.

Схема ("обратная" проверка, бесплатно):
  1. Приложение -> POST /auth/start {phone}        -> получает код и ссылку wa.me
  2. Пользователь отправляет код в WhatsApp на номер компании
  3. Meta -> POST /auth/webhook                     -> сервис видит номер отправителя и код
  4. Приложение опрашивает GET /auth/status/{id}    -> получает логин и пароль Matrix
  5. Приложение входит в Synapse обычным логином

Данные хранятся в памяти: после перезапуска незавершённые входы сбрасываются (для пилота нормально).
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("auth")

SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
SERVER_NAME = os.environ.get("SERVER_NAME", "")
ADMIN_TOKEN = os.environ.get("SYNAPSE_ADMIN_TOKEN", "")
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"

WA_BUSINESS_NUMBER = re.sub(r"\D", "", os.environ.get("WA_BUSINESS_NUMBER", ""))
WA_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.environ.get("WA_APP_SECRET", "")
WA_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")

CODE_TTL = 10 * 60          # код живёт 10 минут
MAX_STARTS_PER_HOUR = 5     # не больше 5 попыток входа с одного номера в час

sessions: dict[str, dict] = {}       # session_id -> {phone, code, expires, verified}
starts: dict[str, list[float]] = {}  # phone -> время попыток

app = FastAPI(title="WhatsApp login for Matrix (pilot)")


# ---------- вспомогательное ----------

def normalize_phone(raw: str) -> str:
    """'8 701 123-45-67', '+7 701...', '701...' -> '77011234567'."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 11 <= len(digits) <= 15:
        raise HTTPException(400, "Неверный номер телефона")
    return digits


def cleanup() -> None:
    now = time.time()
    for sid in [s for s, v in sessions.items() if v["expires"] < now]:
        del sessions[sid]


def new_code() -> str:
    active = {v["code"] for v in sessions.values()}
    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in active:
            return code


def handle_incoming(sender: str, text: str) -> bool:
    """Сообщение пришло в WhatsApp: ищем в нём код и сверяем номер отправителя."""
    cleanup()
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text or "")
    if not match:
        return False
    code = match.group(1)
    sender = normalize_phone(sender)
    for sid, s in sessions.items():
        if s["code"] == code and not s["verified"]:
            if s["phone"] == sender:
                s["verified"] = True
                log.info("Номер %s подтверждён (сессия %s)", sender, sid[:8])
                return True
            log.warning("Код %s пришёл с чужого номера %s", code, sender)
            return False
    return False


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
async def start(req: StartRequest):
    cleanup()
    phone = normalize_phone(req.phone)
    now = time.time()
    recent = [t for t in starts.get(phone, []) if now - t < 3600]
    if len(recent) >= MAX_STARTS_PER_HOUR:
        raise HTTPException(429, "Слишком много попыток, попробуйте через час")
    starts[phone] = recent + [now]

    sid = secrets.token_urlsafe(16)
    code = new_code()
    sessions[sid] = {"phone": phone, "code": code, "expires": now + CODE_TTL, "verified": False}
    wa_link = f"https://wa.me/{WA_BUSINESS_NUMBER}?text={quote('Код ' + code)}" if WA_BUSINESS_NUMBER else None
    log.info("Новый вход: +%s, код %s", phone, code)
    return {"session_id": sid, "code": code, "wa_link": wa_link, "expires_in": CODE_TTL}


@app.get("/auth/status/{sid}")
async def status(sid: str):
    cleanup()
    s = sessions.get(sid)
    if not s:
        raise HTTPException(410, "Сессия истекла, начните заново")
    if not s["verified"]:
        return {"verified": False}
    del sessions[sid]  # логин и пароль выдаются один раз
    user_id, password = await ensure_matrix_user(s["phone"])
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
                    ok = handle_incoming(sender, msg["text"].get("body", ""))
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
    return {"verified": handle_incoming(msg.phone, msg.text)}


@app.get("/auth/health")
async def health():
    return {"ok": True, "dev_mode": DEV_MODE, "whatsapp_number_set": bool(WA_BUSINESS_NUMBER)}
