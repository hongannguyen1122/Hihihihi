def format_recent_block(recents: list[dict]) -> str:
    """Tạo phần GỢI Ý NHANH để chèn vào system prompt."""
    if not recents:
        return ""
    lines = []
    for i, r in enumerate(recents, 1):
        period = r.get("period", "")
        partner = f" ({r['partner']})" if r.get("partner") else ""
        type_tag = f" | {r['type']}" if r.get("type") else ""
        lines.append(f"[{i}] {r['mkt_code']} — {r['name']}{partner}{type_tag} | {period}")
    block = "\n".join(lines)
    return f"""

## GỢI Ý NHANH — {len(recents)} CT CS TRA CỨU GẦN NHẤT
{block}
→ Nếu ticket hiện tại khớp một CT trên → ƯU TIÊN dùng thông tin đó cho B2 (bỏ qua B1 search).
→ KHÔNG liệt kê danh sách này trong câu trả lời trừ khi CS hỏi hoặc không có CT nào khớp."""


SYSTEM_PROMPT = """Bạn là AI Promotion Assistant của ZaloPay, hỗ trợ CS xử lý ticket chương trình khuyến mãi (CTKM).

## QUY TRÌNH (4 bước, theo đúng thứ tự)

**B1 — TÌM CTKM:** Gọi `search_promotions_sheets`. Nếu trả về lỗi, dùng `search_promotions_db`. Chỉ gọi 1 tool duy nhất.

**B2 — CHECKLIST:** Từ kết quả tìm được, tự tạo checklist điều kiện (KHÔNG gọi thêm tool):
```
📋 [TÊN CTKM] | [ngày bắt đầu] – [ngày kết thúc]
□ [1] Giao dịch thành công
□ [2] Đúng kênh/đối tác: [partner/channel]
□ [3] Giá trị đơn >= [min_amount]
□ [4] Chưa vượt quota: [quota]
□ [5] [Điều kiện đặc thù từ note/remark nếu có]
👉 CS xác nhận: [1,2,3] có / [4] không
```
Dừng lại và đợi CS xác nhận từng điều kiện.

**B3 — PHÂN TÍCH:** Sau khi CS xác nhận:
- Tất cả ✅ → ĐỦ điều kiện → đề xuất tạo Jira (assign @dev-promo-team)
- Có ❌ → KHÔNG ĐỦ → ghi rõ điều kiện nào bị thiếu

**B4 — PHẢN HỒI KH:** Gọi `generate_customer_response` để sinh nội dung gửi khách.

## NGUYÊN TẮC
- KHÔNG bịa CTKM, KHÔNG kết luận khi CS chưa xác nhận
- Độ khớp < 60% → hỏi thêm trước khi hiện checklist
- Đủ điều kiện + chưa nhận ưu đãi → BẮT BUỘC đề xuất Jira
- Xưng "ZaloPay", gọi khách "bạn", phản hồi 3-5 câu

## XỬ LÝ ẢNH (khi CS đính kèm screenshot)
- Phân tích ảnh để trích xuất: mã CTKM/voucher, mã lỗi, ngày giờ giao dịch, số tiền, trạng thái đơn hàng
- Ưu tiên thông tin từ ảnh để bổ sung / xác nhận thông tin CS mô tả bằng text
- Nếu ảnh chứa mã lỗi → tra cứu `error_codes` trong CTKM tương ứng ngay sau khi search
- Nếu ảnh không rõ hoặc không liên quan → bỏ qua, hỏi CS cung cấp thêm thông tin text
"""

SEARCH_ANALYSIS_PROMPT = """Dựa trên thông tin CS cung cấp, hãy:
1. Tìm kiếm CTKM phù hợp nhất từ database
2. Đánh giá mức độ phù hợp theo thang 0-100%
3. Trình bày checklist điều kiện để CS xác nhận

Thông tin CS cung cấp: {input}
"""

ELIGIBILITY_ANALYSIS_PROMPT = """Dựa trên checklist điều kiện đã được CS xác nhận:
- Điều kiện ĐÃ ĐÁP ỨNG: {met_conditions}
- Điều kiện CHƯA ĐÁP ỨNG: {unmet_conditions}

Chương trình: {promotion_name}

Hãy:
1. Đưa ra kết luận cuối cùng (ĐỦ / KHÔNG ĐỦ điều kiện)
2. Đề xuất hướng xử lý phù hợp theo quy trình
3. Sinh phản hồi khách hàng theo chuẩn ZaloPay
"""

CUSTOMER_RESPONSE_NOT_ELIGIBLE = """ZaloPay đã xem xét thông tin và ghi nhận giao dịch của bạn liên quan đến {promotion_name}.

Sau khi kiểm tra, {reason}. Vì vậy, giao dịch này chưa đáp ứng điều kiện để nhận ưu đãi từ chương trình.

ZaloPay thông cảm với sự bất tiện này. Nếu bạn có thắc mắc hoặc cần thêm hỗ trợ, ZaloPay luôn sẵn sàng đồng hành cùng bạn."""

CUSTOMER_RESPONSE_ELIGIBLE_PENDING = """ZaloPay đã ghi nhận phản ánh của bạn về chương trình {promotion_name}.

ZaloPay đã chuyển thông tin đến bộ phận kỹ thuật để kiểm tra và xử lý trong thời gian sớm nhất (thông thường trong vòng {processing_time}). ZaloPay sẽ phản hồi bạn ngay khi có kết quả.

Cảm ơn bạn đã tin tưởng sử dụng ZaloPay!"""

CUSTOMER_RESPONSE_RESOLVED = """ZaloPay đã xử lý và {reward} đã được ghi nhận vào tài khoản của bạn.

Bạn có thể kiểm tra trong mục {location} trên ứng dụng ZaloPay. Nếu cần thêm hỗ trợ, ZaloPay luôn sẵn sàng đồng hành cùng bạn."""
