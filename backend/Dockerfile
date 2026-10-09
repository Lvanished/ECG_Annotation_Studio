FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /code
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
RUN useradd --create-home --uid 1000 ecg && mkdir -p /data && chown -R ecg:ecg /data /code
USER ecg
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=5s --start-period=20s --retries=30 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
