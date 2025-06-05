import logging
from binascii import hexlify
from hashlib import sha256
from io import BytesIO

from micropython import const

from mqterm import VERSION


class Job:
    """A job to be executed by the terminal."""

    argc = 0

    def __init__(self, cmd, args=[], client_id="localhost", **kwargs):
        if not self.argc:
            self.argc = len(args)
        if len(args) != self.argc:
            raise ValueError(
                f"Wrong number of arguments for {cmd}; expected {self.argc}"
            )

        self.cmd = cmd
        self.args = args
        self.client_id = client_id
        self.seq = None

    def __str__(self):
        return f"Job for {self.client_id}: {self.cmd} {' '.join(self.args)}"

    def output(self):
        """Readable stream of output data."""
        # TODO: payload format indicator / output format handling
        return BytesIO()

    async def update(self, payload, seq):
        """Update the job with a new message."""
        pass

    @property
    def ready(self):
        """True if the job is ready to be processed."""
        return True

    @classmethod
    def from_cmd(cls, cmd_str, client_id=None):
        """Create a job from a command string, e.g. 'get_file file1.txt'."""
        cmd, *args = cmd_str.split()
        if cmd not in COMMANDS:
            raise ValueError(f"Unknown command: '{cmd}'")
        job_cls = COMMANDS[cmd]
        return job_cls(cmd, args, client_id)


class SequentialJob(Job):
    """A job that waits to be processed until all messages have arrived."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seq = 0

    async def update(self, _payload, seq):
        """Handle the next message in the sequence."""
        self.seq = self._check_seq(seq)

    @property
    def ready(self):
        """True if the job is ready to be processed."""
        return self.seq == -1

    # Validate that the message arrived in sequence for this job
    def _check_seq(self, seq):
        if seq == -1:  # end of sequence
            return seq
        if seq < -1:
            raise ValueError(f"Invalid message sequence: {seq}")

        next_seq = self.seq + 1

        if seq < next_seq:
            raise RuntimeError(f"Duplicate message: expected seq {next_seq}, got {seq}")
        if seq > next_seq:
            raise ValueError(f"Message missing: expected seq {next_seq}, got {seq}")

        return seq


class GetFileJob(Job):
    """A job to stream a file from the device to another client."""

    argc = 1

    def output(self):
        return BytesIO(open(self.args[0], "rb").read())


class WhoAmIJob(Job):
    """Returns the identity of the requesting client."""

    def output(self):
        return BytesIO(self.client_id.encode("utf-8"))


class PlatformInfoJob(Job):
    """Returns information about the device platform."""

    def output(self):
        import sys

        impl = sys.implementation.name
        py_version = ".".join(map(str, sys.implementation.version[:3]))
        return BytesIO(
            "MQTerm v{} on {} v{}".format(VERSION, impl, py_version).encode("utf-8")
        )


class ListDirJob(Job):
    """A job to list the contents of a directory."""

    argc = 1

    def output(self):
        import os

        return BytesIO("\n".join(sorted(os.listdir(self.args[0]))).encode("utf-8"))


class PutFileJob(SequentialJob):
    """A job to stream a file from another client to the device."""

    argc = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file = open(self.args[0], "wb")
        self.bytes_written = 0

    async def update(self, payload, seq):
        """Write the payload to the file and close if finished."""
        await super().update(payload, seq)
        if self.ready:
            self.file.close()
        else:
            self.bytes_written += self.file.write(payload)

    def output(self):
        """Return the number of bytes written to the file."""
        return BytesIO(str(self.bytes_written).encode("utf-8"))


class FirmwareUpdateJob(SequentialJob):
    """A job to update the firmware of the device over the air."""

    argc = 1

    BLOCK_SIZE = const(4096)  # Flash memory block size in bytes

    def __init__(self, *args, **kwargs):
        try:
            from esp32 import Partition
        except ImportError:
            raise ValueError("Firmware updates are not supported on this platform")

        super().__init__(*args, **kwargs)
        self.checksum = self.args[0]
        self.sha = sha256()
        self.buffer = bytearray(self.BLOCK_SIZE)
        self.buf_len = 0
        self.bytes_written = 0
        self.current_block = 0
        self.partition = Partition(Partition.RUNNING).get_next_update()
        self.logger = kwargs.get("logger", logging.getLogger("ota"))

    def __str__(self):
        # Use shortened checksum in string representation
        return f"Job for {self.client_id}: {self.cmd} {self.checksum[:8]}"

    async def update(self, payload, seq):
        """Write the payload to the firmware file and close if finished."""
        await super().update(payload, seq)
        if payload:
            self.sha.update(payload)
            payload_len = len(payload)

        if self.ready:
            self.logger.debug("Firmware data received")
            # If there is any data left in the buffer, write it to flash memory
            if self.buf_len > 0:
                self._write_block()

            # Finalize the firmware update
            self._validate_firmware()
            self.partition.set_boot()
        else:
            # If this message would overflow the buffer, we're ready to write a block
            if self.buf_len + payload_len >= self.BLOCK_SIZE:
                self._write_block(payload, payload_len)

            # Otherwise, just add the payload to the buffer
            else:
                self.buffer[self.buf_len : self.buf_len + payload_len] = payload
                self.buf_len += payload_len
            self.bytes_written += payload_len

    def _write_block(self, payload=None, payload_len=None):
        """Assemble a block and write to flash memory."""
        # See how much space is left in the block
        block_remaining = self.BLOCK_SIZE - self.buf_len

        # If there is space remaining in the block and we got passed a payload,
        # use as much of it as we can to fill the block. If no payload, fill up
        # the rest of the block with empty data instead.
        if block_remaining > 0:
            if payload:
                self.buffer[self.buf_len : self.BLOCK_SIZE] = payload[:block_remaining]
                payload_len -= block_remaining
                self.bytes_written += payload_len
            else:
                for i in range(self.buf_len, self.BLOCK_SIZE):
                    self.buffer[i] = 0xFF  # Erased flash memory is 0xFF
        self.buf_len = self.BLOCK_SIZE  # Buffer is now full

        # Write the current block to flash memory and reset buffer
        self.partition.writeblocks(self.current_block, self.buffer)
        self.current_block += 1
        self.buf_len = 0

        # If there is still data left from the payload, add it to the buffer
        # for the next block and reset the buffer length
        if payload_len and payload_len > 0:
            self.buffer[:payload_len] = payload[block_remaining:]
            self.buf_len = payload_len

    def _validate_firmware(self):
        """Validate the firmware file before finalizing the update."""
        hex_digest = hexlify(self.sha.digest()).decode()
        if not hex_digest == self.checksum:
            raise ValueError(
                f"Checksum mismatch: expected {self.checksum}, got {hex_digest}"
            )

    def output(self):
        """Return the number of bytes written to the firmware file."""
        self.logger.debug(
            f"Firmware update complete, total bytes written: {self.bytes_written}"
        )
        return BytesIO(str(self.bytes_written).encode("utf-8"))


# Map commands to associated job names
COMMANDS = {
    "whoami": WhoAmIJob,
    "uname": PlatformInfoJob,
    "cat": GetFileJob,
    "ls": ListDirJob,
    "cp": PutFileJob,
    "ota": FirmwareUpdateJob,
}
