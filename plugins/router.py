"""
router.py — Telegram 链接路由器
处理逻辑：
  1. 所有非指令的私信文本消息
  2. 正则提取消息中的全部 Telegram URL
  3. 单条链接 → extract_single；链接后跟数字 → extract_range 批量提取
"""

import re
import asyncio
from pyrogram import filters
from shared_client import app
from utils.func import is_whitelisted
from utils.custom_filters import login_in_progress
from plugins.batch import extract_single, extract_range

# ─── Telegram 链接正则 ────────────────────────────────────────────────────────

_TG_RE = re.compile(
    r'https://t\.me/(?:c/)?[^/\s]+/\d+(?:/\d+)?',
    re.IGNORECASE
)


def _extract_tg_urls(text: str) -> list[str]:
    return _TG_RE.findall(text)


def _parse_count_suffix(text: str, url: str) -> int:
    """
    检测 URL 后紧跟的数字，如 "https://t.me/... 50"
    返回解析到的数量（最小 1）。
    """
    idx = text.find(url)
    if idx == -1:
        return 1
    after = text[idx + len(url):].strip()
    m = re.match(r'^(\d+)', after)
    if m:
        n = int(m.group(1))
        return max(1, min(n, 10000))  # 上限 10000
    return 1


# ─── 主路由处理器 ─────────────────────────────────────────────────────────────

@app.on_message(
    filters.incoming & filters.text & filters.private
    & ~login_in_progress
    & ~filters.command([
        'start', 'help', 'login', 'logout', 'cancel',
        'bindbot', 'unbindbot', 'me', 'setting', 'set',
        'allow', 'ban',
    ])
)
async def smart_router(client, message):
    uid = message.from_user.id

    # 白名单检查
    if not await is_whitelisted(uid):
        await message.reply("⚠️ 你没有使用权限，请联系管理员。")
        return

    text = message.text
    urls = _extract_tg_urls(text)

    if not urls:
        # 没有 Telegram 链接，忽略
        return

    # 去重，保留顺序
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    for url in unique_urls:
        try:
            count = _parse_count_suffix(text, url)
            if count > 1:
                await extract_range(client, message, url, count)
            else:
                await extract_single(client, message, url)

        except Exception as e:
            await message.reply(
                f"⚠️ 处理链接时出错：\n`{url[:80]}`\n\n"
                f"错误信息：{str(e)[:100]}"
            )

        # 多链接之间稍作间隔，避免 flood
        if len(unique_urls) > 1:
            await asyncio.sleep(2)
