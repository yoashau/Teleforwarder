from pyrogram import filters

# ─── 登录流程状态追踪 ────────────────────────────────────────────────────────
user_steps = {}


def login_filter_func(_, __, message):
    return message.from_user.id in user_steps


login_in_progress = filters.create(login_filter_func)


def set_user_step(user_id, step=None):
    if step:
        user_steps[user_id] = step
    else:
        user_steps.pop(user_id, None)


def get_user_step(user_id):
    return user_steps.get(user_id)


# ─── 设置面板对话状态追踪 ────────────────────────────────────────────────────
settings_states = {}


def settings_filter_func(_, __, message):
    return message.from_user.id in settings_states


settings_in_progress = filters.create(settings_filter_func)
