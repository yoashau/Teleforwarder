import logging
import os
from pyrogram import Client, filters
from pyrogram.errors import (
    BadRequest, SessionPasswordNeeded,
    PhoneCodeInvalid, PhoneCodeExpired, MessageNotModified
)
from config import API_HASH, API_ID
from shared_client import app as bot
from utils.func import save_user_session, get_user_data, remove_user_session, save_user_bot, remove_user_bot
from utils.encrypt import ecs, dcs
from utils.custom_filters import login_in_progress, set_user_step, get_user_step
from utils.func import is_whitelisted

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STEP_PHONE = 1
STEP_CODE = 2
STEP_PASSWORD = 3
login_cache = {}


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

async def _edit(msg, text):
    try:
        await msg.edit(text)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"编辑消息出错: {e}")


async def _check_whitelist(message) -> bool:
    if not await is_whitelisted(message.from_user.id):
        await message.reply("⚠️ 你没有使用权限，请联系管理员。")
        return False
    return True


# ─── /login ───────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client, message):
    if not await _check_whitelist(message):
        return

    user_id = message.from_user.id
    set_user_step(user_id, STEP_PHONE)
    login_cache.pop(user_id, None)

    try:
        await message.delete()
    except Exception:
        pass

    status_msg = await message.reply(
        "**请发送你的手机号码（含国家区号）**\n"
        "示例：`+8613812345678`"
    )
    login_cache[user_id] = {'status_msg': status_msg}


# ─── 登录流程状态机 ───────────────────────────────────────────────────────────

@bot.on_message(
    login_in_progress & filters.text & filters.private
    & ~filters.command([
        'start', 'cancel', 'login', 'logout', 'help', 'me',
        'allow', 'ban', 'bindbot', 'unbindbot', 'setting', 'set'
    ])
)
async def handle_login_steps(client, message):
    user_id = message.from_user.id
    text = message.text.strip()
    step = get_user_step(user_id)

    try:
        await message.delete()
    except Exception:
        pass

    status_msg = login_cache.get(user_id, {}).get('status_msg')
    if not status_msg:
        status_msg = await message.reply("⏳ 处理中...")
        login_cache[user_id] = {'status_msg': status_msg}

    try:
        if step == STEP_PHONE:
            if not text.startswith('+'):
                await _edit(status_msg, "❌ 手机号格式不正确，请以 `+` 开头，例如 `+8613812345678`")
                return

            await _edit(status_msg, "⏳ 正在发送验证码...")
            temp_client = Client(
                f'temp_{user_id}', api_id=API_ID, api_hash=API_HASH,
                device_model="PrivateBot", in_memory=True
            )
            try:
                await temp_client.connect()
                sent_code = await temp_client.send_code(text)
                login_cache[user_id].update({
                    'phone': text,
                    'phone_code_hash': sent_code.phone_code_hash,
                    'temp_client': temp_client,
                })
                set_user_step(user_id, STEP_CODE)
                await _edit(
                    status_msg,
                    "✅ **验证码已发送！**\n\n"
                    "请输入你收到的验证码，**数字之间用空格隔开**。\n"
                    "示例：`1 2 3 4 5`"
                )
            except BadRequest as e:
                await _edit(status_msg, f"❌ 发送验证码失败：`{e}`\n请重新发送 /login 再试。")
                await temp_client.disconnect()
                set_user_step(user_id, None)

        elif step == STEP_CODE:
            code = text.replace(' ', '')
            phone = login_cache[user_id]['phone']
            phone_code_hash = login_cache[user_id]['phone_code_hash']
            temp_client = login_cache[user_id]['temp_client']
            try:
                await _edit(status_msg, "⏳ 正在验证验证码...")
                await temp_client.sign_in(phone, phone_code_hash, code)
                session_string = await temp_client.export_session_string()
                encrypted_session = ecs(session_string)
                await save_user_session(user_id, encrypted_session)
                await temp_client.disconnect()
                await _edit(status_msg, "✅ **登录成功！** 现在可以提取私有频道内容了。")
                set_user_step(user_id, None)
                login_cache.pop(user_id, None)
            except SessionPasswordNeeded:
                set_user_step(user_id, STEP_PASSWORD)
                await _edit(
                    status_msg,
                    "🔒 **你的账号开启了两步验证**\n\n请输入你的两步验证密码："
                )
            except (PhoneCodeInvalid, PhoneCodeExpired):
                await _edit(
                    status_msg,
                    "❌ 验证码无效或已过期，请重新发送 /login 再试。"
                )
                await temp_client.disconnect()
                login_cache.pop(user_id, None)
                set_user_step(user_id, None)

        elif step == STEP_PASSWORD:
            temp_client = login_cache[user_id]['temp_client']
            try:
                await _edit(status_msg, "⏳ 正在验证密码...")
                await temp_client.check_password(text)
                session_string = await temp_client.export_session_string()
                encrypted_session = ecs(session_string)
                await save_user_session(user_id, encrypted_session)
                await temp_client.disconnect()
                await _edit(status_msg, "✅ **登录成功！** 现在可以提取私有频道内容了。")
                set_user_step(user_id, None)
                login_cache.pop(user_id, None)
            except BadRequest as e:
                await _edit(status_msg, f"❌ 密码错误：`{e}`\n请重新输入密码：")

    except Exception as e:
        logger.error(f"登录流程出错: {e}")
        await _edit(status_msg, f"⚠️ 发生错误，请重新发送 /login 再试。")
        if user_id in login_cache and 'temp_client' in login_cache[user_id]:
            try:
                await login_cache[user_id]['temp_client'].disconnect()
            except Exception:
                pass
        login_cache.pop(user_id, None)
        set_user_step(user_id, None)


