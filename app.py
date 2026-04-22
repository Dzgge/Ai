import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

# 配置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 获取环境变量
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# 初始化 Gemini 3 官方客户端
client = genai.Client(api_key=GEMINI_API_KEY)

# 内存存储用户会话
user_sessions = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "model": "gemini-3.1-flash-lite-preview",
            "search": False,
            "chat": None,
            "last_prompt": ""
        }
    return user_sessions[user_id]

def init_or_update_chat(session):
    """初始化或更新 Chat 对象（切换模型或搜索状态时保留历史上下文）"""
    tools = [{"google_search": {}}] if session["search"] else None
    config = types.GenerateContentConfig(
        temperature=0.0,
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        tools=tools
    )
    
    # 如果已有历史记录，则继承历史记录
    history = session["chat"].history if session["chat"] else []
    
    session["chat"] = client.chats.create(
        model=session["model"],
        config=config,
        history=history
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 欢迎使用 Gemini 3 Telegram Bot！\n\n"
        "⚙️ 当前默认设置：Temperature=0, Thinking Level=High\n\n"
        "🛠 可用命令：\n"
        "/model - 切换模型 (3.1 Flash Lite / 3 Flash)\n"
        "/search - 开启/关闭 Google 搜索\n"
        "/clear - 清空上下文 (开启新对话窗口)\n"
        "/history - 查看当前对话历史\n"
        "/retry - 删除上一轮问答并重新生成\n"
    )
    await update.message.reply_text(help_text)

async def switch_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    if session["model"] == "gemini-3.1-flash-lite-preview":
        session["model"] = "gemini-3-flash-preview"
    else:
        session["model"] = "gemini-3.1-flash-lite-preview"
    
    init_or_update_chat(session)
    await update.message.reply_text(f"🔄 模型已切换为：{session['model']}")

async def toggle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    session["search"] = not session["search"]
    
    init_or_update_chat(session)
    status = "✅ 开启" if session["search"] else "❌ 关闭"
    await update.message.reply_text(f"🔍 Google 搜索已 {status}")

async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    session["chat"] = None
    session["last_prompt"] = ""
    await update.message.reply_text("🧹 上下文已清空，已开启全新对话窗口！")

async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    if not session["chat"] or not session["chat"].history:
        await update.message.reply_text("📭 当前窗口没有对话历史。")
        return
    
    history_text = "📜 当前对话历史：\n\n"
    for msg in session["chat"].history:
        role = "🧑‍💻 你" if msg.role == "user" else "🤖 Gemini"
        text = msg.parts[0].text if msg.parts else "[包含非文本内容]"
        # 截断过长的历史记录以便展示
        content = text[:100] + "..." if len(text) > 100 else text
        history_text += f"{role}: {content}\n\n"
    
    await update.message.reply_text(history_text)

async def generate_response(update: Update, user_id: int, prompt: str):
    session = get_session(user_id)
    
    if session["chat"] is None:
        init_or_update_chat(session)
        
    try:
        response = session["chat"].send_message(prompt)
        reply_text = response.text
        
        # Telegram 单条消息长度限制为 4096 字符，超长自动分段发送
        if len(reply_text) > 4000:
            for i in range(0, len(reply_text), 4000):
                await update.message.reply_text(reply_text[i:i+4000])
        else:
            await update.message.reply_text(reply_text)
            
    except Exception as e:
        await update.message.reply_text(f"❌ 发生错误：{str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prompt = update.message.text
    session = get_session(user_id)
    session["last_prompt"] = prompt
    
    # 显示“正在输入...”状态
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await generate_response(update, user_id, prompt)

async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    
    if not session["last_prompt"] or not session["chat"]:
        await update.message.reply_text("⚠️ 没有可以重试的对话。")
        return
        
    # 移除最后一次的用户提问和模型回答（实现“删除问题”并重试的效果）
    if len(session["chat"].history) >= 2:
        new_history = session["chat"].history[:-2]
        tools = [{"google_search": {}}] if session["search"] else None
        config = types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
            tools=tools
        )
        session["chat"] = client.chats.create(
            model=session["model"],
            config=config,
            history=new_history
        )
    else:
        session["chat"] = None
        
    await update.message.reply_text("🔄 正在重新思考并生成回答...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await generate_response(update, user_id, session["last_prompt"])

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", switch_model))
    app.add_handler(CommandHandler("search", toggle_search))
    app.add_handler(CommandHandler("clear", clear_context))
    app.add_handler(CommandHandler("history", view_history))
    app.add_handler(CommandHandler("retry", retry_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot is running...")
    app.run_polling()
