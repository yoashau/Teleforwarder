import time
import os
import re
import cv2
import logging
import asyncio
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_DB as MONGO_URI, DB_NAME

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_LINK_PATTERN = re.compile(r'(https?://)?(t\.me|telegram\.me)/([^/]+)(/(\d+))?')
PRIVATE_LINK_PATTERN = re.compile(r'(https?://)?(t\.me|telegram\.me)/c/(\d+)(/(\d+))?')
VIDEO_EXTENSIONS = {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "mpeg", "mpg", "3gp"}

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
users_collection = db["users"]
statistics_collection = db["statistics"]


def is_private_link(link):
    return bool(PRIVATE_LINK_PATTERN.match(link))


def thumbnail(sender):
    return f'{sender}.jpg' if os.path.exists(f'{sender}.jpg') else None


def hhmmss(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def E(L):
    """解析 Telegram 链接，返回 (channel_id, message_id, link_type)"""
    private_match = re.match(r'https://t\.me/c/(\d+)/(?:\d+/)?(\d+)', L)
    public_match = re.match(r'https://t\.me/([^/]+)/(?:\d+/)?(\d+)', L)

    if private_match:
        return f'-100{private_match.group(1)}', int(private_match.group(2)), 'private'
    elif public_match:
        return public_match.group(1), int(public_match.group(2)), 'public'

    return None, None, None


def get_display_name(user):
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.last_name:
        return user.last_name
    elif user.username:
        return user.username
    else:
        return "未知用户"


def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '_', filename)


async def is_private_chat(event):
    return event.is_private


async def save_user_data(user_id, key, value):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {key: value}},
        upsert=True
    )


async def get_user_data_key(user_id, key, default=None):
    user_data = await users_collection.find_one({"user_id": int(user_id)})
    return user_data.get(key, default) if user_data else default


async def get_user_data(user_id):
    try:
        user_data = await users_collection.find_one({"user_id": user_id})
        return user_data
    except Exception:
        return None


async def save_user_session(user_id, session_string):
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"session_string": session_string, "updated_at": datetime.now()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"保存 session 出错 {user_id}: {e}")
        return False


async def remove_user_session(user_id):
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"session_string": ""}}
        )
        return True
    except Exception as e:
        logger.error(f"移除 session 出错 {user_id}: {e}")
        return False


async def save_user_bot(user_id, bot_token):
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"bot_token": bot_token, "updated_at": datetime.now()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"保存机器人令牌出错 {user_id}: {e}")
        return False


async def remove_user_bot(user_id):
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"bot_token": ""}}
        )
        return True
    except Exception as e:
        logger.error(f"移除机器人令牌出错 {user_id}: {e}")
        return False


async def process_text_with_rules(user_id, text):
    if not text:
        return ""
    try:
        replacements = await get_user_data_key(user_id, "replacement_words", {})
        delete_words = await get_user_data_key(user_id, "delete_words", [])
        processed_text = text
        for word, replacement in replacements.items():
            processed_text = processed_text.replace(word, replacement)
        if delete_words:
            words = processed_text.split()
            filtered_words = [w for w in words if w not in delete_words]
            processed_text = " ".join(filtered_words)
        return processed_text
    except Exception as e:
        logger.error(f"处理文本规则出错: {e}")
        return text


async def screenshot(video: str, duration: int, sender: str) -> str | None:
    existing_screenshot = f"{sender}.jpg"
    if os.path.exists(existing_screenshot):
        return existing_screenshot

    time_stamp = hhmmss(duration // 2)
    output_file = datetime.now().isoformat("_", "seconds") + ".jpg"
    cmd = ["ffmpeg", "-ss", time_stamp, "-i", video, "-frames:v", "1", output_file, "-y"]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        return None
    if os.path.isfile(output_file):
        return output_file
    print(f"FFmpeg 错误: {stderr.decode().strip()}")
    return None


async def get_video_metadata(file_path):
    default_values = {'width': 1, 'height': 1, 'duration': 1}

    def _extract_metadata():
        try:
            vcap = cv2.VideoCapture(file_path)
            if not vcap.isOpened():
                return default_values
            width = round(vcap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = round(vcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = vcap.get(cv2.CAP_PROP_FPS)
            frame_count = vcap.get(cv2.CAP_PROP_FRAME_COUNT)
            vcap.release()
            if fps <= 0 or frame_count <= 0:
                return default_values
            duration = round(frame_count / fps)
            return {'width': width, 'height': height, 'duration': max(duration, 1)}
        except Exception as e:
            logger.error(f"视频元数据提取出错: {e}")
            return default_values

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract_metadata)
    except Exception as e:
        logger.error(f"获取视频元数据出错: {e}")
        return default_values


# ─── 白名单管理 ───────────────────────────────────────────────────────────────

async def add_to_whitelist(user_id: int) -> bool:
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_whitelisted": True}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"添加白名单出错 {user_id}: {e}")
        return False


async def remove_from_whitelist(user_id: int) -> bool:
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_whitelisted": False}}
        )
        return True
    except Exception as e:
        logger.error(f"移除白名单出错 {user_id}: {e}")
        return False


async def is_whitelisted(user_id: int) -> bool:
    from config import OWNER_ID
    if user_id in OWNER_ID:
        return True
    try:
        user_data = await users_collection.find_one({"user_id": user_id})
        return bool(user_data and user_data.get("is_whitelisted", False))
    except Exception as e:
        logger.error(f"检查白名单出错 {user_id}: {e}")
        return False
