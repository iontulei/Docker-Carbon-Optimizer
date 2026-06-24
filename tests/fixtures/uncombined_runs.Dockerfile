FROM ubuntu:22.04
RUN apt-get update
RUN apt-get install -y curl wget
RUN apt-get install -y git
RUN pip install requests
COPY . /app
WORKDIR /app
CMD ["python", "app.py"]
