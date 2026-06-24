FROM python:3.12.13
RUN pip install flask
COPY . /app
WORKDIR /app
CMD ["python", "app.py"]
