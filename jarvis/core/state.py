"""Small synchronized shared state; voice buffers remain per connection."""
from collections.abc import MutableMapping
from threading import RLock

class SharedCache(MutableMapping):
    def __init__(self, values):
        self._values = dict(values)
        self._lock = RLock()
    def __getitem__(self, key):
        with self._lock: return self._values[key]
    def __setitem__(self, key, value):
        with self._lock: self._values[key] = value
    def __delitem__(self, key):
        with self._lock: del self._values[key]
    def __len__(self):
        with self._lock: return len(self._values)
    def __iter__(self):
        return iter(self.snapshot())
    def snapshot(self):
        with self._lock: return dict(self._values)
