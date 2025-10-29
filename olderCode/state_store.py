import os
import json
import threading
import pandas as pd
from typing import Dict, Any


class StateStore:
    """
    Minimal JSON state store with atomic write via temp file replace.
    """
    def __init__(self, directory: str, filename: str = 'minimal_live_ibkr_trader_state.json') -> None:
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)
        self.path = os.path.join(self.directory, filename)
        self._lock = threading.Lock()

    def save(self, state: Dict[str, Any]) -> None:
        try:
            payload = dict(state or {})
            if 'saved_at' not in payload:
                payload['saved_at'] = str(pd.Timestamp.utcnow())
            tmp = self.path + '.tmp'
            with self._lock:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, default=str)
                os.replace(tmp, self.path)
        except Exception:
            # Do not raise from save
            pass

    def load(self) -> Dict[str, Any]:
        try:
            if not os.path.exists(self.path):
                return {}
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            return {}
