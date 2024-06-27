class QubesDB:
    def read(self, key):
        return b'testvm'

    def write(self, key, value):
        pass

    def rm(self, key):
        pass

    def list(self, path):
        return ['test']

class Error(Exception):
    pass

class DisconnectedError(Error):
    pass
