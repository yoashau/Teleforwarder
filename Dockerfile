FROM python:3.10-slim

# 安装系统依赖（ffmpeg 必需，用于音视频处理）
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ffmpeg \
        python3-pip \
        wget \
        bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip wheel
RUN pip3 install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

CMD ["python3", "main.py"]
