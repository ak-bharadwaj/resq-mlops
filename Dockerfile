FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.lock /workspace/
RUN pip install --no-cache-dir -r requirements.lock

COPY . /workspace/

CMD ["make", "run"]
