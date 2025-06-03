import logging

from amqc.properties import CORRELATION_DATA, USER_PROPERTY

from mqterm.jobs import Job


class MqttTerminal:
    PKTLEN = 1400  # data bytes that reasonably fit into a TCP packet
    BUFLEN = PKTLEN * 2  # payload size for MQTT messages

    def __init__(
        self, mqtt_client, topic_prefix=None, logger=logging.getLogger("mqterm")
    ):
        self.mqtt_client = mqtt_client
        self.topic_prefix = topic_prefix
        self.in_topic = self._format_topic(self.topic_prefix, "tty", "in")
        self.out_topic = self._format_topic(self.topic_prefix, "tty", "out")
        self.err_topic = self._format_topic(self.topic_prefix, "tty", "err")
        self.out_buffer = bytearray(self.BUFLEN)
        self.out_view = memoryview(self.out_buffer)
        self.logger = logger
        self.jobs = {}

    @staticmethod
    def _format_topic(*parts):
        """Create a slash-delimited MQTT topic from a list of strings."""
        return "/" + "/".join(part.strip("/") for part in parts if part)

    async def connect(self):
        """Start processing messages in the input stream."""
        await self.mqtt_client.subscribe(self.in_topic, qos=1)

    async def disconnect(self):
        """Stop processing messages in the input stream."""
        await self.mqtt_client.unsubscribe(self.in_topic)

    async def handle_msg(self, _topic, msg, properties={}):
        """Process a single MQTT message and apply to the appropriate job."""
        client_id = self._get_client_id(properties)
        seq = self._get_seq(properties)
        try:
            await self.update_job(client_id=client_id, seq=seq, payload=msg)
        except RuntimeError as e:  # logged & handled as warning
            self.logger.warning(e)
            await self.mqtt_client.publish(
                self.err_topic,
                str(e).encode("utf-8"),
                qos=1,
                properties={
                    CORRELATION_DATA: client_id.encode("utf-8"),
                    USER_PROPERTY: {"seq": str(seq)},
                },
            )
        except Exception as e:
            self.logger.exception(e)
            await self.mqtt_client.publish(
                self.err_topic,
                str(e).encode("utf-8"),
                qos=1,
                properties={
                    CORRELATION_DATA: client_id.encode("utf-8"),
                    USER_PROPERTY: {"seq": "-1"},
                },
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
                properties={
                    CORRELATION_DATA: client_id.encode("utf-8"),
                    USER_PROPERTY: {"seq": "-1"},
                },
            )
            del self.jobs[client_id]

    async def stream_job_output(self, job):
        """Stream the output of a job to the output topic."""
        in_buffer = job.output()
        seq = 0
        while True:
            bytes_read = in_buffer.readinto(self.out_buffer)
            if bytes_read > 0:
                self.logger.debug(f"Streaming {bytes_read} bytes")
                await self.mqtt_client.publish(
                    self.out_topic,
                    self.out_view[:bytes_read],
                    qos=1,
                    properties={
                        CORRELATION_DATA: job.client_id.encode("utf-8"),
                        USER_PROPERTY: {"seq": str(seq)},
                    },
                )
                seq += 1
            else:
                break

    # Client ID: MQTT Correlation Data
    # Always bytes; we format it as UTF-8
    def _get_client_id(self, properties):
        client_id = properties.get(CORRELATION_DATA, None)
        if not client_id:
            raise ValueError("Missing client ID")
        return client_id.decode("utf-8")

    # Sequence: MQTT User Properties
    # List of tuples; we store sequence info as a string in the first one
    def _get_seq(self, properties):
        user_properties = properties.get(USER_PROPERTY, {})
        seq = user_properties.get("seq", None)
        if not seq:
            raise ValueError("Missing sequence information")
        try:
            seq = int(seq)
        except TypeError:
            raise ValueError(f"Invalid sequence information: {seq}")
        return seq
