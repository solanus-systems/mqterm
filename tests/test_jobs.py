"""Test the GetFileJob."""

import asyncio
import os
from unittest import TestCase

from mqterm.jobs import GetFileJob, Job, PlatformInfoJob, PutFileJob, WhoAmIJob


class TestJob(TestCase):
    def test_from_cmd(self):
        """Job should parse a command string into a Job object"""
        job = Job.from_cmd("cat file.txt")
        self.assertEqual(job.cmd, "cat")
        self.assertEqual(job.args, ["file.txt"])
        self.assertIsInstance(job, GetFileJob)
        with self.assertRaises(ValueError):
            Job.from_cmd("unknown")

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
