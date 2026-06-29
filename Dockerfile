FROM python:3.12-slim

LABEL oci-companion=alpha

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OCI_COMPANION_CONTAINER_IMAGE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY DocumentRoot ./DocumentRoot
COPY engine ./engine
COPY start.sh ./

RUN chmod 755 /app/start.sh

EXPOSE 8080

ENTRYPOINT ["/app/start.sh"]
