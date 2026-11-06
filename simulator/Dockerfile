FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY simulator/ simulator/

CMD ["python", "-m", "simulator.main", "--speedup", "1.0", "--broker", "mosquitto", "--port", "1883"]

