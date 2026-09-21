FROM python:3.10-slim

WORKDIR /app

# Cài đặt các thư viện cần thiết
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn vào container
COPY . .

# Chạy Bot ngầm 24/7
CMD ["python", "background_runner.py"]
