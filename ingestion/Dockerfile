FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY database/ database/
COPY simulator/ simulator/
COPY ingestion/ ingestion/

CMD ["python", "-m", "ingestion.main", "--broker", "mosquitto", "--port", "1883"]

