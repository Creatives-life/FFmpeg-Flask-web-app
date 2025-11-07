# Dockerfile
FROM python:3.11-slim

# Install ffmpeg and fonts
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# Create app dir
WORKDIR /app
COPY requirements.txt .

# Install python deps
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app
COPY . /app

# Create upload directories
RUN mkdir -p /app/uploads /app/outputs

ENV PORT=5000
EXPOSE 5000

# Use gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app", "--workers", "1"]
