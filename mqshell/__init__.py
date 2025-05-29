"""
MQShell: A simple shell for interacting with an MQTT Terminal
"""

from binascii import unhexlify
from cmd import Cmd
from getpass import getuser
from io import IOBase
from shlex import join, shlex
from socket import gethostname
from time import sleep

import paho.mqtt.client as mqtt
from paho.mqtt.enums import (CallbackAPIVersion, MQTTErrorCode,
                             MQTTProtocolVersion)
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode


class MQTTShell(Cmd):
    intro = "Welcome to MQTT Shell. Type help or ? to list commands."
    prompt = "> "
    queue: list[mqtt.MQTTMessage] = []
    buf_len = 1400

    def __init__(self):
        super().__init__()
        user = getuser()
        host = gethostname()
        self.client_id = f"{user}@{host}"
        self.client = mqtt.Client(
            client_id=self.client_id,
            callback_api_version=CallbackAPIVersion.VERSION2,
            protocol=MQTTProtocolVersion.MQTTv5,
        )
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.subscribe_mids = {}

    def _on_connect(self, _client, _userdata, _flags, rc: ReasonCode, _properties):
        if rc.is_failure:
            print(f"Failed to connect to MQTT broker: {rc}")
            return
        print("Connected to MQTT broker")

    def _on_disconnect(self, _client, _userdata, _flags, rc: ReasonCode, _properties):
        if rc.is_failure:
            print(f"Disconnected with error: {rc}")
            return
        print("Disconnected from MQTT broker")

    def _on_subscribe(
        self, _client, _userdata, mid, rc_list: list[ReasonCode], _properties
    ):
        if mid not in self.subscribe_mids:
            print(f"Received unexpected SUBACK with message id: {mid}")
            return
        if any(rc.is_failure for rc in rc_list):
            print(f"Failed to subscribe to topic: {rc_list}")
        else:
            print(f"Subscribed to topic: {self.subscribe_mids[mid]}")
        del self.subscribe_mids[mid]

    def _on_message(self, _client, _userdata, message: mqtt.MQTTMessage):
        # Ignore messages not meant for us (using correlation data)
        client_id, seq = self._parse_props(message)
        if client_id != self.client_id:
            return

        # Handle messages based on topic
        if message.topic == self.out_topic:
            print(message.payload.decode("utf-8"))
        elif message.topic == self.err_topic:
            print(f"ERROR: {message.payload.decode('utf-8')}")

        # Signal completion if seq is -1
        if seq == -1:
            self.ready = True

    def _parse(self, cmd):
        # Parse a command into a list of arguments, shell-style
        lexer = shlex(cmd)
        lexer.whitespace_split = True
        return list(lexer)

    def _make_props(self, seq=-1):
        # Create a properties object with correlation data and sequence number
        props = Properties(PacketTypes.PUBLISH)
        props.CorrelationData = self.client_id.encode("utf-8")
        props.UserProperty = ("seq", str(seq))
        return props

    def _parse_props(self, message: mqtt.MQTTMessage):
        # Parse the client ID and sequence number from the message properties
        # Fault-tolerant; returns None if properties are missing or invalid
        props = message.properties.json() if message.properties else {}
        correlation_data = props.get("CorrelationData", b"")
        client_id = unhexlify(correlation_data).decode("utf-8")
        user_properties = props.get("UserProperty", [("seq", None)])
        seq_data = user_properties[0]
        try:
            seq = int(seq_data[1])
        except Exception:
            seq = None
        return client_id, seq

    def _blocking_publish(self, payload, properties=None):
        # Publish a message and wait for it to be acknowledged
        properties = properties or self._make_props()
        info = self.client.publish(self.in_topic, payload, properties=properties)
        info.wait_for_publish()

    def _blocking_subscribe(self, topic, qos=1):
        # Subscribe to a topic and wait for the SUBACK
        rc, mid = self.client.subscribe(topic, qos)
        if rc != MQTTErrorCode.MQTT_ERR_SUCCESS:
            print(f"Failed to subscribe to topic: {topic}")
            return
        self.subscribe_mids[mid] = topic
        while mid in self.subscribe_mids:
            sleep(0.1)

    def _run_cmd(self, cmd):
        # Run a command and block until completed
        self.ready = False
        self._blocking_publish(cmd)
        self._wait_for_completed()

    def _wait_for_completed(self):
        # Block until the command is completed
        while not self.ready:
            sleep(0.1)

    def _send_stream(self, stream: IOBase):
        # Send a stream of bytes in chunks of buf_len size
        seq = 0
        while not self.ready:
            chunk = stream.read(self.buf_len)
            if not chunk:
                seq = -1
            self._blocking_publish(chunk, self._make_props(seq))
            if seq == -1:
                break

    def do_quit(self, _arg):
        """Exit the shell."""
        if self.client.is_connected:
            self.client.disconnect()
        self.client.loop_stop()
        return True

    def do_connect(self, arg):
        """Connect to a terminal via an MQTT broker.
        connect device_topic [url] [port] [keepalive]
        connect /test/device test.mosquitto.org 1883 60"""
        if self.client.is_connected():
            self.do_disconnect(None)

        # block until connected to broker
        args = self._parse(arg)
        while len(args) < 4:
            args.append("")
        addr = args[0] or "/test/device"
        host = args[1] or "localhost"
        port = int(args[2]) if args[2] else 1883
        keepalive = int(args[3]) if args[3] else 60
        self.client.connect(host=host, port=port, keepalive=keepalive, clean_start=True)

        # start the loop to receive messages
        self.client.loop_start()

        # set and subscribe to in/out/err topics, block until success
        self.in_topic = f"{addr}/tty/in"
        self.out_topic = f"{addr}/tty/out"
        self.err_topic = f"{addr}/tty/err"
        self._blocking_subscribe(self.out_topic)
        self._blocking_subscribe(self.err_topic)

        # ensure device responds to `uname`
        self._run_cmd("uname")

    def do_disconnect(self, _arg):
        """Disconnect from the terminal."""
        self.client.disconnect()

    def do_whoami(self, _arg):
        """Print the current client ID as received by the remote host."""
        self._run_cmd("whoami")

    def do_uname(self, _arg):
        """Print the remote host platform information."""
        self._run_cmd("uname")

    def do_cat(self, arg):
        """Read a file from the remote filesystem.
        cat lib/file.py"""
        args = self._parse(arg)
        if len(args) != 1:
            print("Usage: cat <path>")
            return
        path = args[0]
        self._run_cmd(join(["cat", path]))

    def do_ls(self, arg):
        """List the contents of the remote filesystem."""
        args = self._parse(arg)
        if len(args) != 1:
            print("Usage: ls <path>")
            return
        path = args[0]
        self._run_cmd(join(["ls", path]))

    def do_cp(self, arg):
        """Copy a file to the remote filesystem.
        cp src/file.py dst/file.py"""
        args = self._parse(arg)
        if len(args) != 2:
            print("Usage: cp <source> <destination>")
            return
        src, dst = args
        self._blocking_publish(join(["cp", src, dst]), self._make_props(seq=0))
        if not self.ready:
            with open(src, "rb") as file:
                self._send_stream(file)
        self._wait_for_completed()


if __name__ == "__main__":
    MQTTShell().cmdloop()
