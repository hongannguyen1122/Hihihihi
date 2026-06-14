"""
Google Sheets reader với 2-layer cache và index tìm kiếm nhanh.

Tầng cache (ưu tiên theo thứ tự):
  1. Memory  — trong process, zero I/O, mất khi restart
  2. File    — data/cache_sheets.json, tồn tại qua restart
  3. API     — Google Drive, chỉ gọi khi cả 2 tầng hết hạn

/refresh-cache trong main.py → invalidate_cache() + fetch_sheet_rows()
"""
import io
import os
import re
import json
import time
from datetime import date, datetime
from typing import Optional

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
CACHE_FILE = os.path.join(DATA_DIR, "cache_sheets.json")
CACHE_TTL  = 86400  # 24 giờ

# ── Google Sheets config ──────────────────────────────────────────────────────
SHEET_ID      = "1kvoprjTNCPo4wPcD9qk5BoA-n7oG5Eup"
TAB_NAME      = "CT ĐANG DIỄN RA"
CREDS_ENV     = "GOOGLE_CREDENTIALS_PATH"
CREDS_DEFAULT = os.path.join(os.path.dirname(__file__), "google-credentials.json")

# ── Cột trong sheet (0-indexed) ──────────────────────────────────────────────
COL_MKT_CODE   = 1
COL_NAME       = 2
COL_PARTNER    = 3
COL_ALT_NAME   = 4
COL_START_DATE = 5
COL_END_DATE   = 6
COL_TYPE       = 7
COL_TARGET     = 8
COL_RISK       = 9
COL_NOTE       = 10
COL_PROMO_CODE = 11
COL_CHANNEL    = 12
COL_QUOTA      = 13
COL_AMOUNT     = 14
COL_MIN_AMOUNT = 15
COL_REMARK     = 16
COL_PIC        = 17
COL_STATUS     = 22

# ── In-memory layer ───────────────────────────────────────────────────────────
# Cấu trúc: {"rows": [...], "idx_mkt": {}, "idx_promo": {}, "idx_tokens": {}, "saved_at": float}
_mem: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower())


def _is_fresh(saved_at: float) -> bool:
    return time.time() - saved_at < CACHE_TTL


