FROM python:3.10-slim

WORKDIR /app

# Копируем всё, включая .env
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN if [ -f bot.lock ]; then rm bot.lock; fi

CMD ["python", "main.py"]
