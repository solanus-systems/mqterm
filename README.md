# amqc

[![ci](https://github.com/solanus-systems/amqc/actions/workflows/ci.yml/badge.svg)](https://github.com/solanus-systems/amqc/actions/workflows/ci.yml)

An async MQTTv5 client for micropython on ESP32 and unix.

Adapted from [micropython-mqtt](https://github.com/peterhinch/micropython-mqtt/tree/master).

## Installation

On a micropython device, install with `mip` from the REPL:

```python
>>> import mip
>>> mip.install("github:solanus-systems/amqc")
```

Or on a unix build of micropython via the CLI:

```bash
micropython -m mip install github:solanus-systems/amqc
```

## Usage

TODO

## Developing

You need python and a build of micropython with `asyncio` support. Follow the steps in the CI workflow to get a `micropython` binary and add it to your `PATH`.

Before making changes, install the development dependencies:

```bash
pip install -r dev-requirements.txt
```

After making changes, you can run the linter:

```bash
ruff check
```

Before running tests, install the test dependencies:

```bash
./bin/setup
```

Then, you can run the tests using the micropython version of `unittest`:

```bash
micropython -m unittest
```

## Releasing

To release a new version, first cross-compile to micropython bytecode. You need `mpy-cross` in your `PATH`:

```bash
./bin/compile
```

Then, update the versions in `manifest.py` and `package.json`. Commit your changes and make a pull request. After merging, create a new tag and push to GitHub:

```bash
git tag vX.Y.Z
git push --tags
```
