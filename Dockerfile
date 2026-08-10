FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# T-Bank currently presents a certificate chain rooted at Russian Trusted Root
# CA.  The certificate is added to the OS trust store so TLS verification stays
# enabled for both API and worker requests.
COPY certs/russian-trusted-root-ca.crt /usr/local/share/ca-certificates/russian-trusted-root-ca.crt
RUN apt-get update && \
    apt-get install --no-install-recommends -y ca-certificates tzdata && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && \
    useradd --system --gid app --home-dir /app app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/media /app/logs && \
    chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