# ─── /logout ─────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("logout") & filters.private)
async def logout_command(client, message):
    if not await _check_whitelist(message):
        return

    user_id = message.from_user.id
    try:
        await message.delete()
    except Exception:
        pass
    status_msg = await message.reply("⏳ 正在处理退出请求...")

    try:
        session_data = await get_user_data(user_id)
        if not session_data or 'session_string' not in session_data:
            await _edit(status_msg, "❌ 未找到登录会话，你可能尚未登录。")
            return

        session_string = dcs(session_data['session_string'])
        temp_client = Client(
            f'temp_logout_{user_id}', api_id=API_ID,
            api_hash=API_HASH, session_string=session_string
        )
        try:
            await temp_client.connect()
            await temp_client.log_out()
        except Exception as e:
            logger.warning(f"终止 Telegram 会话出错: {e}")
        finally:
            try:
                await temp_client.disconnect()
            except Exception:
                pass

        await remove_user_session(user_id)
        await _edit(status_msg, "✅ 已成功退出登录！")

        # 清理会话文件
        try:
            if os.path.exists(f"{user_id}_client.session"):
                os.remove(f"{user_id}_client.session")
        except Exception:
            pass

        # 清理内存中的用户客户端
        try:
            from plugins.batch import UC
            if UC.get(user_id):
                del UC[user_id]
        except Exception:
            pass

    except Exception as e:
        logger.error(f"退出登录出错: {e}")
        await remove_user_session(user_id)
        await _edit(status_msg, f"⚠️ 退出过程中发生错误，但会话已从数据库移除。")


# ─── /cancel —— 全局安全出口 ─────────────────────────────────────────────────

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message):
    user_id = message.from_user.id
    cleared = False

    # 清理登录状态
    if get_user_step(user_id):
        if user_id in login_cache and 'temp_client' in login_cache[user_id]:
            try:
                await login_cache[user_id]['temp_client'].disconnect()
            except Exception:
                pass
        login_cache.pop(user_id, None)
        set_user_step(user_id, None)
        cleared = True

    # 清理设置面板对话状态
    try:
        from plugins.settings import active_conversations
        if user_id in active_conversations:
            del active_conversations[user_id]
            cleared = True
    except Exception:
        pass

    # 清理批量任务状态
    try:
        from plugins.batch import request_batch_cancel, is_user_active
        if is_user_active(user_id):
            await request_batch_cancel(user_id)
            cleared = True
    except Exception:
        pass

    try:
        await message.delete()
    except Exception:
        pass

    await message.reply("✅ 操作已取消，机器人已恢复待命状态。")


# ─── /bindbot ────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("bindbot") & filters.private)
async def bind_bot(client, message):
    if not await _check_whitelist(message):
        return

    user_id = message.from_user.id
    args = message.text.split(" ", 1)

    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "用法：`/bindbot <bot_token>`\n\n"
            "此机器人将作为辅助节点用于大文件上传。"
        )
        return

    bot_token = args[1].strip()

    # 停止并替换旧的 bot
    try:
        from plugins.batch import UB
        if user_id in UB:
            try:
                await UB[user_id].stop()
            except Exception:
                pass
            del UB[user_id]
            try:
                if os.path.exists(f"user_{user_id}.session"):
                    os.remove(f"user_{user_id}.session")
            except Exception:
                pass
    except Exception:
        pass

    await save_user_bot(user_id, bot_token)
    await message.reply("✅ 辅助机器人已绑定成功！")


# ─── /unbindbot ──────────────────────────────────────────────────────────────

@bot.on_message(filters.command("unbindbot") & filters.private)
async def unbind_bot(client, message):
    if not await _check_whitelist(message):
        return

    user_id = message.from_user.id

    try:
        from plugins.batch import UB
        if user_id in UB:
            try:
                await UB[user_id].stop()
            except Exception:
                pass
            del UB[user_id]
            try:
                if os.path.exists(f"user_{user_id}.session"):
                    os.remove(f"user_{user_id}.session")
            except Exception:
                pass
    except Exception:
        pass

    await remove_user_bot(user_id)
    await message.reply("✅ 辅助机器人已解绑。")
