FROM xzixmn/legado-hub@sha256:af7464244a4bb6327da9a78f644354d41d5aca13f8263de56b5bbdb78b4d5732
RUN apt-get update && apt-get install -y --no-install-recommends libarchive13 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir 'libarchive-c>=5.3,<6'
COPY --chown=1000:1000 backend/app /app/backend/app
COPY --chown=1000:1000 frontend/dist /app/frontend/dist
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1,192.168.224.1"]
