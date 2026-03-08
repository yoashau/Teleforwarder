import os
import re
import time
import asyncio
import json
from pyrogram import Client
from pyrogram.errors import ChatForwardsRestricted, PeerIdInvalid
from config import API_ID, API_HASH, LOG_GROUP, STRING
from utils.func import (
    get_user_data, get_user_data_key, process_text_with_rules,
    screenshot, thumbnail, get_video_metadata, E
)
from utils.encrypt import dcs
from typing import Dict, Any, Optional, List


Y = None if not STRING else __import__('shared_client').userbot

# ─── 全局状态 ─────────────────────────────────────────────────────────────────
P = {}          # 进度条去重
UB = {}         # user_id → 辅助 bot Client
UC = {}         # user_id → 用户 Client（session）

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


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def sanitize(filename):
    return re.sub(r'[<>:"/\\|?*\']', '_', filename).strip(" .")[:255]


def _filename(m) -> str:
    if m.video:
        return sanitize(m.video.file_name or f'{time.time()}.mp4')
    if m.audio:
        return sanitize(m.audio.file_name or f'{time.time()}.mp3')
    if m.document:
        return sanitize(m.document.file_name or f'{time.time()}')
    if m.animation:
        return sanitize(m.animation.file_name or f'{time.time()}.mp4')
    if m.photo:
        return sanitize(f'{time.time()}.jpg')
    return f'{time.time()}'


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
                xm = await c.get_messages(i, d)
                if xm and not getattr(xm, 'empty', False):
                    return xm
            except Exception:
                pass

            if not u:
                return None

            try:
                try:
                    await u.join_chat(i)
                except Exception:
                    pass
                cid = i if str(i).lstrip('-').isdigit() else (await u.get_chat(f'@{i}')).id
                xm = await u.get_messages(cid, d)
                return xm if xm and not getattr(xm, 'empty', False) else None
            except Exception as e:
                print(f"获取公开消息出错: {e}")
                return None

        else:
            if not u:
                return None
            try:
                si = str(i)
                if si.startswith('-100'):
                    variants = [int(si), int(f'-{si[4:]}')]
                elif si.lstrip('-').isdigit():
                    n = si.lstrip('-')
                    variants = [int(f'-100{n}'), int(f'-{n}')]
                else:
                    variants = [i]

                for cid in variants:
                    try:
                        xm = await u.get_messages(cid, d)
                        if xm and not getattr(xm, 'empty', False):
                            return xm
                    except Exception:
                        pass

                await upd_dlg(u)
                for cid in variants:
                    try:
                        xm = await u.get_messages(cid, d)
                        if xm and not getattr(xm, 'empty', False):
                            return xm
                    except Exception:
                        pass

                return None
            except Exception as e:
                print(f"获取私有频道消息出错: {e}")
                return None

    except Exception as e:
        print(f"获取消息出错: {e}")
        return None


# ─── 辅助 Bot 与用户客户端 ───────────────────────────────────────────────────

async def get_ubot(uid):
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


# ─── 相册（Media Group）处理 ──────────────────────────────────────────────────

async def _fetch_media_group(client, m) -> List:
    """获取同一相册内的全部消息（按 ID 升序）。"""
    try:
        ids = list(range(max(1, m.id - 9), m.id + 10))
        msgs = await client.get_messages(m.chat.id, ids)
        gid = m.media_group_id
        group = [x for x in msgs
                 if x and not getattr(x, 'empty', False)
                 and getattr(x, 'media_group_id', None) == gid]
        return sorted(group, key=lambda x: x.id) if group else [m]
    except Exception:
        return [m]


