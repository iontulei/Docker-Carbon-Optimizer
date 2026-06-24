# Un-optimized: DCO001 (full python, major-only) + DCO004 (no .dockerignore) + DCO006 (unpinned)
FROM python:3

WORKDIR /usr/src/app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["python", "./app.py"]
