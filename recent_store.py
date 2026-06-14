"""
Lưu trữ 5 chương trình khuyến mãi CS tra cứu gần nhất.
"""
import json
import os
import time
from threading import Lock

_STORE_PATH = os.path.join(os.path.dirname(__file__), "data", "recent_promotions.json")
_MAX = 5
_lock = Lock()


def _load() -> list[dict]:
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(recents: list[dict]) -> None:
    try:
        with open(_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(recents, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def record(promo: dict) -> None:
    """Ghi nhận CTKM vừa được tra cứu vào danh sách gần nhất."""
    key = promo.get("mkt_code") or promo.get("codename") or promo.get("id") or promo.get("name")
    if not key:
        return
    entry = {
        "mkt_code":    promo.get("mkt_code") or promo.get("codename", ""),
        "name":        promo.get("name", ""),
        "partner":     promo.get("partner", ""),
        "period":      (
            promo.get("period")
            or f"{promo.get('start_date', '')} → {promo.get('end_date', '')}"
        ).strip(" →"),
        "type":        promo.get("type", ""),
        "accessed_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    with _lock:
        recents = _load()
        recents = [r for r in recents if r.get("mkt_code") != entry["mkt_code"]]
        recents.insert(0, entry)
        _save(recents[:_MAX])


def get_recent(n: int = 5) -> list[dict]:
    """Trả về tối đa n CTKM được tra cứu gần nhất."""
    return _load()[:n]
