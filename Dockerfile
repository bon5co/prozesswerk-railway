FROM python:3.12-slim

# Upstream guidoesser/prozesswerk (MIT) pinned to one commit; bump PROZESSWERK_REF to update.
ARG PROZESSWERK_REF=0a6ea5a795ac7a59c62a5b8553f522cda6508d86

WORKDIR /app

# Node.js 22 is needed by the ELK.js auto-layout the backend shells out to.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/guidoesser/prozesswerk/archive/${PROZESSWERK_REF}.tar.gz" \
    | tar xz --strip-components=1 -C /app \
    && pip install --no-cache-dir -r /app/backend/requirements.txt \
    && cd /app/backend && npm ci --omit=dev \
    && touch /app/backend/__init__.py

COPY railway_app.py /app/railway_app.py

# Literals live here so the Railway deploy form needs only the deployer's own LLM key.
ENV PORT=8080 \
    PROZESSWERK_USERNAME=admin \
    LLM_BASE_URL=https://api.openai.com/v1 \
    LLM_MODEL=gpt-4o \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["python", "/app/railway_app.py"]
