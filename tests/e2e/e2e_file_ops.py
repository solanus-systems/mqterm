#!/usr/bin/env micropython

"""End-to-end tests for copying files to and from the device."""

import asyncio
import logging
import os
import sys
from io import BytesIO

from amqc.client import MQTTClient, config

from mqterm.terminal import MqttTerminal

# Set up logging; pass LOG_LEVEL=DEBUG if needed for local testing
logger = logging.getLogger()
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper()))
formatter = logging.Formatter(
    "%(asctime)s.%(msecs)d - %(levelname)s - %(name)s - %(message)s"
)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger.handlers = []
logger.addHandler(handler)
device_logger = logging.getLogger("device")
control_logger = logging.getLogger("control")


# MQTT Client config
config["server"] = "localhost"
config["queue_len"] = 1  # use event queue
device_config = config.copy()
control_config = config.copy()
device_config["client_id"] = "device"
control_config["client_id"] = "server"

# Set up MQTT clients
device_client = MQTTClient(device_config, logger=device_logger)
control_client = MQTTClient(control_config, logger=control_logger)

# Set up the terminal
term = MqttTerminal(device_client, topic_prefix="/test")


def create_props(seq: int, client_id: str) -> dict:
    """Create MQTTv5 properties with a seq number and client ID."""
    return {
        MqttTerminal.PROP_CORR: client_id.encode("utf-8"),
        MqttTerminal.PROP_USER: {"seq": str(seq)},
    }


async def send_file(buffer: BytesIO):
    """Send a file to the terminal."""
    # Send the first message that will create the job
    seq = 0
    props = create_props(seq, "tty0")
    await control_client.publish(
        "/test/tty/in", "cp test.txt".encode("utf-8"), properties=props
    )

    # Send the file in 4-byte chunks; close when done
    fp = BytesIO(b"Hello world!")
    while True:
        await asyncio.sleep(0.5)
        chunk = fp.read(4)
        if chunk:
            seq += 1
        else:
            seq = -1
        props = create_props(seq, "tty0")
        logger.debug(f"Sending chunk {seq} of size {len(chunk)}: {chunk!r}")
        await control_client.publish("/test/tty/in", chunk, properties=props)
        if seq == -1:
            break

    # Wait until the received buffer gets populated with the response
    await asyncio.sleep(1)

    # Return the bytes received and empty the output buffer
    buffer.seek(0)
    output = buffer.read()
    logger.debug(f"Buffer contents: {output!r}")
    buffer.flush()
    buffer.seek(0)
    return output


async def get_file(buffer: BytesIO):
    """Send a file to the terminal and read it back."""
    # Send the request for the file
    seq = 0
    props = create_props(seq, "tty0")
    await control_client.publish(
        "/test/tty/in", "cat test.txt".encode(), properties=props
    )

    # Wait until the received buffer gets populated with the response
    await asyncio.sleep(1)

    # Return the bytes received and empty the output buffer
    buffer.seek(0)
    output = buffer.read()
    buffer.flush()
    return output


# Handler for device messages that passes them to the terminal
async def device_handler():
    async for topic, payload, _retained, properties in device_client.queue:
        device_logger.debug(f"Device received {len(payload)} bytes on topic '{topic}'")
        await term.handle_msg(topic, payload, properties)


# Handler for control messages that logs and stores them
async def control_handler(buffer):
    async for topic, payload, _retained, properties in control_client.queue:
        if topic == "/test/tty/err":
            logger.error(f"Control received error: {payload.decode('utf-8')}")
        else:
            buffer.write(payload)  # Don't decode yet
            logger.debug(f"Control received {len(payload)} bytes on topic '{topic}'")


# Main test function
async def main():
    # Connect all clients and the terminal
    await control_client.connect(True)
    await control_client.subscribe("/test/tty/out")
    await control_client.subscribe("/test/tty/err")
    await device_client.connect(True)
    await term.connect()

    # Run handlers in the background and test task in the foreground
    buffer = BytesIO()  # buffer for received bytes
    asyncio.create_task(control_handler(buffer))
    asyncio.create_task(device_handler())

    bytes_sent = await send_file(buffer)
    logger.debug(f"Sent {bytes_sent.decode()} bytes to the device")
    bytes_received = await get_file(buffer)
    logger.debug(f"Received {len(bytes_received)} bytes from the device")

    # Disconnect and clean up
    await term.disconnect()
    await device_client.disconnect()
    await control_client.disconnect()

    # Read out the received file
    received_str = bytes_received.decode("utf-8")
    assert (
        received_str == "Hello world!"
    ), f"Expected 'Hello world!', got '{received_str}'"


if __name__ == "__main__":
    asyncio.run(main())
    print("\033[1m\tOK\033[0m")
