class QubesDB:
    def read(self, key):
        return b'testvm'

    def write(self, key, value):
        pass

    def rm(self, key):
        pass

    def list(self, path):
        return ['test']

    def watch(self, path):
        pass

    def read_watch(self):
        return "test"

    def watch_fd(self):
        return 3
    
    def close(self):
        pass

class Error(Exception):
    pass

class DisconnectedError(Error):
    pass
