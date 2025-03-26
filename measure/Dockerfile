# Use an official Python runtime base image.
FROM python:3.8-slim

# Set a working directory in the container.
WORKDIR /app

# Copy the measurement script into the container.
COPY measure.py .

# Install any necessary packages. For this example, we use requests.
RUN pip install --no-cache-dir requests

# The container expects a URL argument when launched.
ENTRYPOINT ["python", "measure.py"]