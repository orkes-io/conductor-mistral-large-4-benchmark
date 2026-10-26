"""Minimal Conductor REST client used by the scripts and workers.

Reads CONDUCTOR_SERVER_URL, CONDUCTOR_AUTH_KEY and CONDUCTOR_AUTH_SECRET from the environment, or from the
env file named by CONDUCTOR_ENV_FILE. For a local OSS server set only CONDUCTOR_SERVER_URL."""
import os
import time
from pathlib import Path

import requests


def _load_env_file(path):
    env = {}
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.replace("export ", "", 1).split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class Conductor:
    def __init__(self, server_url=None, key=None, secret=None, env_file=None):
        env = {}
        if not server_url:
            env_file = env_file or os.environ.get("CONDUCTOR_ENV_FILE")
            env = _load_env_file(env_file) if env_file else {}
        url = server_url or os.environ.get("CONDUCTOR_SERVER_URL") or env.get("CONDUCTOR_SERVER_URL")
        if not url:
            raise SystemExit("Set CONDUCTOR_SERVER_URL (plus CONDUCTOR_AUTH_KEY / CONDUCTOR_AUTH_SECRET for Orkes), "
                             "or point CONDUCTOR_ENV_FILE at a file that sets them.")
        url = url.rstrip("/")
        self.api = url if url.endswith("/api") else url + "/api"
        self.ui = self.api[: -len("/api")]
        self.key = key if server_url else (key or os.environ.get("CONDUCTOR_AUTH_KEY") or env.get("CONDUCTOR_AUTH_KEY"))
        self.secret = secret if server_url else (
            secret or os.environ.get("CONDUCTOR_AUTH_SECRET") or env.get("CONDUCTOR_AUTH_SECRET"))
        self._token = None
        self._token_at = 0
        self.s = requests.Session()

    def _headers(self):
        if not self.key:
            return {}
        if not self._token or time.time() - self._token_at > 1800:
            r = self.s.post(self.api + "/token", json={"keyId": self.key, "keySecret": self.secret}, timeout=30)
            r.raise_for_status()
            self._token = r.json()["token"]
            self._token_at = time.time()
        return {"X-Authorization": self._token}

    def req(self, method, path, **kw):
        r = self.s.request(method, self.api + path, headers=self._headers(), timeout=kw.pop("timeout", 60), **kw)
        return r

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)

    def put(self, path, **kw):
        return self.req("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.req("DELETE", path, **kw)

    # convenience
    def register_workflow(self, wf):
        """Create or overwrite a workflow definition (PUT accepts a list)."""
        r = self.put("/metadata/workflow", json=[wf])
        if not r.ok:
            raise RuntimeError(f"register {wf['name']}: {r.status_code} {r.text[:500]}")
        return r

    def register_tasks(self, tasks):
        r = self.post("/metadata/taskdefs", json=tasks)
        if not r.ok and r.status_code != 409:
            # overwrite existing defs one by one
            for t in tasks:
                u = self.put("/metadata/taskdefs", json=t)
                if not u.ok:
                    raise RuntimeError(f"taskdef {t['name']}: {u.status_code} {u.text[:300]}")
        return r

    def start(self, name, inp, version=None, correlation_id=None):
        body = {"name": name, "input": inp}
        if version:
            body["version"] = version
        if correlation_id:
            body["correlationId"] = correlation_id
        r = self.post("/workflow", json=body)
        if not r.ok:
            raise RuntimeError(f"start {name}: {r.status_code} {r.text[:500]}")
        return r.text.strip().strip('"')

    def execution(self, wid, include_tasks=True):
        r = self.get(f"/workflow/{wid}", params={"includeTasks": str(include_tasks).lower()})
        r.raise_for_status()
        return r.json()

    def wait(self, wid, timeout=900, poll=3):
        t0 = time.time()
        while True:
            ex = self.execution(wid, include_tasks=False)
            if ex["status"] in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
                return self.execution(wid)
            if time.time() - t0 > timeout:
                return self.execution(wid)
            time.sleep(poll)
