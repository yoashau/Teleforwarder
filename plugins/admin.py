from shared_client import app
from pyrogram import filters
from config import OWNER_ID
from utils.func import (
    add_to_whitelist, remove_from_whitelist, is_whitelisted,
    get_user_data
)


def owner_only(func):
    """仅允许 OWNER_ID 中的用户使用的装饰器。"""
    async def wrapper(client, message):
        if message.from_user.id not in OWNER_ID:
            await message.reply("⚠️ 仅管理员可使用此指令。")
            return
        await func(client, message)
    wrapper.__name__ = func.__name__
    return wrapper


@app.on_message(filters.command("allow") & filters.private)
@owner_only
async def allow_user(client, message):
    args = message.command
    if len(args) < 2 or not args[1].lstrip('-').isdigit():
        await message.reply(
            "用法：/allow `<user_id>`\n"
            "示例：/allow 123456789"
        )
        return

    target_id = int(args[1])
    ok = await add_to_whitelist(target_id)
    if ok:
        await message.reply(f"✅ 用户 `{target_id}` 已加入白名单。")
        try:
            await client.send_message(
                target_id,
                "✅ 你已被管理员添加到白名单，现在可以使用机器人了！发送 /start 开始。"
            )
        except Exception:
            pass
    else:
        await message.reply(f"❌ 操作失败，请稍后再试。")


@app.on_message(filters.command("ban") & filters.private)
@owner_only
async def ban_user(client, message):
    args = message.command
    if len(args) < 2 or not args[1].lstrip('-').isdigit():
        await message.reply(
            "用法：/ban `<user_id>`\n"
            "示例：/ban 123456789"
        )
        return

    target_id = int(args[1])
    if target_id in OWNER_ID:
        await message.reply("⚠️ 不能移除管理员的权限。")
        return

    ok = await remove_from_whitelist(target_id)
    if ok:
        await message.reply(f"✅ 用户 `{target_id}` 已从白名单移除。")
    else:
        await message.reply(f"❌ 操作失败，请稍后再试。")


@app.on_message(filters.command("me") & filters.private)
async def me_handler(client, message):
    uid = message.from_user.id
    if not await is_whitelisted(uid):
        await message.reply("⚠️ 你没有使用权限，请联系管理员。")
        return

    user_data = await get_user_data(uid)
    is_owner = uid in OWNER_ID
    is_white = await is_whitelisted(uid)
    has_session = bool(user_data and user_data.get("session_string"))
    has_bot = bool(user_data and user_data.get("bot_token"))

    lines = [
        f"**个人状态**\n",
        f"{'👑 管理员' if is_owner else '✅ 白名单用户'}",
        f"**Telegram 会话：** {'✅ 已登录' if has_session else '❌ 未登录'}",
        f"**辅助机器人：** {'✅ 已绑定' if has_bot else '❌ 未绑定'}",
    ]
    await message.reply("\n".join(lines))