async def _send_media_group_physical(c, u, m, tcid, d, rtmid, cap):
    """物理搬运相册：逐个下载后组合为 send_media_group。"""
    from pyrogram.types import (
        InputMediaPhoto, InputMediaVideo,
        InputMediaDocument, InputMediaAudio,
    )

    group_msgs = await _fetch_media_group(u, m)
    total = len(group_msgs)
    p_msg = await c.send_message(d, f'⬇️ 正在下载相册（共 {total} 项）...')
    files = []

    try:
        media_inputs = []
        for idx, gm in enumerate(group_msgs):
            try:
                await c.edit_message_text(d, p_msg.id, f'⬇️ 正在下载相册 {idx + 1}/{total}...')
            except Exception:
                pass
            st = time.time()
            gf = await u.download_media(gm, file_name=_filename(gm),
                                         progress=prog, progress_args=(c, d, p_msg.id, st))
            if not gf:
                continue
            files.append(gf)
            # caption 只放在最后一项
            item_cap = cap if idx == total - 1 else None
            if gm.photo:
                media_inputs.append(InputMediaPhoto(gf, caption=item_cap))
            elif gm.video:
                media_inputs.append(InputMediaVideo(gf, caption=item_cap))
            elif gm.audio:
                media_inputs.append(InputMediaAudio(gf, caption=item_cap))
            else:
                media_inputs.append(InputMediaDocument(gf, caption=item_cap))

        if media_inputs:
            try:
                await c.edit_message_text(d, p_msg.id, f'⬆️ 正在上传相册（共 {len(media_inputs)} 项）...')
            except Exception:
                pass
            try:
                await c.send_media_group(tcid, media_inputs, reply_to_message_id=rtmid)
            except PeerIdInvalid:
                return '⚠️ 转发失败：Bot 尚未与目标聊天建立会话，请点击启动 Bot 或将其拉入目标群组。'

        await c.delete_messages(d, p_msg.id)
        return '完成。'

    except Exception as e:
        try:
            await c.edit_message_text(d, p_msg.id, f'⚠️ 出错：{str(e)[:80]}')
        except Exception:
            pass
        return f'出错：{str(e)[:80]}'

    finally:
        for gf in files:
            if gf and os.path.exists(gf):
                try:
                    os.remove(gf)
                except Exception:
                    pass


# ─── 核心消息处理 ─────────────────────────────────────────────────────────────

