FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir pipenv \
    && pipenv install --system --deploy --ignore-pipfile

COPY . .

EXPOSE 8765
EXPOSE 8766

CMD ["python", "server.py", "--mode", "rest"]
