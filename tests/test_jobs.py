"""Test the GetFileJob."""

import asyncio
import logging
import os
from binascii import hexlify
from hashlib import sha256
from unittest import TestCase

from mqterm.jobs import (
    FirmwareUpdateJob,
    GetFileJob,
    Job,
    PlatformInfoJob,
    PutFileJob,
    RebootJob,
    RunPyJob,
    WhoAmIJob,
)


class TestJob(TestCase):
    def test_from_cmd(self):
        """Job should parse a command string into a Job object"""
        job = Job.from_cmd("cat file.txt")
        self.assertEqual(job.cmd, "cat")
        self.assertEqual(job.args, ["file.txt"])
        self.assertIsInstance(job, GetFileJob)
        with self.assertRaises(ValueError):
            Job.from_cmd("unknown")

    def test_from_cmd_eval(self):
        """Job should handle eval command"""
        job = Job.from_cmd("eval '1 + 2'")
        self.assertEqual(job.cmd, "eval")
        self.assertEqual(job.args, ["1 + 2"])
        self.assertIsInstance(job, RunPyJob)

    def test_from_cmd_no_args(self):
        """Job should handle commands with no arguments"""
        job = Job.from_cmd("uname")
        self.assertEqual(job.cmd, "uname")
        self.assertEqual(job.args, [])
        self.assertIsInstance(job, PlatformInfoJob)

    def test_str(self):
        """Job should have a string representation"""
        job = Job("cat", args=["file.txt"])
        self.assertEqual(str(job), "Job for localhost: cat file.txt")


class TestGetFileJob(TestCase):
    def setUp(self):
        # Mock the file reading for the test
        self.file_content = "abc"
        with open("file.txt", "w") as f:
            f.write(self.file_content)

    def tearDown(self):
        # Clean up the file after the test
        try:
            os.remove("file.txt")
        except OSError:
            pass

    def test_init(self):
        with self.assertRaises(ValueError, msg="GetFileJob requires a filename"):
            GetFileJob("cat")

    def test_read_file(self):
        job = GetFileJob("cat", ["file.txt"])
        output = job.output().read().decode("utf-8")
        self.assertEqual(output, "abc", msg="File content should match expected output")


class TestWhoAmIJob(TestCase):
    def test_run(self):
        job = WhoAmIJob("whoami", client_id="user@client")
        output = job.output().read().decode("utf-8")
        self.assertEqual(
            output, "user@client", msg="WhoAmIJob should return the client ID"
        )


class TestPlatformInfoJob(TestCase):
    def test_run(self):
        job = PlatformInfoJob("uname")
        output = job.output().read().decode("utf-8")
        self.assertIn(
            "MQTerm v", output, msg="platform info should contain mqterm version"
        )
        self.assertIn(
            "micropython v",
            output,
            msg="platform info should contain micropython version",
        )


class TestListDirJob(TestCase):
    def setUp(self):
        # Create a temporary directory with some files for testing
        self.test_dir = "test_dir"
        os.mkdir(self.test_dir)
        with open(f"{self.test_dir}/file1.txt", "w") as f:
            f.write("content1")
        with open(f"{self.test_dir}/file2.txt", "w") as f:
            f.write("content2")

    def tearDown(self):
        # Clean up the test directory after the test
        for file in os.listdir(self.test_dir):
            os.remove(f"{self.test_dir}/{file}")
        os.rmdir(self.test_dir)

    def test_run(self):
        job = Job.from_cmd(f"ls {self.test_dir}")
        output = job.output().read().decode("utf-8").strip()
        expected_files = "file1.txt\nfile2.txt"
        self.assertEqual(output, expected_files)


class TestPutFileJob(TestCase):
    def setUp(self):
        self.test_file = "test_file.txt"
        self.test_contents = b"test content"

    def tearDown(self):
        # Clean up the test file after the test
        try:
            os.remove(self.test_file)
        except OSError:
            pass

    def test_run(self):
        """Should write to file and return bytes written"""
        job = PutFileJob(f"put {self.test_file}", [self.test_file])
        asyncio.run(job.update(b"test ", seq=1))
        asyncio.run(job.update(b"content", seq=2))
        asyncio.run(job.update(b"", seq=-1))  # Signal end of file transfer
        assert job.ready, "Job should be ready after final update"
        output = job.output().read().decode("utf-8")
        self.assertEqual(int(output), len(self.test_contents))
        with open(self.test_file, "rb") as f:
            self.assertEqual(f.read(), self.test_contents)


