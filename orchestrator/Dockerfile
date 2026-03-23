FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY ../shared /app/shared 2>/dev/null || true
CMD ["python", "-u", "main.py"]

