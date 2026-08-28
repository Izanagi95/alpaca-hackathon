FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

CMD ["uvicorn", "app.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
