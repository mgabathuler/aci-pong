#!/usr/bin/env python3
"""
This script spawns Azure Container Instances as one-off jobs to measure the
response time of defined webpages. It picks a random region from a list of viable
regions for each measurement. Once the job completes, it retrieves logs (which the
measurement container is expected to output as a number indicating ms elapsed),
and then records that as a Prometheus metric.
"""

import os
import time
import random
import uuid
import logging
from datetime import datetime

import requests

# Azure container instance SDK
from azure.identity import DefaultAzureCredential
from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    ContainerGroup,
    Container,
    ResourceRequirements,
    ResourceRequests,
    OperatingSystemTypes,
    ContainerGroupRestartPolicy,
    ImageRegistryCredential,
    Port,
    ContainerPort,
)

# Prometheus client
from prometheus_client import start_http_server, Gauge

# Setup basic logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------
# Global Configurations
# ---------------------------

# Azure Subscription ID must be available as env variable.
AZURE_SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")
if not AZURE_SUBSCRIPTION_ID:
    raise ValueError("AZURE_SUBSCRIPTION_ID environment variable is not set")

# The resource group in which to create container instances
AZURE_RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP", "my-resource-group")
# The container image that performs the measurement.
# This image should contain a script that accepts the URL as argument
# and outputs (logs) a single floating-point number representing response time (ms)
MEASURE_IMAGE = os.environ.get("MEASURE_IMAGE", "myregistry.azurecr.io/webpage-measure:latest")

# If image requires credentials, these environment variables (or similar) must be set
# For this example, we assume public image or that DefaultAzureCredential handles authentication.
# A registry username and password may be provided as environment variables if needed.

# The file path from which to load webpages to monitor (each URL on a new line).
WEBPAGES_CONFIG_PATH = os.environ.get("WEBPAGES_CONFIG_PATH", "/etc/webpages/webpages.txt")

# A list of viable Azure regions
AZURE_REGIONS = [
    "eastus", "westus", "centralus", "northeurope", "westeurope",
    "southeastasia", "eastasia"
]

# Prometheus gauge that will hold the response time metric
# Labels: target (the webpage URL) and region (the Azure region used for measurement)
webpage_response_time = Gauge("webpage_response_time_ms", "Response time in milliseconds",
                              ["target", "region", "timestamp"])

# Delay (in seconds) between measurement cycles
MEASUREMENT_INTERVAL = 15

# Maximum number of seconds to wait for an ACI container group job to finish
ACR_TIMEOUT = 180

# ---------------------------
# Helper functions
# ---------------------------

def read_webpages(config_path):
    """Reads a list of webpages from a given file."""
    try:
        with open(config_path, "r") as f:
            urls = [line.strip() for line in f.readlines() if line.strip()]
        return urls
    except Exception as e:
        logger.error(f"Error reading {config_path}: {e}")
        return []

def create_container_group(client, region, url):
    """
    Creates an ACI container group that runs a one-shot container to measure the response time.
    Returns the name of the container group that was created.
    """
    group_name = f"measure-{uuid.uuid4().hex[:8]}"
    container_name = "measure"

    # Command for the container: call the measurement script with the target URL.
    # The measurement container is expected to output the elapsed time.
    # In this example, we assume the container has a script at /app/measure.py.
    command = ["python", "/app/measure.py", "--url", url]

    container_resource_requests = ResourceRequests(memory_in_gb=0.5, cpu=0.5)
    container_resources = ResourceRequirements(requests=container_resource_requests)
    container = Container(name=container_name,
                          image=MEASURE_IMAGE,
                          command=command,
                          resources=container_resources)

    group = ContainerGroup(
        location=region,
        containers=[container],
        os_type=OperatingSystemTypes.linux,
        restart_policy=ContainerGroupRestartPolicy.never,
    )

    logger.info(f"Creating container group {group_name} in region {region} for URL {url}")
    result = client.container_groups.begin_create_or_update(
        AZURE_RESOURCE_GROUP,
        group_name,
        group
    ).result()  # Wait for creation to finish
    return group_name

