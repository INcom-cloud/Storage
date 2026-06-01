#!/usr/bin/env python3
"""순수 Python RPM 생성기 — T2-lite v2 (DB+API+승인게이트, stdlib 전용).

탐지→보고→승인→조치(dry-run)→완료 폐루프:
  - API : http.server
  - DB  : sqlite3 (/var/lib/osv-t2/t2.db)
  - 상태: pending_approval -> (approve) done / (reject) rejected
  - 조치: host1(no-repo/no-internet) 제약상 dry-run. 운영은 AWX가 root로 수행.
host1(RHVH el8.6 / python3.6) 에 rpm -ivh 로 설치.
출력: ./osv-t2-0.1.0-2.noarch.rpm
"""
import gzip
import hashlib
import struct
import sys

VERSION = "0.1.0"
RELEASE = "2"
NAME = "osv-t2"
MTIME = 1717000000

INIT_PY = b'"""OSV T2 (lite): stdlib http.server + sqlite3 + approval gate."""\n\n__version__ = "0.1.0"\n'

MAIN_PY = b'''import json
import os
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

DB = os.environ.get("OSV_T2_DB", "/var/lib/osv-t2/t2.db")
BIND = os.environ.get("OSV_T2_BIND", "0.0.0.0")
PORT = int(os.environ.get("OSV_T2_PORT", "8000"))


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def init_db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, "
                "payload TEXT, status TEXT, remediation TEXT, updated_ts TEXT)")
    con.commit()
    con.close()


def remediate(payload):
    # PoC remediation (dry-run). Production: AWX runs dnf/kernel update on approval.
    vulns = payload.get("vulns", []) if isinstance(payload, dict) else []
    planned = ["dnf update %s" % v.get("package", "?") for v in vulns]
    try:
        kernel = subprocess.check_output(["uname", "-r"]).decode().strip()
    except Exception:
        kernel = "unknown"
    return {
        "mode": "dry-run",
        "planned": planned,
        "running_kernel": kernel,
        "result": "simulated-success",
        "note": "production: AWX runs dnf/kernel update on approval (see 1-2.md)",
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _task_json(self, r):
        return {"id": r[0], "ts": r[1], "source": r[2],
                "payload": json.loads(r[3]), "status": r[4],
                "remediation": json.loads(r[5]) if r[5] else None,
                "updated_ts": r[6]}

    def _get_row(self, con, tid):
        return con.execute("SELECT id, ts, source, payload, status, remediation, "
                           "updated_ts FROM tasks WHERE id=?", (tid,)).fetchone()

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if self.path in ("/tasks", "/reports"):
            con = sqlite3.connect(DB)
            rows = con.execute("SELECT id, ts, source, payload, status, remediation, "
                               "updated_ts FROM tasks ORDER BY id").fetchall()
            con.close()
            self._send(200, [self._task_json(r) for r in rows])
            return
        parts = self.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "tasks":
            try:
                tid = int(parts[1])
            except ValueError:
                self._send(404, {"error": "not found"})
                return
            con = sqlite3.connect(DB)
            r = self._get_row(con, tid)
            con.close()
            self._send(200, self._task_json(r)) if r else self._send(404, {"error": "not found"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if self.path in ("/reports", "/tasks"):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else "{}"
            try:
                data = json.loads(raw)
            except Exception:
                self._send(400, {"error": "bad json"})
                return
            source = data.get("source", "unknown") if isinstance(data, dict) else "unknown"
            con = sqlite3.connect(DB)
            cur = con.execute("INSERT INTO tasks (ts, source, payload, status, "
                              "remediation, updated_ts) VALUES (?,?,?,?,?,?)",
                              (now(), source, json.dumps(data), "pending_approval", None, now()))
            con.commit()
            tid = cur.lastrowid
            con.close()
            sys.stdout.write("task %s created (pending_approval) source=%s\\n" % (tid, source))
            sys.stdout.flush()
            self._send(201, {"id": tid, "status": "pending_approval"})
            return
        if len(parts) == 3 and parts[0] == "tasks" and parts[2] in ("approve", "reject"):
            try:
                tid = int(parts[1])
            except ValueError:
                self._send(404, {"error": "not found"})
                return
            con = sqlite3.connect(DB)
            r = self._get_row(con, tid)
            if not r:
                con.close()
                self._send(404, {"error": "not found"})
                return
            if parts[2] == "reject":
                con.execute("UPDATE tasks SET status=?, updated_ts=? WHERE id=?",
                            ("rejected", now(), tid))
                con.commit()
                con.close()
                sys.stdout.write("task %s rejected\\n" % tid)
                sys.stdout.flush()
                self._send(200, {"id": tid, "status": "rejected"})
                return
            rem = remediate(json.loads(r[3]))
            con.execute("UPDATE tasks SET status=?, remediation=?, updated_ts=? WHERE id=?",
                        ("done", json.dumps(rem), now(), tid))
            con.commit()
            con.close()
            sys.stdout.write("task %s approved -> remediated(dry-run) -> done\\n" % tid)
            sys.stdout.flush()
            self._send(200, {"id": tid, "status": "done", "remediation": rem})
            return
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    init_db()
    sys.stdout.write("osv-t2 listening on %s:%s db=%s\\n" % (BIND, PORT, DB))
    sys.stdout.flush()
    HTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''

SERVICE = b'''[Unit]
Description=OSV T2 API+DB (lite, stdlib http.server + sqlite3 + approval gate)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=osvt2
Group=osvt2
StateDirectory=osv-t2
Environment=PYTHONPATH=/var/opt/osv-t2/src
Environment=OSV_T2_DB=/var/lib/osv-t2/t2.db
EnvironmentFile=/etc/osv-t2.env
ExecStart=/usr/bin/python3 -m t2
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
'''

ENV = b'''OSV_T2_BIND=0.0.0.0
OSV_T2_PORT=8000
'''

PREIN = b'''getent group osvt2 >/dev/null || groupadd -r osvt2
getent passwd osvt2 >/dev/null || useradd -r -g osvt2 -d /var/opt/osv-t2 -s /sbin/nologin -c "OSV T2" osvt2
exit 0
'''
POSTIN = b'''systemctl daemon-reload >/dev/null 2>&1 || :
systemctl enable osv-t2.service >/dev/null 2>&1 || :
exit 0
'''
PREUN = b'''if [ "$1" = "0" ]; then
  systemctl --no-reload disable osv-t2.service >/dev/null 2>&1 || :
  systemctl stop osv-t2.service >/dev/null 2>&1 || :
