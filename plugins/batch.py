"""
batch.py — 核心提取引擎
暴露的公共接口：
  extract_single(pyro_client, message, tg_url)  — 提取单条消息
  extract_range(pyro_client, message, tg_url, count)  — 批量提取
"""

import os
import re
import time
import asyncio
import json
from pyrogram import Client
from config import API_ID, API_HASH, LOG_GROUP, STRING
from utils.func import (
    get_user_data, get_user_data_key, process_text_with_rules,
    screenshot, thumbnail, get_video_metadata, E
)
from utils.encrypt import dcs
from typing import Dict, Any, Optional


Y = None if not STRING else __import__('shared_client').userbot

# ─── 全局状态 ─────────────────────────────────────────────────────────────────
Z = {}          # 兼容旧代码（不再使用）
P = {}          # 进度条去重
UB = {}         # user_id → 辅助 bot Client
UC = {}         # user_id → 用户 Client（session）
emp = {}        # channel_id → empty 标记

ACTIVE_USERS: Dict[str, Any] = {}
ACTIVE_USERS_FILE = "active_users.json"


# ─── 活跃任务持久化 ───────────────────────────────────────────────────────────

def _load_active_users():
    try:
        if os.path.exists(ACTIVE_USERS_FILE):
            with open(ACTIVE_USERS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}


async def _save_active_users():
    try:
        with open(ACTIVE_USERS_FILE, 'w') as f:
            json.dump(ACTIVE_USERS, f)
    except Exception as e:
        print(f"保存活跃用户出错: {e}")


async def add_active_batch(user_id: int, batch_info: Dict[str, Any]):
    ACTIVE_USERS[str(user_id)] = batch_info
    await _save_active_users()


def is_user_active(user_id: int) -> bool:
    return str(user_id) in ACTIVE_USERS


async def update_batch_progress(user_id: int, current: int, success: int):
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["current"] = current
        ACTIVE_USERS[str(user_id)]["success"] = success
        await _save_active_users()


async def request_batch_cancel(user_id: int) -> bool:
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["cancel_requested"] = True
        await _save_active_users()
        return True
    return False


def should_cancel(user_id: int) -> bool:
    u = str(user_id)
    return u in ACTIVE_USERS and ACTIVE_USERS[u].get("cancel_requested", False)


async def remove_active_batch(user_id: int):
    if str(user_id) in ACTIVE_USERS:
        del ACTIVE_USERS[str(user_id)]
        await _save_active_users()


def get_batch_info(user_id: int) -> Optional[Dict[str, Any]]:
    return ACTIVE_USERS.get(str(user_id))


ACTIVE_USERS = _load_active_users()


# ─── 文件名清理 ───────────────────────────────────────────────────────────────

def sanitize(filename):
    return re.sub(r'[<>:"/\\|?*\']', '_', filename).strip(" .")[:255]


# ─── 对话刷新 ─────────────────────────────────────────────────────────────────

async def upd_dlg(c):
    try:
        async for _ in c.get_dialogs(limit=100):
            pass
        return True
    except Exception as e:
        print(f"刷新对话列表失败: {e}")
        return False


# ─── 获取消息 ─────────────────────────────────────────────────────────────────

async def get_msg(c, u, i, d, lt):
    """获取指定频道的指定消息。
    c = bot client; u = user client; i = channel_id; d = msg_id; lt = link_type
    """
    try:
        if lt == 'public':
            try:
                if str(i).lower().endswith('bot'):
                    emp[i] = False
                    xm = await u.get_messages(i, d)
                    emp[i] = getattr(xm, "empty", False)
                    if not emp[i]:
                        emp[i] = True
                        return xm

                if emp.get(i, True):
                    xm = await c.get_messages(i, d)
                    emp[i] = getattr(xm, "empty", False)
                    if emp[i]:
                        try:
                            await u.join_chat(i)
                        except Exception:
                            pass
                        xm = await u.get_messages((await u.get_chat(f"@{i}")).id, d)
                    return xm
            except Exception as e:
                print(f"获取公开消息出错: {e}")
                return None
        else:
            if u:
                try:
                    async for _ in u.get_dialogs(limit=50):
                        pass
                    if str(i).startswith('-100'):
                        chat_id_100 = i
                        base_id = str(i)[4:]
                        chat_id_dash = f"-{base_id}"
                    elif str(i).isdigit():
                        chat_id_100 = f"-100{i}"
                        chat_id_dash = f"-{i}"
                    else:
                        chat_id_100 = i
                        chat_id_dash = i

                    for cid in [chat_id_100, chat_id_dash]:
                        try:
                            result = await u.get_messages(cid, d)
                            if result and not getattr(result, "empty", False):
                                return result
                        except Exception:
                            pass

                    async for _ in u.get_dialogs(limit=200):
                        pass
                    result = await u.get_messages(i, d)
                    if result and not getattr(result, "empty", False):
                        return result
                    return None
                except Exception as e:
                    print(f"获取私有频道消息出错: {e}")
                    return None
            return None
    except Exception as e:
        print(f"获取消息出错: {e}")
        return None


