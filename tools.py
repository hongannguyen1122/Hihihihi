import json
import os
import re
from typing import Optional
from langchain_core.tools import tool

import recent_store

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _import_sheets_reader():
    """Lazy import để tránh crash khi thư viện Google chưa cài."""
    try:
        import sheets_reader
        return sheets_reader
    except ImportError:
        return None


def _load_json(filename: str) -> dict:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower())


def _keyword_score(text: str, keywords: list[str]) -> float:
    norm_text = _normalize(text)
    matched = sum(1 for kw in keywords if _normalize(kw) in norm_text)
    return matched / len(keywords) if keywords else 0.0


@tool
def search_promotions_db(query: str, transaction_date: Optional[str] = None) -> str:
    """Tìm kiếm chương trình khuyến mãi từ Promotion Database.

    Args:
        query: Từ khóa tìm kiếm (codename, tên CTKM, keyword, nội dung vấn đề)
        transaction_date: Ngày giao dịch (YYYY-MM-DD), dùng để lọc CTKM còn hiệu lực

    Returns:
        Danh sách CTKM phù hợp với mức độ khớp
    """
    db = _load_json("promotions_db.json")
    results = []

    for promo in db["promotions"]:
        score = 0.0
        match_reasons = []

        # Keyword matching từ description và keywords
        search_keywords = promo.get("keywords", []) + [promo["codename"].lower(), promo["name"].lower()]
        kw_score = _keyword_score(query, search_keywords)
        if kw_score > 0:
            score += kw_score * 60
            match_reasons.append(f"Từ khóa khớp {kw_score:.0%}")

        # Codename exact match
        if promo["codename"].lower() in query.lower():
            score += 40
            match_reasons.append("Codename khớp chính xác")

        # Date filter nếu có transaction_date
        date_valid = True
        if transaction_date:
            try:
                from datetime import date
                tx_date = date.fromisoformat(transaction_date)
                start = date.fromisoformat(promo["start_date"])
                end = date.fromisoformat(promo["end_date"])
                date_valid = start <= tx_date <= end
                if date_valid:
                    score += 10
                    match_reasons.append("Ngày giao dịch trong thời gian CTKM")
                else:
                    score -= 30
                    match_reasons.append("Ngày giao dịch ngoài thời gian CTKM")
            except (ValueError, TypeError):
                pass

        if score > 20:
            results.append({
                "id": promo["id"],
                "codename": promo["codename"],
                "name": promo["name"],
                "score": min(round(score), 100),
                "match_reasons": match_reasons,
                "start_date": promo["start_date"],
                "end_date": promo["end_date"],
                "status": promo["status"],
                "type": promo["type"],
                "description": promo["description"],
                "conditions": promo["conditions"],
                "exclusions": promo["exclusions"],
                "reward": promo["reward"],
                "quota_per_user": promo["quota_per_user"],
                "processing_time": promo["processing_time"],
                "error_codes": promo.get("error_codes", {}),
                "resolution_guides": promo.get("resolution_guides", {}),
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        return json.dumps({
            "status": "not_found",
            "message": "Không tìm thấy CTKM phù hợp. Vui lòng cung cấp thêm thông tin (codename, tên CTKM, thời gian giao dịch).",
            "results": []
        }, ensure_ascii=False, indent=2)

    recent_store.record(results[0])
    return json.dumps({
        "status": "found",
        "total": len(results),
        "results": results[:3]
    }, ensure_ascii=False, indent=2)


@tool
def search_faq_cs(query: str) -> str:
    """Tìm kiếm hướng xử lý từ FAQ CS nội bộ.

    Args:
        query: Mô tả vấn đề hoặc keyword cần tìm

    Returns:
        FAQ entries phù hợp với hướng xử lý
    """
    faq_db = _load_json("faq_cs.json")
    results = []

    for faq in faq_db["faqs"]:
        keywords = faq.get("keywords", [])
        score = _keyword_score(query, keywords)
        if score > 0:
            results.append({
                "id": faq["id"],
                "category": faq["category"],
                "question": faq["question"],
                "answer": faq["answer"],
                "resolution_path": faq["resolution_path"],
                "score": round(score * 100)
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        return json.dumps({
            "status": "not_found",
            "message": "Không tìm thấy FAQ phù hợp.",
            "results": []
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "status": "found",
        "results": results[:3]
    }, ensure_ascii=False, indent=2)


@tool
def search_confluence(query: str, codename: Optional[str] = None) -> str:
    """Tìm kiếm tài liệu setup và vận hành CTKM từ Confluence.

    Args:
        query: Từ khóa tìm kiếm
        codename: Codename CTKM cụ thể (nếu có)

    Returns:
        Tài liệu Confluence liên quan
    """
    confluence_db = _load_json("confluence_docs.json")
    results = []

    for doc in confluence_db["documents"]:
        score = 0.0
        keywords = doc.get("keywords", [])
        kw_score = _keyword_score(query, keywords)
        score += kw_score * 70

        if codename and codename.lower() in doc["title"].lower():
            score += 30

        if score > 15:
            results.append({
                "id": doc["id"],
                "title": doc["title"],
                "page_id": doc["page_id"],
                "content": doc["content"],
                "last_updated": doc["last_updated"],
                "owner": doc["owner"],
                "score": round(score)
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        return json.dumps({
            "status": "not_found",
            "message": "Không tìm thấy tài liệu Confluence phù hợp.",
            "results": []
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "status": "found",
        "results": results[:2]
    }, ensure_ascii=False, indent=2)


@tool
def get_promotion_detail(promotion_id: str) -> str:
    """Lấy thông tin chi tiết đầy đủ của một CTKM theo ID.

    Args:
        promotion_id: ID của CTKM (ví dụ: GAMEVERSE_2025_06)

    Returns:
        Thông tin đầy đủ của CTKM bao gồm điều kiện, quota, hướng xử lý
    """
    db = _load_json("promotions_db.json")

    for promo in db["promotions"]:
        if promo["id"] == promotion_id or promo["codename"] == promotion_id:
            return json.dumps({
                "status": "found",
                "promotion": promo
            }, ensure_ascii=False, indent=2)

    return json.dumps({
        "status": "not_found",
        "message": f"Không tìm thấy CTKM với ID: {promotion_id}"
    }, ensure_ascii=False, indent=2)


@tool
def format_conditions_checklist(promotion_id: str) -> str:
    """Tạo checklist điều kiện của CTKM để CS xác nhận từng điều kiện.

    Args:
        promotion_id: ID hoặc codename của CTKM

    Returns:
        Checklist điều kiện có đánh số để CS dễ xác nhận
    """
    db = _load_json("promotions_db.json")

    promo = None
    for p in db["promotions"]:
        if p["id"] == promotion_id or p["codename"] == promotion_id:
            promo = p
            break

    if not promo:
        return json.dumps({
            "status": "error",
            "message": f"Không tìm thấy CTKM: {promotion_id}"
        }, ensure_ascii=False)

    checklist_items = []
    for i, condition in enumerate(promo["conditions"], 1):
        checklist_items.append(f"□ [{i}] {condition}")

    checklist_text = "\n".join(checklist_items)

    result = {
        "status": "success",
        "promotion_id": promo["id"],
        "promotion_name": promo["name"],
        "codename": promo["codename"],
        "period": f"{promo['start_date']} → {promo['end_date']}",
        "reward": promo["reward"],
        "processing_time": promo["processing_time"],
        "checklist": checklist_items,
        "checklist_display": f"""
📋 CHECKLIST ĐIỀU KIỆN - {promo['name']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{checklist_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  Điều kiện LOẠI TRỪ:
""" + "\n".join(f"   • {excl}" for excl in promo["exclusions"]) + """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👉 CS vui lòng xác nhận từng điều kiện theo số thứ tự
   Ví dụ: [1]✅ [2]✅ [3]❌ [4]✅ [5]✅
"""
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def analyze_eligibility_and_suggest(
    promotion_id: str,
    met_conditions: list[int],
    unmet_conditions: list[int],
    error_code: Optional[str] = None
) -> str:
    """Phân tích kết quả điều kiện và đề xuất hướng xử lý phù hợp.

    Args:
        promotion_id: ID hoặc codename CTKM
        met_conditions: Danh sách số thứ tự điều kiện ĐÃ đáp ứng [1,2,4,5]
        unmet_conditions: Danh sách số thứ tự điều kiện CHƯA đáp ứng [3]
        error_code: Mã lỗi hệ thống nếu có (ví dụ: GV005)

    Returns:
        Kết luận phân tích và hướng xử lý đề xuất
    """
    db = _load_json("promotions_db.json")

    promo = None
    for p in db["promotions"]:
        if p["id"] == promotion_id or p["codename"] == promotion_id:
            promo = p
            break

    if not promo:
        return json.dumps({
            "status": "error",
            "message": f"Không tìm thấy CTKM: {promotion_id}"
        }, ensure_ascii=False)

    conditions = promo["conditions"]
    is_eligible = len(unmet_conditions) == 0
    resolution_guides = promo.get("resolution_guides", {})
    error_codes_map = promo.get("error_codes", {})

    # Xác định hướng xử lý
    resolution = ""
    resolution_type = ""

    if error_code and error_code in error_codes_map:
        error_desc = error_codes_map[error_code]
        if "Jira" in error_desc or "lỗi hệ thống" in error_desc.lower():
            resolution_type = "create_jira"
            resolution = f"⚠️ Mã lỗi {error_code}: {error_desc}\n→ Tạo Jira ticket PRIORITY HIGH cho Dev team kiểm tra ngay."
        else:
            resolution_type = "explain_error"
            resolution = f"Mã lỗi {error_code}: {error_desc}"
    elif is_eligible:
        resolution_type = "create_jira"
        resolution = (
            f"✅ Khách hàng ĐỦ điều kiện tham gia {promo['name']}.\n"
            f"→ Tuy nhiên chưa nhận được ưu đãi.\n"
            f"→ {resolution_guides.get('eligible_not_received', 'Tạo Jira ticket cho Dev kiểm tra hệ thống')}"
        )
    else:
        unmet_texts = [conditions[i-1] for i in unmet_conditions if 0 < i <= len(conditions)]
        resolution_type = "explain_conditions"
        resolution = (
            f"❌ Khách hàng KHÔNG ĐỦ điều kiện do:\n"
            + "\n".join(f"   • {c}" for c in unmet_texts)
            + f"\n→ {resolution_guides.get('not_eligible', 'Giải thích điều kiện cho khách hàng')}"
        )

    met_texts = [conditions[i-1] for i in met_conditions if 0 < i <= len(conditions)]
    unmet_texts_full = [conditions[i-1] for i in unmet_conditions if 0 < i <= len(conditions)]

    return json.dumps({
        "status": "success",
        "promotion_name": promo["name"],
        "is_eligible": is_eligible,
        "met_conditions": met_texts,
        "unmet_conditions": unmet_texts_full,
        "resolution_type": resolution_type,
        "resolution": resolution,
        "jira_required": resolution_type == "create_jira",
        "jira_info": {
            "project": "ZALOPAY-CS-PROMO",
            "type": "Bug" if error_code else "Task",
            "priority": "Critical" if error_code and "GV005" in (error_code or "") else "High",
            "tag": f"promo-{promo['codename'].lower()}",
            "assign": "@dev-promo-team"
        } if resolution_type == "create_jira" else None
    }, ensure_ascii=False, indent=2)


@tool
def generate_customer_response(
    promotion_name: str,
    is_eligible: bool,
    resolution_summary: str,
    processing_time: Optional[str] = None,
    reward_description: Optional[str] = None
) -> str:
    """Sinh nội dung phản hồi khách hàng theo chuẩn văn phong Zalopay.

    Args:
        promotion_name: Tên chương trình khuyến mãi
        is_eligible: True nếu đủ điều kiện, False nếu không đủ
        resolution_summary: Tóm tắt hướng xử lý / lý do không đủ điều kiện
        processing_time: Thời gian xử lý (nếu đủ điều kiện)
        reward_description: Mô tả ưu đãi (nếu cần giải thích)

    Returns:
        Nội dung phản hồi khách hàng sẵn sàng gửi
    """
    if is_eligible:
        response = (
            f"Zalopay đã ghi nhận phản ánh của bạn về chương trình {promotion_name}.\n\n"
            f"Zalopay đã chuyển thông tin đến bộ phận kỹ thuật để kiểm tra và xử lý "
            f"trong thời gian sớm nhất"
            + (f" (thông thường trong vòng {processing_time})" if processing_time else "")
            + ". Zalopay sẽ phản hồi bạn ngay khi có kết quả.\n\n"
            "Cảm ơn bạn đã tin tưởng sử dụng Zalopay!"
        )
    else:
        response = (
            f"Zalopay đã kiểm tra thông tin và ghi nhận giao dịch của bạn liên quan đến "
            f"chương trình {promotion_name}.\n\n"
            f"{resolution_summary}\n\n"
            "Zalopay thông cảm với sự bất tiện này. Nếu bạn có thắc mắc hoặc cần thêm hỗ trợ, "
            "Zalopay luôn sẵn sàng đồng hành cùng bạn."
        )

    return json.dumps({
        "status": "success",
        "customer_response": response,
        "char_count": len(response),
        "tone_check": {
            "uses_zalopay_pronoun": "Zalopay" in response,
            "uses_ban_pronoun": "bạn" in response,
            "has_closing": "đồng hành" in response or "Cảm ơn" in response,
            "professional": True
        }
    }, ensure_ascii=False, indent=2)


@tool
def search_promotions_sheets(query: str, transaction_date: Optional[str] = None) -> str:
    """Tìm kiếm chương trình khuyến mãi từ Google Sheets (dữ liệu thực tế, real-time).
    Ưu tiên dùng tool này trước search_promotions_db vì dữ liệu luôn mới nhất.

    Args:
        query: Từ khóa tìm kiếm — mã voucher, tên CTKM, tên đối tác, keyword
        transaction_date: Ngày giao dịch dạng YYYY-MM-DD để lọc CTKM còn hiệu lực

    Returns:
        Danh sách CTKM phù hợp kèm thông tin chi tiết lấy trực tiếp từ sheet
    """
    sr = _import_sheets_reader()
    if sr is None:
        return json.dumps({
            "status": "error",
            "message": (
                "Thư viện google-api-python-client / openpyxl chưa được cài. "
                "Dùng search_promotions_db để thay thế."
            )
        }, ensure_ascii=False)

    try:
        results = sr.search_promotions(query, transaction_date)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Lỗi đọc Google Sheet: {exc}. Dùng search_promotions_db để thay thế.",
        }, ensure_ascii=False)

    if not results:
        return json.dumps({
            "status": "not_found",
            "message": (
                "Không tìm thấy CTKM phù hợp trong sheet. "
                "Thử với từ khóa khác hoặc kiểm tra mã voucher."
            ),
            "results": []
        }, ensure_ascii=False, indent=2)

    # Format kết quả thân thiện với agent
    formatted = []
    for r in results:
        formatted.append({
            "mkt_code":    r["mkt_code"],
            "name":        r["name"],
            "partner":     r["partner"],
            "promo_code":  r["promo_code"],
            "period":      f"{r['start_date']} → {r['end_date']}",
            "type":        r["type"],
            "target":      r["target"],
            "quota":       r["quota"],
            "amount":      r["amount"],
            "min_amount":  r["min_amount"],
            "channel":     r["channel"],
            "note":        r["note"],
            "remark":      r["remark"],
            "status":      r["status"],
            "score":       r["score"],
            "match_reasons": r["match_reasons"],
        })

    recent_store.record(formatted[0])
    return json.dumps({
        "status": "found",
        "source": "Google Sheets (real-time)",
        "total": len(formatted),
        "results": formatted
    }, ensure_ascii=False, indent=2)


@tool
def get_recent_promotions() -> str:
    """Lấy danh sách 5 chương trình khuyến mãi CS tra cứu gần nhất làm gợi ý nhanh.

    Returns:
        Danh sách CTKM gần nhất kèm thời gian tra cứu
    """
    recents = recent_store.get_recent()
    if not recents:
        return json.dumps({
            "status": "empty",
            "message": "Chưa có CT nào được tra cứu gần đây.",
            "results": []
        }, ensure_ascii=False)

    return json.dumps({
        "status": "found",
        "message": f"Đây là {len(recents)} CTKM được CS tra cứu gần nhất:",
        "results": recents,
    }, ensure_ascii=False, indent=2)


def get_all_tools():
    # 3 tools thay vì 8: mỗi turn agent tối đa 1-2 tool call thay vì 4-5.
    # search_faq_cs / search_confluence / get_promotion_detail /
    # format_conditions_checklist / analyze_eligibility_and_suggest
    # được bỏ khỏi tool list — LLM suy luận trực tiếp từ kết quả search.
    return [
        get_recent_promotions,      # B0: gợi ý nhanh 5 CT gần nhất
        search_promotions_sheets,   # B1 primary: real-time Google Sheets
        search_promotions_db,       # B1 fallback: JSON tĩnh nếu Sheets lỗi
        generate_customer_response, # B4: sinh phản hồi khách hàng
    ]