def _parse_date(val) -> Optional[date]:
    """Parse nhiều định dạng ngày; ưu tiên dòng 'Gia hạn DD/MM/YYYY' nếu có."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()

    gia_han = re.search(r"[Gg]ia\s+h[aạ]n\s+(\d{1,2}/\d{1,2}/\d{4})", s)
    if gia_han:
        try:
            return datetime.strptime(gia_han.group(1), "%d/%m/%Y").date()
        except ValueError:
            pass

    first_line = s.split("\n")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(first_line, fmt).date()
        except ValueError:
            pass
    return None


def _cell(row: tuple, idx: int) -> str:
    try:
        v = row[idx]
        return str(v).strip() if v is not None else ""
    except IndexError:
        return ""


# ── Index builder ─────────────────────────────────────────────────────────────

def _build_indexes(rows: list[dict]) -> dict:
    """
    Xây dựng 3 index để tìm kiếm nhanh:
      idx_mkt    : mkt_code chuẩn hoá  → row index (exact lookup)
      idx_promo  : promo_code chuẩn hoá → row index (exact lookup)
      idx_tokens : token từ name/partner/alt_name → [row indices] (keyword lookup)
    """
    idx_mkt: dict[str, int]             = {}
    idx_promo: dict[str, int]           = {}
    idx_tokens: dict[str, list[int]]    = {}

    for i, p in enumerate(rows):
        mkt = _normalize(p.get("mkt_code", ""))
        if mkt:
            idx_mkt[mkt] = i

        promo = _normalize(p.get("promo_code", ""))
        if promo:
            idx_promo[promo] = i

        text_blob = " ".join([
            p.get("name", ""),
            p.get("partner", ""),
            p.get("alt_name", ""),
        ])
        for token in _normalize(text_blob).split():
            if len(token) >= 2:
                idx_tokens.setdefault(token, []).append(i)

    return {"idx_mkt": idx_mkt, "idx_promo": idx_promo, "idx_tokens": idx_tokens}


# ── File cache ────────────────────────────────────────────────────────────────

def _load_file_cache() -> Optional[dict]:
    """Đọc cache từ file; trả về None nếu không tồn tại, lỗi, hoặc hết hạn."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if _is_fresh(data.get("saved_at", 0)):
            return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def _save_file_cache(rows: list[dict], indexes: dict) -> None:
    """Ghi rows + indexes ra file cache (atomic write qua file tạm)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {"saved_at": time.time(), "rows": rows, **indexes}
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


# ── Public cache API ──────────────────────────────────────────────────────────

def invalidate_cache() -> None:
    """Xóa cả memory cache lẫn file cache; buộc fetch lại từ API lần sau."""
    global _mem
    _mem = None
    try:
        os.remove(CACHE_FILE)
    except FileNotFoundError:
        pass


def cache_status() -> dict:
    """Trả về thông tin trạng thái cache hiện tại."""
    if _mem is not None and _is_fresh(_mem["saved_at"]):
        age = time.time() - _mem["saved_at"]
        return {
            "source": "memory",
            "loaded": True,
            "count": len(_mem["rows"]),
            "age_seconds": round(age),
            "expires_in_seconds": max(0, round(CACHE_TTL - age)),
        }

    file_data = _load_file_cache()
    if file_data:
        age = time.time() - file_data["saved_at"]
        return {
            "source": "file",
            "loaded": True,
            "count": len(file_data["rows"]),
            "age_seconds": round(age),
            "expires_in_seconds": max(0, round(CACHE_TTL - age)),
        }

    return {"source": "none", "loaded": False, "count": 0,
            "age_seconds": None, "expires_in_seconds": None}


# ── Fetch & cache ─────────────────────────────────────────────────────────────

def _get_cache() -> tuple[list[dict], dict]:
    """
    Trả về (rows, indexes) từ tầng cache nhanh nhất còn hợp lệ.
    Thứ tự: memory → file → API.
    """
    global _mem

    # Tầng 1: memory
    if _mem is not None and _is_fresh(_mem["saved_at"]):
        return _mem["rows"], {k: _mem[k] for k in ("idx_mkt", "idx_promo", "idx_tokens")}

    # Tầng 2: file
    file_data = _load_file_cache()
    if file_data:
        _mem = file_data
        return _mem["rows"], {k: _mem[k] for k in ("idx_mkt", "idx_promo", "idx_tokens")}

    # Tầng 3: Google Drive API
    rows = _fetch_from_api()
    indexes = _build_indexes(rows)
    _save_file_cache(rows, indexes)
    _mem = {"rows": rows, "saved_at": time.time(), **indexes}
    return rows, indexes


def fetch_sheet_rows() -> list[dict]:
    """Trả về danh sách CTKM (dùng cache nếu còn hợp lệ)."""
    rows, _ = _get_cache()
    return rows


def _fetch_from_api() -> list[dict]:
    """Download .xlsx từ Google Drive và parse tab TAB_NAME."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import openpyxl

    creds_path = os.environ.get(CREDS_ENV, CREDS_DEFAULT)
    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    drive = build("drive", "v3", credentials=creds)
    raw   = drive.files().get_media(fileId=SHEET_ID).execute()
    wb    = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    ws    = wb[TAB_NAME]

    rows_raw = list(ws.iter_rows(values_only=True))
    if not rows_raw:
        return []

    promos = []
    for row in rows_raw[1:]:
        mkt_code = _cell(row, COL_MKT_CODE)
        name     = _cell(row, COL_NAME)
        if not mkt_code and not name:
            continue

        start = _parse_date(row[COL_START_DATE] if len(row) > COL_START_DATE else None)
        end   = _parse_date(row[COL_END_DATE]   if len(row) > COL_END_DATE   else None)

        promos.append({
            "mkt_code":   mkt_code,
            "name":       name,
            "partner":    _cell(row, COL_PARTNER),
            "alt_name":   _cell(row, COL_ALT_NAME),
            "promo_code": _cell(row, COL_PROMO_CODE),
            "start_date": start.isoformat() if start else "",
            "end_date":   end.isoformat()   if end   else "",
            "type":       _cell(row, COL_TYPE),
            "target":     _cell(row, COL_TARGET),
            "risk":       _cell(row, COL_RISK),
            "channel":    _cell(row, COL_CHANNEL),
            "quota":      _cell(row, COL_QUOTA),
            "amount":     _cell(row, COL_AMOUNT),
            "min_amount": _cell(row, COL_MIN_AMOUNT),
            "note":       _cell(row, COL_NOTE),
            "remark":     _cell(row, COL_REMARK),
            "pic":        _cell(row, COL_PIC),
            "status":     _cell(row, COL_STATUS),
        })

    return promos


