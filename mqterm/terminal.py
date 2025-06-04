import logging

from amqc.properties import CORRELATION_DATA, USER_PROPERTY

from mqterm.jobs import Job


def format_topic(*parts):
    """Create a slash-delimited MQTT topic from a list of strings."""
    return "/" + "/".join(part.strip("/") for part in parts if part)


def format_properties(client_id, seq):
    """Format MQTT properties for a message."""
    return {
        CORRELATION_DATA: client_id.encode("utf-8"),
        USER_PROPERTY: {"seq": str(seq)},
    }


def parse_client_id(properties):
    """Extract the client ID from MQTT properties."""
    client_id = properties.get(CORRELATION_DATA, None)
    if not client_id:
        raise ValueError("Missing client ID")
    return client_id.decode("utf-8")


def parse_seq(properties):
    """Extract the sequence number from MQTT User Properties."""
    user_properties = properties.get(USER_PROPERTY, {})
    seq = user_properties.get("seq", None)
    if not seq:
        raise ValueError("Missing sequence information")
    try:
        seq = int(seq)
    except TypeError:
        raise ValueError(f"Invalid sequence information: {seq}")
    return seq


class MqttTerminal:
    PKTLEN = 1400  # data bytes that reasonably fit into a TCP packet
    BUFLEN = PKTLEN * 2  # payload size for MQTT messages

    def __init__(
        self, mqtt_client, topic_prefix=None, logger=logging.getLogger("mqterm")
    ):
        self.mqtt_client = mqtt_client
        self.topic_prefix = topic_prefix
        self.in_topic = format_topic(self.topic_prefix, "tty", "in")
        self.out_topic = format_topic(self.topic_prefix, "tty", "out")
        self.err_topic = format_topic(self.topic_prefix, "tty", "err")
        self.out_buffer = bytearray(self.BUFLEN)
        self.out_view = memoryview(self.out_buffer)
        self.logger = logger
        self.jobs = {}

    async def connect(self):
        """Start processing messages in the input stream."""
        await self.mqtt_client.subscribe(self.in_topic, qos=1)

    async def disconnect(self):
        """Stop processing messages in the input stream."""
        await self.mqtt_client.unsubscribe(self.in_topic)

    async def handle_msg(self, topic, msg, properties={}):
        """Process a single MQTT message and apply to the appropriate job."""
        if not topic.startswith(self.in_topic):
            self.logger.debug(f"Terminal received message on {topic}; ignoring")
            return

        client_id = parse_client_id(properties)
        seq = parse_seq(properties)
        try:
            await self.update_job(client_id=client_id, seq=seq, payload=msg)
        except RuntimeError as e:  # logged & handled as warning
            self.logger.warning(e)
            await self.mqtt_client.publish(
                self.err_topic,
                str(e).encode("utf-8"),
                qos=1,
                properties=format_properties(client_id, seq),
            )
        except Exception as e:
            self.logger.exception(e)
            await self.mqtt_client.publish(
                self.err_topic,
                str(e).encode("utf-8"),
                qos=1,
                properties=format_properties(client_id, -1),
            )
            if client_id in self.jobs:  # remove job on fatal error
                del self.jobs[client_id]

    async def update_job(self, client_id, seq, payload):
        """Update or create a job, running it if ready."""
        # Fetch existing job or create a new one
        if client_id in self.jobs:
            job = self.jobs[client_id]
            await job.update(payload, seq)
            self.logger.debug(f"Updated {job}, seq: {seq}")
        else:
            cmd = payload.decode("utf-8")
            job = Job.from_cmd(cmd, client_id=client_id)
            self.jobs[client_id] = job
            self.logger.debug(f"Created {job}")

        # Run the job if it's ready and stream the results / signal completion
        if job.ready:
            await self.stream_job_output(job)
            await self.mqtt_client.publish(
                self.out_topic,
                b"",
                qos=1,
                properties=format_properties(client_id, -1),
            )
            del self.jobs[client_id]

    async def stream_job_output(self, job):
        """Stream the output of a job to the output topic."""
        in_buffer = job.output()
        seq = 0
        while True:
            bytes_read = in_buffer.readinto(self.out_buffer)
            if bytes_read > 0:
                await self.mqtt_client.publish(
                    self.out_topic,
                    self.out_view[:bytes_read],
                    qos=1,
                    properties=format_properties(job.client_id, seq),
                )
                seq += 1
            else:
                break
