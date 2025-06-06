def call(*args, **kwargs):
    return (tuple(args), dict(kwargs))


class Mock:
    """A mock callable object that stores its calls."""

    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self._calls = []

    def __call__(self, *args, **kwargs):
        """Call the mock and store the call details."""
        self._calls.append(call(*args[1:], **kwargs))  # Skip the first argument (self)
        if self.side_effect:
            raise self.side_effect
        return self.return_value

    def assert_called(self):
        """Assert that the mock was called at least once."""
        assert len(self._calls) > 0, "Expected mock to be called, but it was not."

    def assert_not_called(self):
        """Assert that the mock was not called."""
        assert len(self._calls) == 0, "Expected mock to not be called, but it was."

    def assert_called_with(self, *args, **kwargs):
        """Assert that the mock was last called with the given arguments."""
        # Fail if no calls were made
        self.assert_called()

        # Try to have a useful output for assertion failures
        expectation = call(*args, **kwargs)
        assert self._calls[-1] == expectation, "Expected call with {}, got {}".format(
            expectation, self._calls[-1]
        )

    def assert_has_calls(self, calls):
        """Assert that the mock has the expected calls with arguments."""
        assert calls, "Expected calls cannot be empty."

        # Fail if no calls were made
        self.assert_called()

        assert self._calls == calls, "Expected calls {}, got {}".format(
            calls, self._calls
        )


class AsyncMock(Mock):
    """An async version of Mock that can be awaited."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(self, *args, **kwargs)

    def assert_awaited(self):
        """Assert that the async mock was awaited at least once."""
        return super().assert_called()

    def assert_not_awaited(self):
        """Assert that the async mock was not awaited."""
        return super().assert_not_called()

    def assert_awaited_with(self, *args, **kwargs):
        """Assert that the async mock was last awaited with the given arguments."""
        return super().assert_called_with(*args, **kwargs)

    def assert_has_awaits(self, awaits):
        """Assert that the async mock has the expected awaits with arguments."""
        return super().assert_has_calls(awaits)