# ── Search ────────────────────────────────────────────────────────────────────

def search_promotions(query: str, transaction_date: Optional[str] = None) -> list[dict]:
    """
    Tìm kiếm CTKM từ Google Sheet.

    Dùng index để tìm candidates trước, chỉ score trên tập nhỏ đó.
    Fallback về substring scan nếu index không ra kết quả.

    Scoring:
      Promo code khớp    +50
      MKT code khớp      +40
      Tên/đối tác khớp   +30 × tỉ_lệ_từ
      Trong thời gian    +10  /  ngoài thời gian  −20
    """
    rows, indexes = _get_cache()
    if not rows:
        return []

    q_norm   = _normalize(query)
    q_words  = [w for w in q_norm.split() if w]
    tx_date  = _parse_date(transaction_date) if transaction_date else None
    idx_mkt    = indexes["idx_mkt"]
    idx_promo  = indexes["idx_promo"]
    idx_tokens = indexes["idx_tokens"]

    # ── Gom candidates qua index ─────────────────────────────────
    # score_map: row_index → [score, reasons]
    score_map: dict[int, list] = {}

    def _add(i: int, delta: float, reason: str) -> None:
        if i not in score_map:
            score_map[i] = [0.0, []]
        score_map[i][0] += delta
        score_map[i][1].append(reason)

    # Promo code: bất kỳ promo code nào xuất hiện trong query
    for code, i in idx_promo.items():
        if code and code in q_norm:
            _add(i, 50, f"Mã KM khớp: {rows[i]['promo_code']}")

    # MKT code: bất kỳ mkt code nào xuất hiện trong query
    for code, i in idx_mkt.items():
        if code and code in q_norm:
            _add(i, 40, f"MKT code khớp: {rows[i]['mkt_code']}")

    # Token keyword: tra từng query word trong idx_tokens
    token_hits: dict[int, int] = {}
    for w in q_words:
        # Exact token match
        for i in idx_tokens.get(w, []):
            token_hits[i] = token_hits.get(i, 0) + 1
        # Prefix match cho query word dài ≥ 3 ký tự (vd: "game" khớp "gameverse")
        if len(w) >= 3:
            for token, indices in idx_tokens.items():
                if token != w and token.startswith(w):
                    for i in indices:
                        token_hits[i] = token_hits.get(i, 0) + 1

    total_q = len(q_words) or 1
    for i, hits in token_hits.items():
        ratio = min(hits / total_q, 1.0)
        _add(i, ratio * 30, f"Tên khớp {ratio:.0%}")

    # Fallback substring scan khi index không ra candidate nào
    if not score_map and q_norm:
        for i, p in enumerate(rows):
            blob = _normalize(" ".join([p.get("name",""), p.get("partner",""), p.get("alt_name","")]))
            if q_norm in blob:
                _add(i, 15, "Khớp chuỗi con")

    # ── Date filter + threshold ───────────────────────────────────
    results = []
    for i, (score, reasons) in score_map.items():
        p = rows[i]
        if tx_date:
            start = _parse_date(p["start_date"]) if p["start_date"] else None
            end   = _parse_date(p["end_date"])   if p["end_date"]   else None
            if start and end:
                if start <= tx_date <= end:
                    score += 10
                    reasons.append("Trong thời gian CTKM")
                else:
                    score -= 20
                    reasons.append("Ngoài thời gian CTKM")

        if score >= 20:
            results.append({**p, "score": min(round(score), 100), "match_reasons": reasons})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]
