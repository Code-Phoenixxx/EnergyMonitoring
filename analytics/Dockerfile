FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY database/ database/
COPY simulator/ simulator/
COPY analytics/ analytics/

CMD ["python", "-m", "analytics.worker", "--interval", "5.0"]