fi
exit 0
'''
POSTUN = b'''systemctl daemon-reload >/dev/null 2>&1 || :
exit 0
'''

DIR = None
FILES = [
    ("/etc/osv-t2.env",                       0o100640, 1 | 16, ENV),
    ("/etc/systemd/system/osv-t2.service",    0o100644, 0,      SERVICE),
    ("/var/opt/osv-t2",                       0o040755, 0,      DIR),
    ("/var/opt/osv-t2/src",                   0o040755, 0,      DIR),
    ("/var/opt/osv-t2/src/t2",                0o040755, 0,      DIR),
    ("/var/opt/osv-t2/src/t2/__init__.py",    0o100644, 0,      INIT_PY),
    ("/var/opt/osv-t2/src/t2/__main__.py",    0o100644, 0,      MAIN_PY),
]

# ---------------- RPM 코어 (검증됨, T1 make_rpm.py 와 동일) ----------------
NULL, CHAR, INT8, INT16, INT32, INT64, STRING, BIN, STRING_ARRAY, I18N = range(10)


def enc_value(store, typ, val):
    if typ == STRING:
        store += val.encode("utf-8") + b"\x00"
        return 1
    if typ == I18N:
        store += val.encode("utf-8") + b"\x00"
        return 1
    if typ == STRING_ARRAY:
        for s in val:
            store += s.encode("utf-8") + b"\x00"
        return len(val)
    if typ == BIN:
        store += bytes(val)
        return len(val)
    if typ == INT16:
        for v in val:
            store += struct.pack(">H", v & 0xFFFF)
        return len(val)
    if typ == INT32:
        for v in val:
            store += struct.pack(">I", v & 0xFFFFFFFF)
        return len(val)
    raise ValueError("bad type %r" % typ)


def align(store, n):
    while len(store) % n != 0:
        store += b"\x00"


def build_header(entries):
    entries = sorted(entries, key=lambda e: e[0])
    index = []
    store = bytearray()
    for tag, typ, val in entries:
        if typ == INT16:
            align(store, 2)
        elif typ == INT32:
            align(store, 4)
        offset = len(store)
        count = enc_value(store, typ, val)
        index.append((tag, typ, offset, count))
    out = bytearray()
    out += b"\x8e\xad\xe8" + bytes([1]) + b"\x00\x00\x00\x00"
    out += struct.pack(">II", len(index), len(store))
    for tag, typ, offset, count in index:
        out += struct.pack(">IIII", tag, typ, offset, count)
    out += bytes(store)
    return bytes(out)


def build_cpio(files):
    buf = bytearray()
    ino = 1
    for path, mode, flags, content in files:
        data = b"" if content is None else content
        name = ("." + path).encode("utf-8") + b"\x00"
        nlink = 2 if content is None else 1
        fields = [ino, mode, 0, 0, nlink, MTIME, len(data),
                  0, 0, 0, 0, len(name), 0]
        buf += b"070701" + b"".join(b"%08x" % (f & 0xFFFFFFFF) for f in fields)
        buf += name
        while len(buf) % 4 != 0:
            buf += b"\x00"
        buf += data
        while len(buf) % 4 != 0:
            buf += b"\x00"
        ino += 1
    name = b"TRAILER!!!\x00"
    buf += b"070701" + b"".join(b"%08x" % f for f in
                                [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0])
    buf += name
    while len(buf) % 4 != 0:
        buf += b"\x00"
    return bytes(buf)


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else \
        "%s-%s-%s.noarch.rpm" % (NAME, VERSION, RELEASE)

    basenames, dirnames, dirindexes = [], [], []
    filesizes, filemodes, filerdevs, filemtimes = [], [], [], []
    filedigests, filelinktos, fileflags = [], [], []
    fileusername, filegroupname, fileverify = [], [], []
    filedevices, fileinodes, filelangs = [], [], []
    total = 0
    ino = 1
    for path, mode, flags, content in FILES:
        d, b = path.rsplit("/", 1)
        d = d + "/"
        if d not in dirnames:
            dirnames.append(d)
        dirindexes.append(dirnames.index(d))
        basenames.append(b)
        if content is None:
            filesizes.append(0)
            filedigests.append("")
        else:
            filesizes.append(len(content))
            filedigests.append(hashlib.sha256(content).hexdigest())
            total += len(content)
        filemodes.append(mode)
        filerdevs.append(0)
        filemtimes.append(MTIME)
        filelinktos.append("")
        fileflags.append(flags)
        fileusername.append("root")
        filegroupname.append("root")
        fileverify.append(0xFFFFFFFF)
        filedevices.append(1)
        fileinodes.append(ino)
        filelangs.append("")
        ino += 1

    req_name = ["rpmlib(CompressedFileNames)", "rpmlib(FileDigests)",
                "rpmlib(PayloadFilesHavePrefix)", "python3"]
    req_ver = ["3.0.4-1", "4.6.0-1", "4.0-1", ""]
    RPMLIB = (1 << 24) | (1 << 1) | (1 << 3)
    req_flags = [RPMLIB, RPMLIB, RPMLIB, 0]

    E = [
        (100, STRING_ARRAY, ["C"]),
        (1000, STRING, NAME),
        (1001, STRING, VERSION),
        (1002, STRING, RELEASE),
        (1004, I18N, "OSV T2 API+DB (lite, approval gate)"),
        (1005, I18N, "T2-lite v2: stdlib http.server + sqlite3 + 승인게이트. host1 offline."),
        (1009, INT32, [total]),
        (1014, STRING, "Proprietary"),
        (1016, I18N, "Unspecified"),
        (1021, STRING, "linux"),
        (1022, STRING, "noarch"),
        (1023, STRING, PREIN.decode()),
        (1024, STRING, POSTIN.decode()),
        (1025, STRING, PREUN.decode()),
        (1026, STRING, POSTUN.decode()),
        (1028, INT32, filesizes),
        (1030, INT16, filemodes),
        (1033, INT16, filerdevs),
        (1034, INT32, filemtimes),
        (1035, STRING_ARRAY, filedigests),
        (1036, STRING_ARRAY, filelinktos),
        (1037, INT32, fileflags),
        (1039, STRING_ARRAY, fileusername),
        (1040, STRING_ARRAY, filegroupname),
        (1045, INT32, fileverify),
        (1047, STRING_ARRAY, [NAME]),
        (1048, INT32, req_flags),
        (1049, STRING_ARRAY, req_name),
        (1050, STRING_ARRAY, req_ver),
        (1064, STRING, "4.14.3"),
        (1085, STRING_ARRAY, ["/bin/sh"]),
        (1086, STRING_ARRAY, ["/bin/sh"]),
        (1087, STRING_ARRAY, ["/bin/sh"]),
        (1088, STRING_ARRAY, ["/bin/sh"]),
        (1095, INT32, filedevices),
        (1096, INT32, fileinodes),
        (1097, STRING_ARRAY, filelangs),
        (1112, INT32, [8]),
        (1113, STRING_ARRAY, ["%s-%s" % (VERSION, RELEASE)]),
        (1116, INT32, dirindexes),
        (1117, STRING_ARRAY, basenames),
        (1118, STRING_ARRAY, dirnames),
        (1124, STRING, "cpio"),
        (1125, STRING, "gzip"),
        (1126, STRING, "9"),
        (5011, INT32, [8]),
    ]

    main_hdr = build_header(E)
    cpio = build_cpio(FILES)
    payload = gzip.compress(cpio, 9)

    S = [
        (1000, INT32, [len(main_hdr) + len(payload)]),
        (1004, BIN, hashlib.md5(main_hdr + payload).digest()),
        (1007, INT32, [len(cpio)]),
    ]
    sig_hdr = build_header(S)
    pad = (8 - (len(sig_hdr) % 8)) % 8

    lead = bytearray()
    lead += b"\xed\xab\xee\xdb" + bytes([3, 0])
    lead += struct.pack(">h", 0) + struct.pack(">h", 1)
    nm = ("%s-%s-%s" % (NAME, VERSION, RELEASE)).encode()[:65]
    lead += nm + b"\x00" * (66 - len(nm))
    lead += struct.pack(">h", 1) + struct.pack(">h", 5) + b"\x00" * 16

    with open(out_path, "wb") as f:
        f.write(bytes(lead))
        f.write(sig_hdr)
        f.write(b"\x00" * pad)
        f.write(main_hdr)
        f.write(payload)

    print("[+] RPM 생성 완료:", out_path)
    print("    main header :", len(main_hdr), "bytes / payload:", len(payload))


if __name__ == "__main__":
    main()
