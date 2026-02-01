FROM python:3.10-slim

WORKDIR /app

# Install dependencies (skip evdev - not needed in container)
COPY requirements.txt .
RUN grep -v -E '^\s*#|^\s*$|evdev' requirements.txt > /tmp/reqs.txt && \
    pip install --no-cache-dir -r /tmp/reqs.txt

# Copy server source
COPY *.py .
COPY config.example.yaml .

CMD ["python", "-m", "main"]