async def process_msg(c, u, m, d, lt, uid, i):
    """处理单条消息：1:1 克隆转发，遇到禁止转发限制则降级物理搬运。
    c = 上传 bot; u = 下载 client; m = 源消息;
    d = 目标 chat_id(str); lt = link_type; uid = user_id; i = channel_id
    """
    try:
        # 解析目标聊天
        cfg_chat = await get_user_data_key(d, 'chat_id', None)
        tcid = d
        rtmid = None
        if cfg_chat:
            if '/' in str(cfg_chat):
                parts = str(cfg_chat).split('/', 1)
                tcid = int(parts[0])
                rtmid = int(parts[1]) if len(parts) > 1 else None
            else:
                tcid = int(cfg_chat)

        user_cap = await get_user_data_key(d, 'caption', '') or ''

        # ── 纯文本消息 ────────────────────────────────────────────────────────
        if m.text and not m.media:
            proc = await process_text_with_rules(d, m.text.markdown)
            final = f'{proc}\n\n{user_cap}' if user_cap else proc
            try:
                await c.send_message(tcid, final, reply_to_message_id=rtmid)
            except PeerIdInvalid:
                return '⚠️ 转发失败：Bot 尚未与目标聊天建立会话，请点击启动 Bot 或将其拉入目标群组。'
            return '完成。'

        # ── 计算最终 caption ──────────────────────────────────────────────────
        orig_cap = m.caption.markdown if m.caption else ''
        proc_cap = await process_text_with_rules(d, orig_cap)
        if proc_cap and user_cap:
            final_cap = f'{proc_cap}\n\n{user_cap}'
        elif user_cap:
            final_cap = user_cap
        elif proc_cap != orig_cap:
            final_cap = proc_cap
        else:
            final_cap = None  # 不覆盖，原生克隆完整保留原始排版

        # 物理搬运时使用的 caption（确保有内容时不丢失）
        cap = final_cap if final_cap is not None else (orig_cap or None)

        # ── 相册（Media Group）────────────────────────────────────────────────
        if getattr(m, 'media_group_id', None):
            # 优先尝试原生克隆整组
            if hasattr(c, 'copy_media_group'):
                try:
                    await c.copy_media_group(tcid, m.chat.id, m.id,
                                             reply_to_message_id=rtmid)
                    return '完成。'
                except ChatForwardsRestricted:
                    pass
                except PeerIdInvalid:
                    return '⚠️ 转发失败：Bot 尚未与目标聊天建立会话，请点击启动 Bot 或将其拉入目标群组。'
                except Exception:
                    pass
            # 降级：物理搬运整组相册
            return await _send_media_group_physical(c, u, m, tcid, d, rtmid, cap)

        # ── 单条媒体：优先原生克隆 ────────────────────────────────────────────
        try:
            await c.copy_message(
                tcid, m.chat.id, m.id,
                caption=final_cap,
                reply_to_message_id=rtmid
            )
            return '完成。'
        except ChatForwardsRestricted:
            pass  # 降级物理搬运
        except PeerIdInvalid:
            return '⚠️ 转发失败：Bot 尚未与目标聊天建立会话，请点击启动 Bot 或将其拉入目标群组。'
        except Exception as e:
            return f'出错：{str(e)[:80]}'

        # ── 物理搬运降级（突破禁止转发限制）─────────────────────────────────
        p = await c.send_message(d, '⬇️ 正在下载...')
        f = None
        st = time.time()

        try:
            f = await u.download_media(m, file_name=_filename(m),
                                        progress=prog, progress_args=(c, d, p.id, st))
            if not f:
                await c.edit_message_text(d, p.id, '❌ 下载失败。')
                return '下载失败。'

            await c.edit_message_text(d, p.id, '✏️ 正在重命名...')
            if ((m.video and m.video.file_name) or
                    (m.audio and m.audio.file_name) or
                    (m.document and m.document.file_name)):
                from plugins.settings import rename_file
                f = await rename_file(f, d, p)

            fsize = os.path.getsize(f) / (1024 ** 3)
            th = thumbnail(d)

            # 超过 2GB：走 Premium 用户 bot 上传通道
            if fsize > 2 and Y:
                await c.edit_message_text(d, p.id, '⚠️ 文件超过 2GB，使用高级通道上传...')
                await upd_dlg(Y)
                await c.edit_message_text(d, p.id, '🎬 正在处理视频元数据...')
                mtd = await get_video_metadata(f)
                dur, vh, vw = mtd['duration'], mtd['height'], mtd['width']
                th = await screenshot(f, dur, d)
                st = time.time()

                if m.video or f.lower().endswith('.mp4'):
                    sent = await Y.send_video(
                        LOG_GROUP, f, thumb=th, duration=dur, height=vh, width=vw,
                        caption=cap, progress=prog, progress_args=(c, d, p.id, st))
                elif m.audio:
                    sent = await Y.send_audio(
                        LOG_GROUP, f, caption=cap,
                        progress=prog, progress_args=(c, d, p.id, st))
                elif m.photo:
                    sent = await Y.send_photo(
                        LOG_GROUP, f, caption=cap,
                        progress=prog, progress_args=(c, d, p.id, st))
                elif m.video_note:
                    sent = await Y.send_video_note(
                        LOG_GROUP, f,
                        progress=prog, progress_args=(c, d, p.id, st))
                elif m.voice:
                    sent = await Y.send_voice(
                        LOG_GROUP, f,
                        progress=prog, progress_args=(c, d, p.id, st))
                else:
                    sent = await Y.send_document(
                        LOG_GROUP, f, thumb=th, caption=cap,
                        progress=prog, progress_args=(c, d, p.id, st))

                await c.copy_message(d, LOG_GROUP, sent.id)
                await c.delete_messages(d, p.id)
                os.remove(f)
                f = None
                return '完成（大文件）。'

            # 常规上传
            await c.edit_message_text(d, p.id, '⬆️ 正在上传...')
            st = time.time()

            video_exts = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ogv'}
            audio_exts = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.opus', '.aiff', '.ac3'}
            ext = os.path.splitext(f)[1].lower()

            try:
                if m.video or ext in video_exts:
                    await c.edit_message_text(d, p.id, '🎬 正在处理视频元数据...')
                    mtd = await get_video_metadata(f)
                    dur, vh, vw = mtd['duration'], mtd['height'], mtd['width']
                    th = await screenshot(f, dur, d)
                    await c.edit_message_text(d, p.id, '⬆️ 正在上传...')
                    st = time.time()
                    await c.send_video(tcid, f, caption=cap, thumb=th,
                                       width=vw, height=vh, duration=dur,
                                       progress=prog, progress_args=(c, d, p.id, st),
                                       reply_to_message_id=rtmid)
                elif m.video_note:
                    await c.send_video_note(tcid, f,
                                             progress=prog, progress_args=(c, d, p.id, st),
                                             reply_to_message_id=rtmid)
                elif m.voice:
                    await c.send_voice(tcid, f,
                                        progress=prog, progress_args=(c, d, p.id, st),
                                        reply_to_message_id=rtmid)
                elif m.animation:
                    await c.send_animation(tcid, f, caption=cap,
                                            progress=prog, progress_args=(c, d, p.id, st),
                                            reply_to_message_id=rtmid)
                elif m.sticker:
                    await c.send_sticker(tcid, f, reply_to_message_id=rtmid)
                elif m.audio or ext in audio_exts:
                    await c.send_audio(tcid, f, caption=cap, thumb=th,
                                        progress=prog, progress_args=(c, d, p.id, st),
                                        reply_to_message_id=rtmid)
                elif m.photo:
                    await c.send_photo(tcid, f, caption=cap,
                                        progress=prog, progress_args=(c, d, p.id, st),
                                        reply_to_message_id=rtmid)
                else:
                    await c.send_document(tcid, f, caption=cap,
                                           progress=prog, progress_args=(c, d, p.id, st),
                                           reply_to_message_id=rtmid)
            except PeerIdInvalid:
                await c.edit_message_text(
                    d, p.id,
                    '⚠️ 转发失败：Bot 尚未与目标聊天建立会话，请点击启动 Bot 或将其拉入目标群组。'
                )
                return '转发失败。'
            except Exception as e:
                await c.edit_message_text(d, p.id, f'⚠️ 上传失败：{str(e)[:50]}')
                return '上传失败。'

            await c.delete_messages(d, p.id)
            return '完成。'

        except Exception as e:
            try:
                await c.edit_message_text(d, p.id, f'⚠️ 出错：{str(e)[:80]}')
            except Exception:
                pass
            return f'出错：{str(e)[:80]}'

        finally:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    except Exception as e:
        return f'出错：{str(e)[:80]}'


# ─── 公共接口：单条提取 ───────────────────────────────────────────────────────

async def extract_single(pyro_client, message, tg_url: str):
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
        seen_groups: set = set()  # 已处理的相册 media_group_id，避免重复发送

        for j in range(count):
            if should_cancel(uid):
                await pt.edit(f"🚫 已取消，进度：{j}/{count}，成功：{success}")
                break
            await update_batch_progress(uid, j, success)
            try:
                await pt.edit(f"⏳ 正在处理 {j + 1}/{count}，已成功：{success}")
            except Exception:
                pass
            mid = sid + j
            try:
                msg = await get_msg(upload_bot, uc, cid, mid, lt)
                if not msg or getattr(msg, "empty", False):
                    continue

                # 同一相册只处理第一条，跳过其余
                gid = getattr(msg, 'media_group_id', None)
                if gid:
                    if gid in seen_groups:
                        success += 1  # 相册已整体发送，计为成功
                        continue
                    seen_groups.add(gid)

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
