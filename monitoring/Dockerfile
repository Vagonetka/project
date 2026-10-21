FROM python:3.13.2-slim

WORKDIR /usr/app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PROMETHEUS_MULTIPROC_DIR="/dev/shm"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./checker .

EXPOSE 8081

ENTRYPOINT [ "gunicorn", "-b", "0.0.0.0:8081", "server:app" ]
CMD [ "-c", "config.py", "-w", "1", "--threads", "2", "--max-requests", "10000" ]