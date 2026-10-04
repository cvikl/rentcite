# Homerule: FastAPI + decision engine + the committed outputs and model cache. The demo runs offline from out/ and cache/;
# "Add a law" needs an API key in deploy/.env.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY data ./data
COPY out ./out
COPY cache ./cache
COPY README.md ./
ENV PYTHONUNBUFFERED=1 HOMERULE_CACHE=1
EXPOSE 8795
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8795", "--proxy-headers", "--forwarded-allow-ips", "*"]
