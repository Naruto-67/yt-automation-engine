# Dockerfile — Ghost Engine Enterprise
FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies (FFmpeg for rendering, eSpeak for TTS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    espeak-ng \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_sm

# Copy the rest of the Ghost Engine architecture
COPY . .

# Ensure memory and assets directories exist
RUN mkdir -p memory assets config

# Default command runs the main pipeline
CMD ["python", "main.py"]
