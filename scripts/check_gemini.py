"""Изолированная проверка Gemini API (этап 3, шаг 3.4).

Не подключена к Люсе и ничего в ней не меняет. Берёт ключ из Диспетчера
учётных данных Windows (secret_store) и проверяет:
  1. авторизацию и список моделей;
  2. ответ на русском с системной инструкцией и диалогом из нескольких реплик;
  3. неверный ключ;
  4. несуществующую модель;
  5. таймаут;
  6. отсутствие сети.
Превышение квоты здесь не вызывается нарочно (для этого пришлось бы
засыпать API запросами) — его обработка проверяется в тестах адаптера.

Ключ передаётся в заголовке x-goog-api-key, а не в адресе запроса,
и нигде не печатается.

Запуск из папки проекта:
    python scripts/check_gemini.py
"""

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secret_store import SecretStore  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"
# Стабильные текстовые модели из документации (ai.google.dev/gemini-api/docs/models, 31.10.2026)
CANDIDATES = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite"]


def request(method: str, url: str, key: str, body: dict | None = None, timeout: float = 30):
    """HTTP-запрос. Возвращает (код, JSON). Ошибки сети пробрасываются."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}


def error_summary(payload: dict, key: str) -> str:
    err = payload.get("error", payload)
    text = f"{err.get('status') or err.get('code')}: {err.get('message', '')}"[:200]
    return text.replace(key, "<ключ>")  # на всякий случай: ключ не должен попасть в вывод


def generate_body():
    return {
        "systemInstruction": {"parts": [{"text": "Ты — Люся, голосовая помощница. Отвечай по-русски, "
                                                 "одним-двумя короткими предложениями."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Привет! Как тебя зовут?"}]},
            {"role": "model", "parts": [{"text": "Я Люся."}]},
            {"role": "user", "parts": [{"text": "Сколько лап у двух собак? Ответь числом и коротко поясни."}]},
        ],
    }


def main() -> int:
    key = SecretStore().get("gemini_api_key")
    if not key:
        print("Ключ не найден. Сохрани его: python secret_store.py set gemini_api_key")
        return 1
    ok = True

    print("1) Авторизация и список моделей")
    status, payload = request("GET", f"{BASE}/models?pageSize=1000", key)
    if status != 200:
        print(f"   ОШИБКА {status} — {error_summary(payload, key)}")
        return 1
    models = {m["name"].removeprefix("models/"): m for m in payload.get("models", [])}
    print(f"   ОК: доступно моделей — {len(models)}")
    for name in CANDIDATES:
        m = models.get(name)
        if m:
            print(f"   • {name}: generateContent={'generateContent' in m.get('supportedGenerationMethods', [])}, "
                  f"вход до {m.get('inputTokenLimit')} токенов, выход до {m.get('outputTokenLimit')}")
        else:
            print(f"   • {name}: нет в списке для этого ключа")
    available = [n for n in CANDIDATES if n in models]

    print("2) Ответ на русском (системная инструкция + диалог)")
    for name in available[:2]:
        started = time.monotonic()
        status, payload = request("POST", f"{BASE}/models/{name}:generateContent", key, generate_body())
        took = time.monotonic() - started
        if status == 200:
            parts = payload["candidates"][0]["content"]["parts"]
            answer = "".join(p.get("text", "") for p in parts).strip()
            usage = payload.get("usageMetadata", {})
            print(f"   ОК {name} за {took:.1f} с, токенов: вход {usage.get('promptTokenCount')}, "
                  f"выход {usage.get('candidatesTokenCount')}")
            print(f"     ответ: {answer}")
        else:
            ok = False
            print(f"   ОШИБКА {name} {status} — {error_summary(payload, key)}")

    print("3) Неверный ключ")
    bad = "AQ.invalid-key-for-lyusya-check"  # в заголовке HTTP допустима только латиница
    status, payload = request("POST", f"{BASE}/models/{available[0]}:generateContent", bad, generate_body())
    print(f"   код {status} — {error_summary(payload, bad)}")

    print("4) Несуществующая модель")
    status, payload = request("POST", f"{BASE}/models/gemini-no-such-model:generateContent", key, generate_body())
    print(f"   код {status} — {error_summary(payload, key)}")

    print("5) Таймаут (ждём 0,01 с)")
    try:
        request("POST", f"{BASE}/models/{available[0]}:generateContent", key, generate_body(), timeout=0.01)
        print("   ответ успел прийти — таймаут не сработал")
    except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
        print(f"   сработал: {type(e).__name__}: {str(getattr(e, 'reason', e))[:80]}")

    print("6) Нет сети (несуществующий адрес)")
    try:
        request("GET", "https://generativelanguage.invalid/v1beta/models", key, timeout=5)
        print("   неожиданно ответил")
    except urllib.error.URLError as e:
        print(f"   сработал: URLError: {str(e.reason)[:80]}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
