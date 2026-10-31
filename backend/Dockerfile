FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port \"$BACKEND_PORT\""]