# ─── 辅助 Bot 与用户客户端 ───────────────────────────────────────────────────

async def get_ubot(uid):
    """获取用户绑定的辅助 bot；若无则返回 None。"""
    bt = await get_user_data_key(uid, "bot_token", None)
    if not bt:
        return None
    if uid in UB:
        return UB[uid]
    try:
        bot = Client(f"user_{uid}", bot_token=bt, api_id=API_ID, api_hash=API_HASH)
        await bot.start()
        UB[uid] = bot
        return bot
    except Exception as e:
        print(f"启动辅助 bot 出错 {uid}: {e}")
        return None


async def get_uclient(uid):
    """获取用户的个人 Pyrogram 客户端（用于下载私有内容）。"""
    ud = await get_user_data(uid)
    ubot = UB.get(uid)
    cl = UC.get(uid)
    if cl:
        return cl
    if not ud:
        return ubot if ubot else None
    xxx = ud.get('session_string')
    if xxx:
        try:
            ss = dcs(xxx)
            gg = Client(f'{uid}_client', api_id=API_ID, api_hash=API_HASH,
                        device_model="PrivateBot", session_string=ss)
            await gg.start()
            await upd_dlg(gg)
            UC[uid] = gg
            return gg
        except Exception as e:
            print(f"用户客户端启动出错: {e}")
            return ubot if ubot else Y
    return Y


# ─── 进度条 ───────────────────────────────────────────────────────────────────

