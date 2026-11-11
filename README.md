# Local socket spike

Throwaway spike. Checks whether a PyQt `QLocalSocket` client can talk to a
Node.js `net` server over a Unix domain socket (macOS, Linux) or a named pipe
(Windows), under PyQt5, PyQt6 and the Python that ships with QGIS.

- `server.js` listens on the given path and speaks length-prefixed JSON frames
  (4-byte little-endian length + UTF-8 JSON). It echoes each frame and, after
  `{"subscribe": true}`, pushes three events.
- `client.py` connects with `QLocalSocket`, and checks echo, a 1 MB round trip,
  pushes after idle, server-side close, and that a missing server errors promptly.
- `run.js` starts the server, waits for it to be ready, then runs a client command.
- `qgis_env.py` prints versions and import availability inside a QGIS Python.
- `perms_unix.sh`, `perms_win.ps1`, `perms_win.py` probe access by other local users.

```sh
node run.js python client.py
```

Results are in the workflow runs under Actions. Not maintained.
