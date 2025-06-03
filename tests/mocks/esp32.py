# ESP32 mocks for Unix


class Partition:
    @classmethod
    def RUNNING(cls):
        pass

    def __init__(self, _which):
        self.contents = bytearray()

    def get_next_update(self):
        return self

    def writeblocks(self, block, buf):
        self.contents[block * 4096 : (block + 1) * 4096] = buf

    def set_boot(self):
        pass
