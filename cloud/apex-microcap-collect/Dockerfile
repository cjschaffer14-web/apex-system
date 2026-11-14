FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY collector.py cloud_store.py manifest.json ./
USER 65534:65534
CMD ["python", "collector.py"]
