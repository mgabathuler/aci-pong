# Use an official Python runtime base image.
FROM python:3.8-slim

# Set a working directory in the container.
WORKDIR /app

# Install any necessary packages.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the measurement script into the container.
COPY aci-pong.py .

# The container expects a URL argument when launched.
ENTRYPOINT ["python", "aci-pong.py"]