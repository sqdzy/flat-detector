FROM python:3.13.5-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
  && useradd --system --uid 10001 --create-home app
COPY flat_detector /app/flat_detector
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "flat_detector.web:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
