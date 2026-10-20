FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY . .

FROM base AS web
ARG DATA_SOURCES=""
RUN if [ -n "$DATA_SOURCES" ]; then python scripts/fetch_data.py $DATA_SOURCES; fi
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "mhbot.server"]

FROM base AS llm
RUN pip install --no-cache-dir --only-binary=llama-cpp-python -r requirements-llm.txt \
    || (apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
        && pip install --no-cache-dir -r requirements-llm.txt \
        && rm -rf /var/lib/apt/lists/*)
ARG MHBOT_MODEL_REPO
ARG MHBOT_MODEL_FILE
ARG MHBOT_MODEL_REVISION=""
ENV MHBOT_MODELS_DIR=/models \
    MHBOT_MODEL_REPO=$MHBOT_MODEL_REPO \
    MHBOT_MODEL_FILE=$MHBOT_MODEL_FILE \
    MHBOT_MODEL_REVISION=$MHBOT_MODEL_REVISION \
    MHBOT_LLM_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1
RUN python -m mhbot.model pull
EXPOSE 8081
CMD ["python", "-m", "mhbot.model", "serve"]
