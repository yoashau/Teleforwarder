import re
import os
import string
import random
from telethon import events, Button
from shared_client import client as gf
from utils.func import get_user_data_key, save_user_data, users_collection

VIDEO_EXTENSIONS = {
    'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm',
    'mpeg', 'mpg', '3gp'
}

# 对话状态字典（由 plugins/login.py 的 /cancel 统一清理）
active_conversations = {}


@gf.on(events.NewMessage(incoming=True, pattern='/setting'))
async def settings_command(event):
    user_id = event.sender_id
    await _send_settings_menu(event.chat_id, user_id)


async def _send_settings_menu(chat_id, user_id):
    buttons = [
        [
            Button.inline('📝 自定义名称', b'setrename'),
            Button.inline('🖼️ 设置封面', b'setthumb'),
        ],
        [
            Button.inline('💬 预设文案', b'setcaption'),
            Button.inline('🔄 替换规则', b'setreplacement'),
        ],
        [
            Button.inline('🗑️ 删词规则', b'delete'),
            Button.inline('📤 发送目标', b'setchat'),
        ],
        [
            Button.inline('❌ 移除封面', b'remthumb'),
            Button.inline('🔁 重置全部', b'reset'),
        ],
    ]
    await gf.send_message(chat_id, "⚙️ **个性化设置**\n请选择要配置的项目：", buttons=buttons)


@gf.on(events.CallbackQuery)
async def callback_query_handler(event):
    user_id = event.sender_id

    action_map = {
        b'setrename': (
            'setrename',
            '📝 **自定义文件名称**\n\n'
            '请发送你想在文件名末尾附加的标签（如频道名或个人标识）。\n'
            '发送 /cancel 取消。'
        ),
        b'setchat': (
            'setchat',
            '📤 **设置发送目标**\n\n'
            '请发送目标聊天的 ID（以 `-100` 开头）。\n'
            '如需发送到频道的某个话题，格式为 `-100频道ID/话题ID`，例如：`-1004783898/12`\n'
            '发送 /cancel 取消。'
        ),
        b'setcaption': (
            'setcaption',
            '💬 **设置预设文案**\n\n'
            '请发送你想在每个文件下方附加的文字内容。\n'
            '发送 /cancel 取消。'
        ),
        b'setreplacement': (
            'setreplacement',
            '🔄 **设置替换规则**\n\n'
            '格式：`\'原词\' \'替换词\'`\n'
            '示例：`\'Team SPY\' \'我的频道\'`\n'
            '发送 /cancel 取消。'
        ),
        b'delete': (
            'deleteword',
            '🗑️ **设置删词规则**\n\n'
            '请发送要从文件名/文案中删除的词（多个词用空格分隔）。\n'
            '发送 /cancel 取消。'
        ),
        b'setthumb': (
            'setthumb',
            '🖼️ **设置自定义封面**\n\n'
            '请直接发送一张图片作为所有文件的默认封面。\n'
            '发送 /cancel 取消。'
        ),
    }

    if event.data in action_map:
        conv_type, prompt = action_map[event.data]
        await _start_conversation(event, user_id, conv_type, prompt)
        return

    if event.data == b'remthumb':
        try:
            thumb_path = f'{user_id}.jpg'
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
                await event.respond('✅ 封面已移除。')
            else:
                await event.respond('⚠️ 未找到自定义封面。')
        except Exception as e:
            await event.respond(f'❌ 移除封面失败：{e}')
        return

    if event.data == b'reset':
        try:
            await users_collection.update_one(
                {'user_id': user_id},
                {'$unset': {
                    'delete_words': '',
                    'replacement_words': '',
                    'rename_tag': '',
                    'caption': '',
                    'chat_id': '',
                }}
            )
            thumb_path = f'{user_id}.jpg'
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            await event.respond('✅ 全部设置已重置。如需退出登录，请使用 /logout。')
        except Exception as e:
            await event.respond(f'❌ 重置失败：{e}')
        return


async def _start_conversation(event, user_id, conv_type, prompt):
    if user_id in active_conversations:
        await event.respond('⚠️ 已有进行中的操作，已自动取消并开启新操作。')
    msg = await event.respond(prompt)
    active_conversations[user_id] = {'type': conv_type, 'message_id': msg.id}


