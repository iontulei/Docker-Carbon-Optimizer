# Un-optimized: DCO001 (full python image) + DCO002 (consecutive RUNs) + DCO003 (dev deps)
FROM python:3.12

ENV FLASK_APP=flaskr
ENV FLASK_ENV=development

COPY . /app

WORKDIR /app

RUN apt-get update && apt-get install -y gcc build-essential
RUN pip install --editable .
RUN flask init-db

EXPOSE 5000

CMD [ "flask", "run", "--host=0.0.0.0" ]
