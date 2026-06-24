FROM python
RUN pip install flask
COPY . /app
WORKDIR /app
CMD ["python", "app.py"]
