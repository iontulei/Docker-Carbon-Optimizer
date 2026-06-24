FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask gunicorn
COPY . /app
WORKDIR /app
CMD ["gunicorn", "app:app"]