@gf.on(events.NewMessage(incoming=True))
async def handle_conversation_input(event):
    user_id = event.sender_id
    if user_id not in active_conversations:
        return
    if event.message.text and event.message.text.startswith('/'):
        return

    conv_type = active_conversations[user_id]['type']

    handlers = {
        'setchat': _handle_setchat,
        'setrename': _handle_setrename,
        'setcaption': _handle_setcaption,
        'setreplacement': _handle_setreplacement,
        'addsession': _handle_addsession,
        'deleteword': _handle_deleteword,
        'setthumb': _handle_setthumb,
    }

    if conv_type in handlers:
        await handlers[conv_type](event, user_id)

    active_conversations.pop(user_id, None)


async def _handle_setchat(event, user_id):
    try:
        chat_id = event.text.strip()
        await save_user_data(user_id, 'chat_id', chat_id)
        await event.respond('✅ 发送目标已设置！')
    except Exception as e:
        await event.respond(f'❌ 设置失败：{e}')


async def _handle_setrename(event, user_id):
    tag = event.text.strip()
    await save_user_data(user_id, 'rename_tag', tag)
    await event.respond(f'✅ 文件名标签已设置为：`{tag}`')


async def _handle_setcaption(event, user_id):
    caption = event.text
    await save_user_data(user_id, 'caption', caption)
    await event.respond('✅ 预设文案已保存！')


async def _handle_setreplacement(event, user_id):
    match = re.match(r"'(.+)' '(.+)'", event.text)
    if not match:
        await event.respond("❌ 格式不正确。正确格式：`'原词' '替换词'`")
        return
    word, replace_word = match.groups()
    delete_words = await get_user_data_key(user_id, 'delete_words', [])
    if word in delete_words:
        await event.respond(f"❌ 词语 `{word}` 在删词列表中，无法设置替换规则。")
        return
    replacements = await get_user_data_key(user_id, 'replacement_words', {})
    replacements[word] = replace_word
    await save_user_data(user_id, 'replacement_words', replacements)
    await event.respond(f"✅ 替换规则已保存：`{word}` → `{replace_word}`")


async def _handle_addsession(event, user_id):
    session_string = event.text.strip()
    await save_user_data(user_id, 'session_string', session_string)
    await event.respond('✅ Session 已添加！')


async def _handle_deleteword(event, user_id):
    words_to_delete = event.message.text.split()
    delete_words = await get_user_data_key(user_id, 'delete_words', [])
    delete_words = list(set(delete_words + words_to_delete))
    await save_user_data(user_id, 'delete_words', delete_words)
    await event.respond(f"✅ 已添加删词：`{'、'.join(words_to_delete)}`")


async def _handle_setthumb(event, user_id):
    if event.photo:
        temp_path = await event.download_media()
        try:
            thumb_path = f'{user_id}.jpg'
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            os.rename(temp_path, thumb_path)
            await event.respond('✅ 封面已更新！')
        except Exception as e:
            await event.respond(f'❌ 保存封面失败：{e}')
    else:
        await event.respond('❌ 请发送一张图片。操作已取消。')


def generate_random_name(length=7):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


async def rename_file(file, sender, edit):
    try:
        delete_words = await get_user_data_key(sender, 'delete_words', [])
        custom_rename_tag = await get_user_data_key(sender, 'rename_tag', '')
        replacements = await get_user_data_key(sender, 'replacement_words', {})

        last_dot_index = str(file).rfind('.')
        if last_dot_index != -1 and last_dot_index != 0:
            ggn_ext = str(file)[last_dot_index + 1:]
            if ggn_ext.isalpha() and len(ggn_ext) <= 9:
                if ggn_ext.lower() in VIDEO_EXTENSIONS:
                    original_file_name = str(file)[:last_dot_index]
                    file_extension = 'mp4'
                else:
                    original_file_name = str(file)[:last_dot_index]
                    file_extension = ggn_ext
            else:
                original_file_name = str(file)[:last_dot_index]
                file_extension = 'mp4'
        else:
            original_file_name = str(file)
            file_extension = 'mp4'

        for word in delete_words:
            original_file_name = original_file_name.replace(word, '')

        for word, replace_word in replacements.items():
            original_file_name = original_file_name.replace(word, replace_word)

        new_file_name = f'{original_file_name} {custom_rename_tag}.{file_extension}'.strip()
        os.rename(file, new_file_name)
        return new_file_name
    except Exception as e:
        print(f"重命名文件出错: {e}")
        return file
