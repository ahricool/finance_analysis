FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY qlib_worker/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
RUN pip install --no-cache-dir --no-deps pyqlib==0.9.7
COPY qlib_worker /workspace/qlib_worker
CMD ["uvicorn", "qlib_worker.app:app", "--host", "0.0.0.0", "--port", "8010"]
