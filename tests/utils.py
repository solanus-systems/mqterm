# from unittest import TestCase


def call(*args, **kwargs):
    return (tuple(args), dict(kwargs))


class Mock:
    """A mock callable object that stores its calls."""

    def __init__(self):
        self._calls = []

    def __call__(self, *args, **kwargs):
        self._calls.append(call(*args, **kwargs))

    def assert_called_with(self, *args, **kwargs):
        # First call should be self, so we prepend it
        expected_args = [self] + list(args)
        expectation = call(*expected_args, **kwargs)

        # Try to have a useful output for assertion failures
        assert self._calls[-1] == expectation, "Expected call with {}, got {}".format(
            expectation, self._calls[-1]
        )


class AsyncMock(Mock):
    """An async version of Mock that can be awaited."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(self, *args, **kwargs)

    def assert_awaited_with(self, *args, **kwargs):
        return super().assert_called_with(*args, **kwargs)

    def assert_has_awaits(self, awaits):
        assert self._calls == awaits
