# Zalopay CS Promotion Assistant

AI Agent hỗ trợ Customer Service Zalopay xử lý các yêu cầu liên quan đến chương trình khuyến mãi (CTKM).

## Tính năng

| Bước | Chức năng |
|------|-----------|
| 1 | Phân tích thông tin đầu vào (text + hình ảnh OCR) |
| 2 | Tìm kiếm CTKM từ Promotion DB, FAQ CS, Confluence |
| 3 | Hiển thị checklist điều kiện cho CS xác nhận |
| 4 | Phân tích eligibility & đề xuất hướng xử lý |
| 5 | Sinh phản hồi khách hàng theo chuẩn Zalopay |

## Cài đặt

```bash
cd "C:/CS assistant/zalopay-cs-agent"

# Tạo virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Cài dependencies
pip install -r requirements.txt

# Tạo file .env từ template
copy .env.example .env
# Điền LLM_API_KEY, LLM_BASE_URL, LLM_MODEL vào .env
```

## Chạy thử (CLI mode)

```bash
python main.py
```

Ví dụ tương tác:

```
[CS] Khách tham gia GAMEVERSE nhưng chưa nhận mã dự thưởng.
     Giao dịch ngày 2025-06-10, thanh toán game 80k, đã eKYC.

[AI] 🔍 Đã tìm thấy CTKM phù hợp: GAMEVERSE (Độ khớp: 95%)
     ...
     📋 CHECKLIST ĐIỀU KIỆN - Zalopay GAMEVERSE
     □ [1] Giao dịch thanh toán game thành công qua Zalopay
     □ [2] Giá trị giao dịch tối thiểu 50.000 VNĐ
     □ [3] User đã xác thực eKYC
     □ [4] Tài khoản không bị khóa/hạn chế
     □ [5] Chưa nhận mã trong ngày (quota: 1 mã/user/ngày)
     □ [6] Ứng dụng Zalopay phiên bản 6.0 trở lên
     👉 CS vui lòng xác nhận từng điều kiện...

[CS] [1]✅ [2]✅ [3]✅ [4]✅ [5]✅ [6] chưa biết

[AI] ⚖️ KẾT LUẬN: Cần xác thêm điều kiện [6]...
     ...
     💬 PHẢN HỒI KHÁCH HÀNG: Zalopay đã ghi nhận...
```

## Deploy lên GreenNode AgentBase

```bash
# 1. Setup credentials
cp .env.example .env
# Điền GREENNODE_CLIENT_ID, GREENNODE_CLIENT_SECRET

# 2. Build Docker image
docker build --platform linux/amd64 -t zalopay-cs-agent:latest .

# 3. Push lên Container Registry
docker tag zalopay-cs-agent:latest <registry>/zalopay-cs-agent:latest
docker push <registry>/zalopay-cs-agent:latest

# 4. Deploy Runtime
/agentbase-deploy deploy

# 5. Monitor
/agentbase-monitor runtime-logs <runtime-id>
```

## Cấu trúc project

```
zalopay-cs-agent/
├── main.py              # Entry point (LangGraph + GreenNodeAgentBaseApp)
├── tools.py             # Tool implementations (search, analyze, generate)
├── prompts.py           # System prompts & templates tiếng Việt
├── data/
│   ├── promotions_db.json   # Promotion Database (sample)
│   ├── faq_cs.json          # FAQ CS nội bộ (sample)
│   └── confluence_docs.json # Confluence docs (sample)
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## Nguyên tắc hoạt động

- AI chỉ dùng dữ liệu từ nguồn nội bộ (Promotion DB, FAQ, Confluence)
- Không tự suy diễn hoặc bịa thông tin CTKM
- Bắt buộc yêu cầu CS xác nhận checklist trước khi kết luận
- Nếu đủ điều kiện nhưng chưa nhận ưu đãi → đề xuất tạo Jira Dev
- Phản hồi khách hàng theo chuẩn: xưng Zalopay, gọi khách là "bạn"

## Mở rộng production

Thay thế dữ liệu sample bằng:
- `promotions_db.json` → Kết nối API Promotion Service thực tế
- `faq_cs.json` → Kết nối Zendesk/CRM knowledge base
- `confluence_docs.json` → Kết nối Confluence REST API
- Thêm vector search (FAISS/Pinecone) cho semantic search chính xác hơn
