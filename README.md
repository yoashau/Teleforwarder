# 私有 Telegram 内容提取机器人

专为个人及白名单好友打造的 Telegram 内容提取机器人。摒弃了商业化限制与付费模块，经过彻底重构，拥有**"发链接即提取"**的智能路由体验。

## 功能特点

- **纯粹私有**：内置白名单系统，告别强制订阅和使用限制
- **智能路由**：无需任何指令，直接发送 Telegram 链接自动提取
- **突破 Telegram 限制**：提取公开/私密群组和频道中"禁止保存和转发"的内容
- **4GB 超大文件**：支持绑定 Premium 会话，突破机器人 2GB 上传限制
- **高度个性化**：自定义文件名后缀、词汇替换/删除规则、全局视频封面

---

## 快速部署

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/zh-CN/templates/V0WIKI)

> Docker 本地部署：
> ```bash
> docker build -t downloader .
> docker run -d -e API_ID=值 -e API_HASH=值 -e BOT_TOKEN=值 -e MONGO_DB=值 -e OWNER_ID=值 downloader
> ```

---

## 环境变量配置

### 参数速览

| 参数 | 必填 | 默认值 | 用途 |
|------|------|--------|------|
| `API_ID` | 是 | — | Telegram API ID |
| `API_HASH` | 是 | — | Telegram API Hash |
| `BOT_TOKEN` | 是 | — | 机器人令牌 |
| `MONGO_DB` | 是 | — | MongoDB 连接字符串 |
| `OWNER_ID` | 是 | — | 管理员用户 ID（多个用空格分隔） |
| `DB_NAME` | 否 | `telegram_downloader` | MongoDB 数据库名称 |
| `STRING` | 否 | — | Premium 账号 Session，解锁 4GB 上传 |
| `LOG_GROUP` | 否 | — | 大文件中转频道 ID（使用 `STRING` 时必填） |
| `MASTER_KEY` | 否 | 内置默认值 | 用户会话 AES 加密主密钥（强烈建议自定义） |
| `IV_KEY` | 否 | 内置默认值 | 用户会话 AES 加密盐值（强烈建议自定义） |

---

### 必填参数详解

#### `API_ID` / `API_HASH`

Telegram 官方 API 密钥，机器人与用户会话均依赖此项。

1. 访问 [my.telegram.org](https://my.telegram.org) 用 Telegram 手机号登录
2. 点击 **API development tools**，随意填写应用名称后创建
3. 页面展示的 `App api_id`（数字）和 `App api_hash`（32位字符串）即为所需

```
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
```

#### `BOT_TOKEN`

机器人身份令牌，由 @BotFather 颁发。

1. 打开 [@BotFather](https://t.me/BotFather)，发送 `/newbot`
2. 按提示设置机器人名称和用户名（用户名须以 `bot` 结尾）
3. 创建成功后 BotFather 会回复 Token

```
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
```

#### `OWNER_ID`

管理员的 Telegram 用户数字 ID。管理员自动拥有使用权限，并可通过 `/allow`、`/ban` 管理白名单。

打开 [@getidsbot](https://t.me/getidsbot) 发送任意消息即可获取自己的 ID。多个管理员用空格分隔：

```
OWNER_ID=123456789 987654321
```

#### `MONGO_DB`

MongoDB 连接字符串，用于存储白名单、用户会话（加密）和个性化设置。推荐使用 [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) 免费套餐：

1. 注册并创建免费 **M0 Cluster**
2. **Database Access** 中创建数据库用户并记住密码
3. **Network Access** 中添加 `0.0.0.0/0` 允许所有 IP
4. **Connect → Drivers** 复制连接字符串，将 `<password>` 替换为实际密码

```
MONGO_DB=mongodb+srv://admin:密码@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

---

### 可选参数详解

#### `DB_NAME`

MongoDB 数据库名称，默认 `telegram_downloader`。单项目使用保持默认即可，多项目共用同一 MongoDB 实例时建议修改以避免冲突。

#### `STRING` 与 `LOG_GROUP`

这两个参数配套使用，用于解锁 4GB 大文件上传能力。

**`STRING`** 是一个 **Premium 账号**的 Pyrogram Session String。配置后，机器人以该 Premium 身份上传文件，突破普通机器人 2GB 单文件上传限制。

> 与 `/login` 的区别：`/login` 是用户自己登录账号用于**读取**私有频道内容；`STRING` 是机器人的专用**上传**客户端，两者解决不同问题，互不替代。

生成 Session String（需要一个 Premium 账号）：
```python
from pyrogram import Client
with Client("my_session", api_id=你的API_ID, api_hash="你的API_HASH") as app:
    print(app.export_session_string())
```
按提示输入手机号和验证码，输出的长字符串即为 `STRING` 的值。

> Session String 等同于该账号的完整登录凭证，请勿泄露。

**`LOG_GROUP`** 是大文件上传的中转频道 ID。上传超大文件时，机器人先将文件发至此频道，再转发到用户的实际目标位置。配置了 `STRING` 就必须同时设置此项：

1. 创建一个私有频道，将机器人设为管理员（需要发送消息权限）
2. 通过 [@getidsbot](https://t.me/getidsbot) 获取频道 ID（以 `-100` 开头）

```
STRING=BQABsAIAAT...
LOG_GROUP=-1009876543210
```

#### `MASTER_KEY` / `IV_KEY`

用于 AES-GCM 加密的密钥对。用户 `/login` 生成的会话凭证以此加密后存入数据库，防止数据库泄露时凭证被直接读取。

代码内置了默认值可直接运行，但**强烈建议正式部署时替换为自己的随机字符串**：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # MASTER_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(12))"  # IV_KEY
```

> **注意**：这两个值部署后不能修改。一旦修改，所有已登录用户的会话将无法解密，需重新 `/login`。

---

## 使用方法

部署后在 Telegram 找到机器人，发送 `/start`。

**核心用法**：直接发送 Telegram 消息链接，支持批量：

```
帮我提取这几个：
https://t.me/c/123456/789
https://t.me/channelname/100 5
```

> 链接后加空格和数字（如 `100 5`）表示从该消息起连续提取 5 条。

### 指令列表

| 指令 | 权限 | 说明 |
|------|------|------|
| `/allow <user_id>` | 管理员 | 将用户加入白名单 |
| `/ban <user_id>` | 管理员 | 将用户移出白名单 |
| `/start` | 白名单 | 启动机器人 |
| `/login` | 白名单 | 登录 Telegram 账号（用于提取私有频道内容） |
| `/logout` | 白名单 | 退出 Telegram 账号登录 |
| `/bindbot <token>` | 白名单 | 绑定辅助机器人（用于大文件分流上传） |
| `/unbindbot` | 白名单 | 解绑辅助机器人 |
| `/setting` | 白名单 | 个性化设置（文件名、封面、文案、替换规则等） |
| `/me` | 白名单 | 查看自己的账号状态 |
| `/cancel` | 白名单 | 取消当前进行中的操作 |
