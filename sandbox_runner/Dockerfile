FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY server.py .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8200"]