async def prog(c, t, C, h, m, st):
    global P
    p = c / t * 100
    interval = 10 if t >= 100 * 1024 * 1024 else 20 if t >= 50 * 1024 * 1024 else 30 if t >= 10 * 1024 * 1024 else 50
    step = int(p // interval) * interval
    if m not in P or P[m] != step or p >= 100:
        P[m] = step
        c_mb = c / (1024 * 1024)
        t_mb = t / (1024 * 1024)
        bar = '🟢' * int(p / 10) + '🔴' * (10 - int(p / 10))
        speed = c / (time.time() - st) / (1024 * 1024) if time.time() > st else 0
        eta = time.strftime('%M:%S', time.gmtime((t - c) / (speed * 1024 * 1024))) if speed > 0 else '00:00'
        try:
            await C.edit_message_text(
                h, m,
                f"**⬆️ 上传中...**\n\n{bar}\n\n"
                f"**完成度：** {c_mb:.2f} MB / {t_mb:.2f} MB（{p:.2f}%）\n"
                f"**速度：** {speed:.2f} MB/s\n"
                f"**剩余时间：** {eta}"
            )
        except Exception:
            pass
        if p >= 100:
            P.pop(m, None)


# ─── 直接转发（不落盘）────────────────────────────────────────────────────────

async def send_direct(c, m, tcid, ft=None, rtmid=None):
    try:
        if m.video:
            await c.send_video(tcid, m.video.file_id, caption=ft,
                               duration=m.video.duration, width=m.video.width,
                               height=m.video.height, reply_to_message_id=rtmid)
        elif m.video_note:
            await c.send_video_note(tcid, m.video_note.file_id, reply_to_message_id=rtmid)
        elif m.voice:
            await c.send_voice(tcid, m.voice.file_id, reply_to_message_id=rtmid)
        elif m.sticker:
            await c.send_sticker(tcid, m.sticker.file_id, reply_to_message_id=rtmid)
        elif m.audio:
            await c.send_audio(tcid, m.audio.file_id, caption=ft,
                               duration=m.audio.duration, performer=m.audio.performer,
                               title=m.audio.title, reply_to_message_id=rtmid)
        elif m.photo:
            photo_id = m.photo.file_id if hasattr(m.photo, 'file_id') else m.photo[-1].file_id
            await c.send_photo(tcid, photo_id, caption=ft, reply_to_message_id=rtmid)
        elif m.document:
            await c.send_document(tcid, m.document.file_id, caption=ft,
                                  file_name=m.document.file_name, reply_to_message_id=rtmid)
        else:
            return False
        return True
    except Exception as e:
        print(f"直接转发出错: {e}")
        return False


# ─── 核心消息处理 ─────────────────────────────────────────────────────────────

async def process_msg(c, u, m, d, lt, uid, i):
    """处理单条消息：下载并上传到用户的聊天。
    c = 上传 bot; u = 下载 client; m = 源消息;
    d = 目标 chat_id(str); lt = link_type; uid = user_id; i = channel_id
    """
    try:
        cfg_chat = await get_user_data_key(d, 'chat_id', None)
        tcid = d
        rtmid = None
        if cfg_chat:
            if '/' in cfg_chat:
                parts = cfg_chat.split('/', 1)
                tcid = int(parts[0])
                rtmid = int(parts[1]) if len(parts) > 1 else None
            else:
                tcid = int(cfg_chat)

        if m.media:
            orig_text = m.caption.markdown if m.caption else ''
            proc_text = await process_text_with_rules(d, orig_text)
            user_cap = await get_user_data_key(d, 'caption', '')
            ft = (f'{proc_text}\n\n{user_cap}' if proc_text and user_cap
                  else user_cap if user_cap else proc_text)

            if lt == 'public' and not emp.get(i, False):
                await send_direct(c, m, tcid, ft, rtmid)
                return '直接转发完成。'

            st = time.time()
            p = await c.send_message(d, '⬇️ 正在下载...')

            c_name = f"{time.time()}"
            if m.video:
                file_name = m.video.file_name or f"{time.time()}.mp4"
                c_name = sanitize(file_name)
            elif m.audio:
                file_name = m.audio.file_name or f"{time.time()}.mp3"
                c_name = sanitize(file_name)
            elif m.document:
                file_name = m.document.file_name or f"{time.time()}"
                c_name = sanitize(file_name)
            elif m.photo:
                c_name = sanitize(f"{time.time()}.jpg")

            f = await u.download_media(m, file_name=c_name, progress=prog,
                                       progress_args=(c, d, p.id, st))

            if not f:
                await c.edit_message_text(d, p.id, '❌ 下载失败。')
                return '下载失败。'

            await c.edit_message_text(d, p.id, '✏️ 正在重命名...')
            if (
                (m.video and m.video.file_name) or
                (m.audio and m.audio.file_name) or
                (m.document and m.document.file_name)
            ):
                from plugins.settings import rename_file
                f = await rename_file(f, d, p)

            fsize = os.path.getsize(f) / (1024 * 1024 * 1024)
            th = thumbnail(d)

            if fsize > 2 and Y:
                await c.edit_message_text(d, p.id, '⚠️ 文件超过 2GB，使用高级通道上传...')
                await upd_dlg(Y)
                mtd = await get_video_metadata(f)
                dur, h, w = mtd['duration'], mtd['width'], mtd['height']
                th = await screenshot(f, dur, d)
                st = time.time()

                send_funcs = {
                    'video': Y.send_video, 'video_note': Y.send_video_note,
                    'voice': Y.send_voice, 'audio': Y.send_audio,
                    'photo': Y.send_photo, 'document': Y.send_document
                }
                for mtype, func in send_funcs.items():
                    if f.endswith('.mp4'):
                        mtype = 'video'
                    if getattr(m, mtype, None):
                        sent = await func(
                            LOG_GROUP, f,
                            thumb=th if mtype == 'video' else None,
                            duration=dur if mtype == 'video' else None,
                            height=h if mtype == 'video' else None,
                            width=w if mtype == 'video' else None,
                            caption=ft if m.caption and mtype not in ['video_note', 'voice'] else None,
                            reply_to_message_id=rtmid,
                            progress=prog, progress_args=(c, d, p.id, st)
                        )
                        break
                else:
                    sent = await Y.send_document(
                        LOG_GROUP, f, thumb=th, caption=ft if m.caption else None,
                        reply_to_message_id=rtmid,
                        progress=prog, progress_args=(c, d, p.id, st)
                    )

                await c.copy_message(d, LOG_GROUP, sent.id)
                os.remove(f)
                await c.delete_messages(d, p.id)
                return '完成（大文件）。'

            await c.edit_message_text(d, p.id, '⬆️ 正在上传...')
            st = time.time()

            try:
                video_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ogv']
                audio_extensions = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.opus', '.aiff', '.ac3']
                file_ext = os.path.splitext(f)[1].lower()
                if m.video or (m.document and file_ext in video_extensions):
                    mtd = await get_video_metadata(f)
                    dur, h, w = mtd['duration'], mtd['width'], mtd['height']
                    th = await screenshot(f, dur, d)
                    await c.send_video(tcid, video=f, caption=ft if m.caption else None,
                                       thumb=th, width=w, height=h, duration=dur,
                                       progress=prog, progress_args=(c, d, p.id, st),
                                       reply_to_message_id=rtmid)
                elif m.video_note:
                    await c.send_video_note(tcid, video_note=f, progress=prog,
                                            progress_args=(c, d, p.id, st),
                                            reply_to_message_id=rtmid)
                elif m.voice:
                    await c.send_voice(tcid, f, progress=prog,
                                       progress_args=(c, d, p.id, st),
                                       reply_to_message_id=rtmid)
                elif m.sticker:
                    await c.send_sticker(tcid, m.sticker.file_id, reply_to_message_id=rtmid)
                elif m.audio or (m.document and file_ext in audio_extensions):
                    await c.send_audio(tcid, audio=f, caption=ft if m.caption else None,
                                       thumb=th, progress=prog,
                                       progress_args=(c, d, p.id, st),
                                       reply_to_message_id=rtmid)
                elif m.photo:
                    await c.send_photo(tcid, photo=f, caption=ft if m.caption else None,
                                       progress=prog, progress_args=(c, d, p.id, st),
                                       reply_to_message_id=rtmid)
                else:
                    await c.send_document(tcid, document=f, caption=ft if m.caption else None,
                                          progress=prog, progress_args=(c, d, p.id, st),
                                          reply_to_message_id=rtmid)
            except Exception as e:
                await c.edit_message_text(d, p.id, f'⚠️ 上传失败：{str(e)[:50]}')
                if os.path.exists(f):
                    os.remove(f)
                return '上传失败。'

            os.remove(f)
            await c.delete_messages(d, p.id)
            return '完成。'

        elif m.text:
            await c.send_message(tcid, text=m.text.markdown, reply_to_message_id=rtmid)
            return '文本已发送。'

    except Exception as e:
        return f'出错：{str(e)[:80]}'


# ─── 公共接口：单条提取 ───────────────────────────────────────────────────────

async def extract_single(pyro_client, message, tg_url: str):
    """供 router.py 调用：提取单条 Telegram 消息。"""
    uid = message.from_user.id
    chat_id = str(message.chat.id)

    cid, sid, lt = E(tg_url)
    if not cid or not sid:
        await message.reply("⚠️ 链接解析失败，请确认链接格式正确。")
        return

    if lt == 'private':
        uc = await get_uclient(uid)
        if not uc:
            await message.reply(
                "⚠️ 提取私有频道内容需要先登录，请使用 /login 完成账号验证。"
            )
            return
    else:
        uc = await get_uclient(uid)
        if not uc:
            uc = pyro_client

    # 上传用 bot：优先辅助 bot，否则主 bot
    upload_bot = await get_ubot(uid) or pyro_client

    status = await message.reply("⏳ 正在处理...")
    try:
        msg = await get_msg(upload_bot, uc, cid, sid, lt)
        if not msg or getattr(msg, "empty", False):
            await status.edit("⚠️ 消息获取失败，可能已被删除或频道已限制访问。")
            return
        res = await process_msg(upload_bot, uc, msg, chat_id, lt, uid, cid)
        await status.edit(f"✅ {res}")
    except Exception as e:
        await status.edit(f"⚠️ 下载失败：{str(e)[:100]}")


# ─── 公共接口：批量提取 ───────────────────────────────────────────────────────

async def extract_range(pyro_client, message, tg_url: str, count: int):
    """供 router.py 调用：从指定链接开始连续提取 count 条消息。"""
    uid = message.from_user.id
    chat_id = str(message.chat.id)

    cid, sid, lt = E(tg_url)
    if not cid or not sid:
        await message.reply("⚠️ 链接解析失败，请确认链接格式正确。")
        return

    if is_user_active(uid):
        await message.reply("⚠️ 你已有正在进行的任务，请等待完成或发送 /cancel 取消。")
        return

    if lt == 'private':
        uc = await get_uclient(uid)
        if not uc:
            await message.reply(
                "⚠️ 提取私有频道内容需要先登录，请使用 /login 完成账号验证。"
            )
            return
    else:
        uc = await get_uclient(uid)
        if not uc:
            uc = pyro_client

    upload_bot = await get_ubot(uid) or pyro_client

    pt = await message.reply(f"⏳ 开始批量提取（共 {count} 条）...")
    success = 0

    await add_active_batch(uid, {
        "total": count, "current": 0, "success": 0,
        "cancel_requested": False, "progress_message_id": pt.id
    })

    try:
        for j in range(count):
            if should_cancel(uid):
                await pt.edit(f"🚫 已取消，进度：{j}/{count}，成功：{success}")
                break
            await update_batch_progress(uid, j, success)
            mid = sid + j
            try:
                msg = await get_msg(upload_bot, uc, cid, mid, lt)
                if msg and not getattr(msg, "empty", False):
                    res = await process_msg(upload_bot, uc, msg, chat_id, lt, uid, cid)
                    if any(kw in res for kw in ['完成', '转发', '发送']):
                        success += 1
            except Exception as e:
                try:
                    await pt.edit(f"⏳ {j + 1}/{count} 出错：{str(e)[:30]}")
                except Exception:
                    pass
            await asyncio.sleep(8)

        if not should_cancel(uid):
            await message.reply(f"✅ 批量提取完成！成功：{success}/{count}")
    finally:
        await remove_active_batch(uid)
