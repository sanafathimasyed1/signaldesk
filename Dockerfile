FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY main.py ./
COPY salesintel ./salesintel
COPY static ./static
COPY prompts ./prompts
COPY data ./data

EXPOSE 8000
CMD ["python", "main.py"]
