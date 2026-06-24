FROM python:3.12-slim
RUN apt-get update && apt-get install -y gcc build-essential python3-dev
RUN pip install numpy pandas
COPY . /app
CMD ["python", "app.py"]
