from io import BytesIO

from mqterm import VERSION


class Job:
    """A job to be executed by the terminal."""

    argc = 0

    def __init__(self, cmd, args=[], client_id="localhost"):
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

        return BytesIO("\n".join(os.listdir(self.args[0])).encode("utf-8"))


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


# Map commands to associated job names
COMMANDS = {
    "whoami": WhoAmIJob,
    "uname": PlatformInfoJob,
    "cat": GetFileJob,
    "ls": ListDirJob,
    "cp": PutFileJob,
}
