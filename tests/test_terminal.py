import asyncio
from io import BytesIO
from unittest import TestCase, skip

from mqterm.jobs import Job, SequentialJob
from mqterm.terminal import MqttTerminal, format_properties
from tests.utils import AsyncMock, Mock, call


class ErroringJob(Job):
    """A job that raises an error on update."""

    def output(self):
        raise ValueError("test error")


class MockSequentialJob(SequentialJob):
    """A test job that accumulates messages and reads them back."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contents = ""

    async def update(self, payload, seq):
        await super().update(payload, seq)
        self.contents += payload.decode("utf-8")

    def output(self):
        return BytesIO(self.contents.encode("utf-8"))


class TestMqttTerminal(TestCase):
    def setUp(self):
        self.in_topic = "/tty/in"
        self.mqtt_client = Mock()
        self.mqtt_client.publish = Mock()
        self.term = MqttTerminal(self.mqtt_client)

    # test helper for sending a message to the terminal
    def send_msg(self, payload, client_id="localhost", seq=-1):
        asyncio.run(
            self.term.handle_msg(
                self.in_topic,
                payload.encode("utf-8"),
                format_properties(client_id, seq),
            ),
        )

    def test_handle_msg_no_client_id(self):
        """MqttTerminal should raise on message with no client ID"""
        payload = "get_file file.txt"
        props = format_properties("", "invalid_seq")
        with self.assertRaises(ValueError):
            asyncio.run(
                self.term.handle_msg(self.in_topic, payload.encode("utf-8"), props)
            )

    def test_handle_msg_bad_seq(self):
        """MqttTerminal should raise on message with invalid sequence"""
        payload = "get_file file.txt"
        props = format_properties("localhost", "invalid_seq")
        with self.assertRaises(ValueError):
            asyncio.run(
                self.term.handle_msg(self.in_topic, payload.encode("utf-8"), props)
            )

    def test_handle_msg(self):
        """MqttTerminal should parse MQTT messages to update jobs"""
        self.term.update_job = AsyncMock()
        self.send_msg("get_file file.txt")
        self.term.update_job.assert_awaited_with(
            client_id="localhost", seq=-1, payload="get_file file.txt".encode("utf-8")
        )

    def test_update_job_existing(self):
        """MqttTerminal should update an existing job"""
        job = MockSequentialJob("x", ["file.txt"])
        self.term.jobs["localhost"] = job
        self.send_msg("abc", seq=1)
        self.assertEqual(self.term.jobs["localhost"].seq, 1)

    @skip("FIXME")
    def test_update_job_ready(self):
        """MqttTerminal should run a job when it's ready"""
        job = MockSequentialJob("x", ["file.txt"])
        self.term.jobs["localhost"] = job
        job.contents = "abc"  # existing contents
        self.send_msg("a", seq=1)  # last message
        self.send_msg("", seq=-1)
        self.mqtt_client.publish.assert_has_awaits(
            [
                call(
                    self.term.out_topic,
                    b"abc",
                    qos=1,
                    properties={
                        MqttTerminal.PROP_CORR: "localhost".encode("utf-8"),
                        MqttTerminal.PROP_USER: {"seq": "0"},
                    },
                ),
                call(
                    self.term.out_topic,
                    b"",
                    qos=1,
                    properties={
                        MqttTerminal.PROP_CORR: "localhost".encode("utf-8"),
                        MqttTerminal.PROP_USER: {"seq": "-1"},
                    },
                ),
            ]
        )
        self.assertEqual(
            len(self.term.jobs), 0, "Job should be removed after completion"
        )

    @skip("FIXME")
    def test_job_publish_err(self):
        """MqttTerminal should publish errors to the error topic"""
        job = ErroringJob("cat", ["file.txt"])
        self.term.jobs["localhost"] = job
        self.send_msg(" ")
        self.mqtt_client.publish.assert_awaited_with(
            self.term.err_topic,
            b"test error",
            qos=1,
            properties={
                MqttTerminal.PROP_CORR: "localhost".encode("utf-8"),
                MqttTerminal.PROP_USER: {"seq": "-1"},
            },
        )
