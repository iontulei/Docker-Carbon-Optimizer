FROM ubuntu:22.04
RUN apt-get update && \
    apt-get install -y curl wget && \
    apt-get install -y git && \
    pip install requests
COPY . /app
WORKDIR /app
CMD ["python", "app.py"]