class TestFirmwareUpdateJob(TestCase):
    def test_update_sha(self):
        """Should update the SHA256 hash with each update"""
        job = FirmwareUpdateJob("ota", ["firmware.bin"])
        asyncio.run(job.update(b"\xde\xad\xbe\xef", seq=1))
        expected_sha = sha256(b"\xde\xad\xbe\xef").digest()
        self.assertEqual(job.sha.digest(), expected_sha)

    def test_write_block(self):
        """Should write a block to partition when buffer is full"""
        job = FirmwareUpdateJob("ota", ["firmware.bin"])

        # Buffer is partially full; next update would overflow it
        initial_data = b"\xde\xad\xbe\xef"
        job.buffer[0 : len(initial_data)] = initial_data
        job.buf_len = len(initial_data)
        payload = bytearray(b"\xcc" * FirmwareUpdateJob.BLOCK_SIZE)
        asyncio.run(job.update(payload, seq=1))

        # After update, we've written exactly one full block
        self.assertEqual(job.current_block, 1)
        self.assertEqual(len(job.partition.contents), FirmwareUpdateJob.BLOCK_SIZE)

    def test_wait_partial_block(self):
        """Should not write a block until buffer is full"""
        job = FirmwareUpdateJob("ota", ["firmware.bin"])

        # Buffer is partially full but next update would not overflow it
        initial_data = b"\xde\xad\xbe\xef"
        job.buffer[0 : len(initial_data)] = initial_data
        job.buf_len = len(initial_data)
        payload = bytearray(b"\xcc" * (FirmwareUpdateJob.BLOCK_SIZE // 2))
        asyncio.run(job.update(payload, seq=1))

        # After update, nothing written yet
        self.assertEqual(job.current_block, 0)
        self.assertEqual(len(job.partition.contents), 0)

    def test_last_block_fill(self):
        """Should fill space in last block with empty data on final update"""
        initial_data = b"\xde\xad\xbe\xef"
        checksum = hexlify(sha256(initial_data).digest()).decode("utf-8")
        job = FirmwareUpdateJob("ota", [checksum])

        # Send and complete the update
        asyncio.run(job.update(initial_data, seq=1))
        asyncio.run(job.update(b"", seq=-1))

        # After final update, we should have written one last block of full size
        self.assertEqual(job.current_block, 1)
        self.assertEqual(len(job.partition.contents), FirmwareUpdateJob.BLOCK_SIZE)
        self.assertEqual(
            job.partition.contents[: len(initial_data)],
            initial_data,
            "Last block should contain the initial data",
        )
        self.assertEqual(
            job.partition.contents[len(initial_data) :],
            bytearray(
                0xFF for _ in range(FirmwareUpdateJob.BLOCK_SIZE - len(initial_data))
            ),
            "Remaining bytes in last block should be filled with empty data",
        )

    def test_output(self):
        """Should return the total bytes written as output"""
        initial_data = b"\xde\xad\xbe\xef"
        checksum = hexlify(sha256(initial_data).digest()).decode("utf-8")
        job = FirmwareUpdateJob("ota", [checksum])

        # Send and complete the update
        asyncio.run(job.update(initial_data, seq=1))
        asyncio.run(job.update(b"", seq=-1))

        # Output should be the total bytes written
        output = job.output().read().decode("utf-8").strip()
        self.assertEqual(output, "4")


class TestRebootJob(TestCase):
    def setUp(self):
        # Turn off logging during tests
        self.logger = logging.getLogger()
        self.handlers = self.logger.handlers[:]
        self.logger.handlers = []

    def tearDown(self):
        self.logger.handlers = self.handlers

    def test_run_hard(self):
        """Reboot job should signal and perform a hard reboot"""
        job = RebootJob("reboot", ["hard"])
        with self.assertRaises(OSError):  # Can't do on unix
            output = job.output().read().decode("utf-8").strip()
            self.assertEqual(output, "Performing hard reboot")

    def test_run_soft(self):
        """Reboot job should signal a soft reboot"""
        job = RebootJob("reboot", ["soft"])
        output = job.output().read().decode("utf-8").strip()
        self.assertEqual(output, "Performing soft reboot")


class TestRunPyJob(TestCase):
    def test_eval(self):
        """RunPyJob should evaluate a Python expression and return result"""
        job = RunPyJob("eval", ["1 + 2"])
        output = job.output().read().decode("utf-8").strip()
        self.assertEqual(output, "3")

    def test_globals(self):
        """RunPyJob should use provided globals for evaluation"""
        job = RunPyJob("eval", ["x + y"], globals={"x": 1, "y": 2})
        output = job.output().read().decode("utf-8").strip()
        self.assertEqual(output, "3")

    def test_exec(self):
        """RunPyJob should execute a Python script with side effects"""
        cmd = """
            with open("output.txt", "w") as f:
                f.write("Hello, World!")
        """.strip()
        job = RunPyJob("exec", [cmd])
        job_output = job.output().read().decode("utf-8").strip()
        file_output = open("output.txt").read().strip()
        self.assertEqual(job_output, "")  # No output expected
        self.assertEqual(file_output, "Hello, World!")
        os.remove("output.txt")

    # NOTE: on unix micropython you need to compile with MICROPY_PY_OS_DUPTERM
    # to capture output. If this fails, see:
    # https://forum.micropython.org/viewtopic.php?t=7055
    def test_exec_output(self):
        """RunPyJob should capture output from executed script"""
        cmd = 'import sys; sys.stdout.write("Hello, World!")'
        job = RunPyJob("exec", [cmd])
        output = job.output().read().decode("utf-8").strip()
        self.assertEqual(output, "Hello, World!")
