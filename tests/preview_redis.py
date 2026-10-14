"""Offline Redis transaction double for preview publication tests."""


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.reads = []

    def get(self, key):
        self.reads.append(("get", key))
        return self.values.get(key)

    def hmget(self, key, *fields):
        self.reads.append(("hmget", key))
        return [self.values.get(key, {}).get(field) for field in fields]

    def pipeline(self, transaction=True):
        assert transaction
        return Pipeline(self)


class Pipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []

    def set(self, key, value, ex):
        self.commands.append(("set", key, value, ex))

    def delete(self, key):
        self.commands.append(("delete", key))

    def hset(self, key, mapping):
        self.commands.append(("hset", key, mapping))

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))

    def execute(self):
        for command, key, *args in self.commands:
            if command == "set":
                self.client.values[key] = args[0]
                self.client.ttls[key] = args[1]
            elif command == "delete":
                self.client.values.pop(key, None)
            elif command == "hset":
                self.client.values[key] = args[0]
            else:
                self.client.ttls[key] = args[0]
        return [True] * len(self.commands)
