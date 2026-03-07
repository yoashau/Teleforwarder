from shared_client import app
from pyrogram import filters
from pyrogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from config import OWNER_ID
from utils.func import is_whitelisted


async def check_whitelist(message) -> bool:
    """检查用户是否在白名单中，若不在则直接回复拒绝消息并返回 False。"""
    if not await is_whitelisted(message.from_user.id):
        await message.reply("⚠️ 你没有使用权限，请联系管理员。")
        return False
    return True


@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    if not await check_whitelist(message):
        return

    await message.reply(
        "**欢迎使用私有 Telegram 内容提取机器人！**\n\n"
        "直接向我发送 Telegram 消息链接，我会自动提取并转发：\n"
        "• **公开频道/群组链接**（无需登录）\n"
        "• **私有频道/群组链接**（需先 /login 登录账号）\n\n"
        "支持链接后加空格和数字批量提取，如：`https://t.me/xxx/100 10`\n\n"
        "发送 /help 查看完整指令列表。"
    )


@app.on_message(filters.command("help") & filters.private)
async def help_handler(client, message):
    if not await check_whitelist(message):
        return

    text = (
        "**指令列表**\n\n"
        "**提取（无需指令，直接发链接）**\n"
        "> 发送 Telegram 消息链接即可自动提取，支持批量（链接后跟数字）。\n\n"
        "**账号管理**\n"
        "> /login — 登录 Telegram 账号（用于提取私有频道内容）\n"
        "> /logout — 退出 Telegram 账号\n"
        "> /bindbot `<token>` — 绑定辅助节点机器人（用于大文件上传）\n"
        "> /unbindbot — 解绑辅助节点机器人\n\n"
        "**个人信息**\n"
        "> /me — 查看当前账号的白名单与登录状态\n"
        "> /setting — 打开个性化设置面板\n\n"
        "**管理员指令**\n"
        "> /allow `<user_id>` — 将用户加入白名单\n"
        "> /ban `<user_id>` — 将用户移出白名单\n\n"
        "**通用**\n"
        "> /cancel — 取消当前所有进行中的操作\n"
    )
    await message.reply(text)


@app.on_message(filters.command("set") & filters.private)
async def set_commands(client, message):
    if message.from_user.id not in OWNER_ID:
        await message.reply("⚠️ 仅管理员可使用此指令。")
        return

    await app.set_bot_commands([
        BotCommand("start", "启动机器人"),
        BotCommand("help", "查看帮助"),
        BotCommand("login", "登录 Telegram 账号"),
        BotCommand("logout", "退出 Telegram 账号"),
        BotCommand("bindbot", "绑定辅助节点机器人"),
        BotCommand("unbindbot", "解绑辅助节点机器人"),
        BotCommand("me", "查看个人状态"),
        BotCommand("setting", "个性化设置"),
        BotCommand("allow", "添加用户到白名单（管理员）"),
        BotCommand("ban", "从白名单移除用户（管理员）"),
        BotCommand("cancel", "取消当前操作"),
    ])
    await message.reply("✅ 指令列表已更新！")