def wait_for_container_completion(client, container_group_name, container_name="measure"):
    """
    Polls the container instance until it finishes executing (or a timeout is reached).
    Returns True if completed; False if timed out.
    """
    start_time = time.time()
    while time.time() - start_time < ACR_TIMEOUT:
        cg = client.container_groups.get(AZURE_RESOURCE_GROUP, container_group_name)
        container_state = cg.containers[0].instance_view.current_state.state.lower() if cg.containers[0].instance_view else ""
        logger.debug(f"Container {container_group_name} state: {container_state}")
        if container_state in ("terminated", "exited"):
            return True
        time.sleep(5)
    return False

def get_container_logs(client, container_group_name, container_name="measure"):
    """
    Retrieves the logs from the finished container.
    """
    logs = client.containers.list_logs(AZURE_RESOURCE_GROUP, container_group_name, container_name)
    return logs.content

def delete_container_group(client, container_group_name):
    """
    Deletes a container group to cleanup resources.
    """
    try:
        client.container_groups.begin_delete(AZURE_RESOURCE_GROUP, container_group_name)
        logger.info(f"Deleted container group {container_group_name}")
    except Exception as e:
        logger.error(f"Error deleting container group {container_group_name}: {e}")

def parse_response_time(log_content):
    """
    Parses log output and returns the response time (as float).
    This function assumes that the measurement container prints a single line
    that is just a float (milliseconds). Customize parsing if needed.
    """
    try:
        # Remove extra whitespace and possible additional logs
        for line in log_content.splitlines():
            try:
                value = float(line.strip())
                return value
            except ValueError:
                continue
    except Exception as e:
        logger.error(f"Error parsing log content: {e}")
    return None

# ---------------------------
# Main measurement loop
# ---------------------------

def run_measurement_cycle():
    """
    Runs a measurement cycle for each webpage defined.
    Spawns an ACI job for each target in a random region and records the metric.
    """
    webpages = read_webpages(WEBPAGES_CONFIG_PATH)
    if not webpages:
        logger.error("No webpages defined to monitor.")
        return

    # Set up the Azure Container Instance Management Client
    credential = DefaultAzureCredential()
    aci_client = ContainerInstanceManagementClient(credential, AZURE_SUBSCRIPTION_ID)

    for url in webpages:
        region = random.choice(AZURE_REGIONS)
        try:
            # Create the container group in a chosen region
            container_group_name = create_container_group(aci_client, region, url)
            # Wait for the container to run until finished.
            completed = wait_for_container_completion(aci_client, container_group_name)
            if not completed:
                logger.error(f"Timeout waiting for container group {container_group_name} to finish.")
                continue

            # Get container logs and parse response time
            log_content = get_container_logs(aci_client, container_group_name)
            response_time_ms = parse_response_time(log_content)
            if response_time_ms is not None:
                timestamp = datetime.datetime.now(datetime.UTC).isoformat()
                logger.info(f"Measured {response_time_ms}ms for {url} from {region}")
                # Record metric with additional label for timestamp if needed.
                webpage_response_time.labels(target=url, region=region, timestamp=timestamp).set(response_time_ms)
            else:
                logger.error(f"Could not parse response time for {url} in container group {container_group_name}")

        except Exception as exc:
            logger.error(f"Error running measurement for {url} from region {region}: {exc}")
        finally:
            # Cleanup: delete the container group
            try:
                delete_container_group(aci_client, container_group_name)
            except Exception as cleanup_error:
                logger.error(f"Cleanup error for container group {container_group_name}: {cleanup_error}")

# ---------------------------
# Main runner
# ---------------------------

def main():
    # Start Prometheus metrics server (exposes /metrics on port 8000)
    start_http_server(8000)
    logger.info("Prometheus metrics server started on port 8000")

    # In a production system you might use a scheduler (e.g., cronjob, Celery beat or APScheduler)
    # Here we run an infinite loop with a sleep interval.
    while True:
        logger.info("Starting new measurement cycle")
        run_measurement_cycle()
        logger.info(f"Measurement cycle completed. Sleeping for {MEASUREMENT_INTERVAL} seconds.")
        time.sleep(MEASUREMENT_INTERVAL)

if __name__ == '__main__':
    main()