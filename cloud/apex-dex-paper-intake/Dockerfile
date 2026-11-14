FROM python:3.12-slim
WORKDIR /app
COPY paper_live.py cloud_intake.py paper_dashboard.html ./
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
CMD ["python", "cloud_intake.py"]
