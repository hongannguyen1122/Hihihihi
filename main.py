import os
from typing import Annotated, Optional, Any
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from flask import Flask, request, jsonify, send_from_directory

from tools import get_all_tools
from prompts import SYSTEM_PROMPT, format_recent_block
import recent_store

try:
    import sheets_reader as _sr
    _HAS_SHEETS = True
except ImportError:
    _HAS_SHEETS = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─── Paths ────────────────────────────────────────────────────────────────────

_STATIC_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_RECENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recent_promotions.json")


# ─── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ─── LLM + Graph ──────────────────────────────────────────────────────────────

_GN_MAAS_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
_GN_MAAS_MODEL    = "qwen/qwen3-5-27b"

def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", _GN_MAAS_MODEL),
        base_url=os.getenv("LLM_BASE_URL", _GN_MAAS_BASE_URL),
        api_key=os.getenv("LLM_API_KEY", ""),
        temperature=0.1,
        max_tokens=4096,
    )


def make_chatbot_node(llm_with_tools):
    def chatbot(state: AgentState) -> AgentState:
        recents = recent_store.get_recent()
        system_content = SYSTEM_PROMPT + format_recent_block(recents)
        messages = [SystemMessage(content=system_content)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
    return chatbot


def build_graph(llm: ChatOpenAI, memory: MemorySaver) -> Any:
    tools = get_all_tools()
    llm_with_tools = llm.bind_tools(tools)
    graph = StateGraph(AgentState)
    graph.add_node("chatbot", make_chatbot_node(llm_with_tools))
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", tools_condition)
    graph.add_edge("tools", "chatbot")
    return graph.compile(checkpointer=memory)


memory_store = MemorySaver()
_llm: Optional[ChatOpenAI] = None
_graph: Optional[Any] = None


def get_graph() -> Any:
    global _llm, _graph
    if _graph is None:
        _llm = build_llm()
        _graph = build_graph(_llm, memory_store)
    return _graph


# ─── Message builder ──────────────────────────────────────────────────────────

def build_user_message(payload: dict) -> HumanMessage:
    text       = payload.get("message", "").strip()
    image_data = payload.get("image")
    if image_data:
        image_url = (
            image_data if image_data.startswith("data:")
            else f"data:image/jpeg;base64,{image_data}"
        )
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url, "detail": "high"},
        })
        return HumanMessage(content=content)
    return HumanMessage(content=text or "(Không có nội dung)")


def extract_last_response(result: dict) -> str:
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, str):
                return msg.content
            if isinstance(msg.content, list):
                texts = [c.get("text", "") for c in msg.content
                         if isinstance(c, dict) and c.get("type") == "text"]
                return "\n".join(texts)
    return "Không thể tạo phản hồi. Vui lòng thử lại."


# ─── Slash command handler ─────────────────────────────────────────────────────

def handle_slash_command(text: str) -> Optional[str]:
    cmd = text.strip().lower()
    if not cmd.startswith("/"):
        return None
    if cmd.startswith("/refresh-cache"):
        if not _HAS_SHEETS:
            return "⚠️ Google Sheets chưa được cài đặt, không có cache để refresh."
        try:
            _sr.invalidate_cache()
            _sr.fetch_sheet_rows()
            status = _sr.cache_status()
            return (
                f"✅ **Cache đã được làm mới thành công.**\n\n"
                f"- Đã tải **{status['count']} chương trình khuyến mãi** từ Google Sheets\n"
                f"- Đã lưu vào **file cache** — giữ nguyên khi khởi động lại server\n"
                f"- Cache hợp lệ trong **24 giờ** tới\n"
                f"- Dùng `/refresh-cache` bất kỳ lúc nào để cập nhật thủ công"
            )
        except Exception as exc:
            return f"❌ Refresh cache thất bại: {exc}"
    return f"⚠️ Lệnh `{text.strip()}` không được nhận dạng. Lệnh hỗ trợ: `/refresh-cache`"


# ─── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.get("/")
def index():
    return send_from_directory(_STATIC_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "agent": "Zalopay CS Promotion Assistant"})


@app.get("/api/recent")
def api_recent():
    try:
        with open(_RECENT_PATH, "r", encoding="utf-8") as f:
            data = f.read()
        return app.response_class(data, mimetype="application/json; charset=utf-8")
    except (FileNotFoundError, OSError):
        return app.response_class("[]", mimetype="application/json")


def _invoke_agent():
    payload    = request.get_json(force=True) or {}
    session_id = (
        request.headers.get("X-GreenNode-AgentBase-Session-Id")
        or payload.get("session_id", "default-session")
    )
    text = payload.get("message", "").strip()

    cmd_response = handle_slash_command(text)
    if cmd_response is not None:
        return jsonify({"response": cmd_response, "session_id": session_id})

    user_message = build_user_message(payload)
    graph        = get_graph()
    config       = {"configurable": {"thread_id": session_id}}
    result       = graph.invoke({"messages": [user_message]}, config=config)
    return jsonify({"response": extract_last_response(result), "session_id": session_id})


@app.post("/invocations")
def invocations():
    return _invoke_agent()


@app.post("/api/invocations")
def api_invocations():
    return _invoke_agent()


# ─── CLI interactive mode ──────────────────────────────────────────────────────

def run_cli():
    print("=" * 60)
    print("  Zalopay CS Promotion Assistant - CLI Mode")
    print("=" * 60)
    print("Nhập thông tin ticket CS (gõ 'exit' để thoát, 'new' để reset session)")
    print("-" * 60)

    graph      = get_graph()
    session_id = "cli-session-001"
    config     = {"configurable": {"thread_id": session_id}}

    while True:
        try:
            user_input = input("\n[CS] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nKết thúc phiên làm việc.")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Thoát. Cảm ơn!")
            break
        if user_input.lower() == "new":
            import uuid
            session_id = f"cli-session-{uuid.uuid4().hex[:8]}"
            config     = {"configurable": {"thread_id": session_id}}
            print(f"[Đã bắt đầu session mới: {session_id}]")
            continue

        message  = HumanMessage(content=user_input)
        result   = graph.invoke({"messages": [message]}, config=config)
        response = extract_last_response(result)
        print(f"\n[AI Assistant]\n{response}")


if __name__ == "__main__":
    import sys
    if "--cli" in sys.argv:
        run_cli()
    else:
        port = int(os.getenv("PORT", "8080"))
        print(f"Zalopay CS Agent  →  http://0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, debug=False)
