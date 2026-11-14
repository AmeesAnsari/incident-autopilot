FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY incident_autopilot ./incident_autopilot
RUN pip install --no-cache-dir . && useradd --create-home app && mkdir /data && chown app /data

USER app
ENV AUTOPILOT_DB=/data/autopilot.db
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "incident_autopilot.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
