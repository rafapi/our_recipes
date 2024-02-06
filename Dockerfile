FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

RUN apt-get update \
    && apt-get -y install netcat gcc \
    && apt-get clean

RUN pip install --upgrade pip

COPY . /app

RUN pip install -r requirements.txt

CMD ["uvicorn", "your_app:app", "--host", "0.0.0.0", "--port", "8000"]
