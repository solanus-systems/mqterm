# mqterm

[![ci](https://github.com/solanus-systems/mqterm/actions/workflows/ci.yml/badge.svg)](https://github.com/solanus-systems/mqterm/actions/workflows/ci.yml)

An MQTT-based terminal for remote management of micropython devices.

Inspired by [mqboard](https://github.com/tve/mqboard).

## Installation

On a micropython device, install with `mip` from the REPL:

```python
>>> import mip
>>> mip.install("github:solanus-systems/mqterm")
```

Or on a unix build of micropython via the CLI:

```bash
micropython -m mip install github:solanus-systems/mqterm
```

## Usage

TODO

## Developing

You need python and a build of micropython with `asyncio` and `os.dupterm` support. Follow the steps in the CI workflow to get a `micropython` binary and add it to your `PATH`.

Before making changes, install the development (CPython) dependencies:

```bash
pip install -r dev-requirements.txt
```

### Linting

This project uses [ruff](https://github.com/astral-sh/ruff) for linting. After making changes, you can run the linter:

```bash
ruff check
```

### Testing

Before running tests, install the test (micropython) dependencies:

```bash
./bin/setup
```

Note that you need to set up your `MICROPYPATH` environment variable so that the local copy of the package is loaded before any installed packages.

```bash
export MICROPYPATH="$(pwd)/tests/mocks:$(pwd):.frozen:~/.micropython/lib:/usr/lib/micropython"
```

#### Unit tests

You can run the unit tests using the micropython version of `unittest`:

```bash
micropython -m unittest
```

#### Integration tests

Integration tests use a running MQTT broker ([mosquitto](https://mosquitto.org/)), which you need to have installed (e.g. with `brew`).

There is a script that will set up the test environment, run the tests, and tear down the broker afterward:

```bash
./bin/test_e2e
```

Sometimes it's useful to debug an individual integration test. To do this, you need to run the broker yourself, then set up the environment and invoke the test directly:

```bash
mosquitto -v  # keep open to check the broker logs
```

Then in another terminal:

```bash
LOG_LEVEL=DEBUG MICROPYPATH="$(pwd)/tests/mocks:$(pwd):.frozen:~/.micropython/lib:/usr/lib/micropython" micropython ./tests/e2e/e2e_file_ops.py
```

## Releasing

To release a new version, update the version in `package.json`. Commit your changes and make a pull request. After merging, create a new tag and push to GitHub:

```bash
git tag vX.Y.Z
git push --tags
```
