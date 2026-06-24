FROM python:3.12
RUN apt-get update
RUN apt-get install -y curl
RUN pip install flask gunicorn
COPY . /app
WORKDIR /app
CMD ["gunicorn", "app:app"]
