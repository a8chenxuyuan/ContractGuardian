FROM python:3.11-slim-bookworm

WORKDIR /app

# 安装系统依赖（WeasyPrint、PyMuPDF 等需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libpango1.0-0 \
    libgdk-pixbuf2.0-0 \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
