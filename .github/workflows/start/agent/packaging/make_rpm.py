#!/usr/bin/env python3
"""순수 Python RPM 생성기 (rpmbuild 불필요).

Windows/리눅스 어디서든 python3 만 있으면 osv-agent noarch RPM 을 만든다.
host1(RHVH el8.6)에 'rpm -ivh' 로 바로 설치되도록 설계:
  - python 3.6 호환 에이전트 (dataclasses 미사용)
  - unit -> /etc/systemd/system (RHVH /usr read-only 회피)
  - app  -> /var/opt/osv-agent (쓰기 영역)
  - Requires: python3 (버전 하한 없음 -> el8 3.6.8 충족)
출력: ./osv-agent-0.1.0-1.noarch.rpm  (또는 인자로 받은 경로)
"""
import gzip
import hashlib
import io
import struct
import sys

VERSION = "0.1.0"
RELEASE = "2"
NAME = "osv-agent"
MTIME = 1717000000  # 고정 빌드시각(재현성)

# ---------------- 패키지에 담을 파일 내용 ----------------
INIT_PY = b'"""OSV \xec\xb7\xa8\xec\x95\xbd\xec\xa0\x90 \xec\x88\x98\xec\xa7\x91 \xec\x97\x90\xec\x9d\xb4\xec\xa0\x84\xed\x8a\xb8 (T1)."""\n\n__version__ = "0.1.0"\n'

CONFIG_PY = b'''import os


class Config(object):
    def __init__(self, t2_api_url, t2_api_key, osv_api_timeout,
                 collector_interval, log_level):
        self.t2_api_url = t2_api_url
        self.t2_api_key = t2_api_key
        self.osv_api_timeout = osv_api_timeout
        self.collector_interval = collector_interval
        self.log_level = log_level

    @classmethod
    def from_env(cls):
        return cls(
            t2_api_url=os.environ.get("T2_API_URL", "http://t2-api:8000"),
            t2_api_key=os.environ.get("T2_API_KEY", ""),
            osv_api_timeout=int(os.environ.get("OSV_API_TIMEOUT", "30")),
            collector_interval=int(os.environ.get("COLLECTOR_INTERVAL", "3600")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
'''

MAIN_PY = b'''import json
import logging
import socket
import sys
import time
from urllib import request as urlrequest

from .config import Config


def setup_logging(level):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("osv-agent")


def collect_once(cfg, log):
    log.info("OSV collect start (timeout=%ss)", cfg.osv_api_timeout)
    report = {
        "source": "t1-agent",
        "host": socket.gethostname(),
        "vulns": [{"id": "OSV-DEMO-0001", "package": "demo", "severity": "HIGH"}],
    }
    url = cfg.t2_api_url.rstrip("/") + "/reports"
    body = json.dumps(report).encode("utf-8")
    req = urlrequest.Request(url, data=body,
                             headers={"Content-Type": "application/json"})
    try:
        resp = urlrequest.urlopen(req, timeout=cfg.osv_api_timeout)
        log.info("T2 report ok: %s -> HTTP %s", url, resp.getcode())
    except Exception as e:
        log.warning("T2 report failed: %s (%s)", url, e)
    return 0


def main():
    cfg = Config.from_env()
    log = setup_logging(cfg.log_level)
    log.info("osv-agent started (interval=%ss)", cfg.collector_interval)
    try:
        while True:
            collect_once(cfg, log)
            time.sleep(cfg.collector_interval)
    except KeyboardInterrupt:
        log.info("stop signal, exit")
        return 0
    except Exception:
        log.exception("error during collect")
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''

SERVICE = b'''[Unit]
Description=OSV Vulnerability Collector Agent (T1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=osvagent
Group=osvagent
Environment=PYTHONPATH=/var/opt/osv-agent/src
EnvironmentFile=/etc/osv-agent.env
ExecStart=/usr/bin/python3 -m agent
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
'''

ENV = b'''T2_API_URL=http://127.0.0.1:8000
T2_API_KEY=your-secret-key
OSV_API_TIMEOUT=30
COLLECTOR_INTERVAL=3600
LOG_LEVEL=INFO
'''

PREIN = b'''getent group osvagent >/dev/null || groupadd -r osvagent
getent passwd osvagent >/dev/null || useradd -r -g osvagent -d /var/opt/osv-agent -s /sbin/nologin -c "OSV Agent" osvagent
exit 0
'''
POSTIN = b'''systemctl daemon-reload >/dev/null 2>&1 || :
systemctl enable osv-agent.service >/dev/null 2>&1 || :
exit 0
'''
PREUN = b'''if [ "$1" = "0" ]; then
  systemctl --no-reload disable osv-agent.service >/dev/null 2>&1 || :
  systemctl stop osv-agent.service >/dev/null 2>&1 || :
fi
exit 0
'''
POSTUN = b'''systemctl daemon-reload >/dev/null 2>&1 || :
exit 0
'''

# 파일 목록: (전체경로, mode, flags, content|None=dir)
DIR = None
FILES = [
    ("/etc/osv-agent.env",                              0o100640, 0o0 | 1 | 16, ENV),  # config|noreplace
    ("/etc/systemd/system/osv-agent.service",           0o100644, 0,           SERVICE),
    ("/var/opt/osv-agent",                              0o040755, 0,           DIR),
    ("/var/opt/osv-agent/src",                          0o040755, 0,           DIR),
    ("/var/opt/osv-agent/src/agent",                    0o040755, 0,           DIR),
    ("/var/opt/osv-agent/src/agent/__init__.py",        0o100644, 0,           INIT_PY),
    ("/var/opt/osv-agent/src/agent/config.py",          0o100644, 0,           CONFIG_PY),
    ("/var/opt/osv-agent/src/agent/__main__.py",        0o100644, 0,           MAIN_PY),
]

# ---------------- RPM 타입 상수 ----------------
NULL, CHAR, INT8, INT16, INT32, INT64, STRING, BIN, STRING_ARRAY, I18N = range(10)


def enc_value(store, typ, val):
    if typ in (STRING,):
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
    if typ == INT8:
        for v in val:
            store += struct.pack("B", v & 0xFF)
        return len(val)
    if typ == INT16:
        for v in val:
            store += struct.pack(">H", v & 0xFFFF)
        return len(val)
    if typ == INT32:
        for v in val:
            store += struct.pack(">I", v & 0xFFFFFFFF)
        return len(val)
    if typ == INT64:
        for v in val:
            store += struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF)
        return len(val)
    raise ValueError("bad type %r" % typ)


def align(store, n):
    while len(store) % n != 0:
        store += b"\x00"


def build_header(entries):
    """entries: list of (tag, type, value). 태그 오름차순 정렬해서 헤더 blob 생성."""
    entries = sorted(entries, key=lambda e: e[0])
    index = []
    store = bytearray()
    for tag, typ, val in entries:
        if typ == INT16:
            align(store, 2)
        elif typ == INT32:
            align(store, 4)
        elif typ == INT64:
            align(store, 8)
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
        hdr = b"070701"
        fields = [
            ino, mode, 0, 0, nlink, MTIME, len(data),
            0, 0, 0, 0, len(name), 0,
        ]
        hdr += b"".join(b"%08x" % (f & 0xFFFFFFFF) for f in fields)
        buf += hdr + name
        while len(buf) % 4 != 0:
            buf += b"\x00"
        buf += data
        while len(buf) % 4 != 0:
            buf += b"\x00"
        ino += 1
    # trailer
    name = b"TRAILER!!!\x00"
    hdr = b"070701" + b"".join(
        b"%08x" % f for f in [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0]
    )
    buf += hdr + name
    while len(buf) % 4 != 0:
        buf += b"\x00"
    return bytes(buf)


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "osv-agent-%s-%s.noarch.rpm" % (VERSION, RELEASE)

    # 파일 메타 배열 구성
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
    RPMLIB = (1 << 24) | (1 << 1) | (1 << 3)  # rpmlib|LESS|EQUAL
    req_flags = [RPMLIB, RPMLIB, RPMLIB, 0]

    E = [
        (100, STRING_ARRAY, ["C"]),
        (1000, STRING, NAME),
        (1001, STRING, VERSION),
        (1002, STRING, RELEASE),
        (1004, I18N, "OSV Vulnerability Collector Agent (T1)"),
        (1005, I18N, "T1 OSV vulnerability collector agent (offline). Runs on system python3."),
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
        (1047, STRING_ARRAY, ["osv-agent"]),
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
    payload = gzip.compress(build_cpio(FILES), 9)

    sig_size = len(main_hdr) + len(payload)
    sig_md5 = hashlib.md5(main_hdr + payload).digest()
    S = [
        (1000, INT32, [sig_size]),
        (1004, BIN, sig_md5),
        (1007, INT32, [len(build_cpio(FILES))]),
    ]
    sig_hdr = build_header(S)
    pad = (8 - (len(sig_hdr) % 8)) % 8

    lead = bytearray()
    lead += b"\xed\xab\xee\xdb"
    lead += bytes([3, 0])            # version 3.0
    lead += struct.pack(">h", 0)     # type binary
    lead += struct.pack(">h", 1)     # archnum
    nm = ("%s-%s-%s" % (NAME, VERSION, RELEASE)).encode()[:65]
    lead += nm + b"\x00" * (66 - len(nm))
    lead += struct.pack(">h", 1)     # osnum linux
    lead += struct.pack(">h", 5)     # sig type = headersig
    lead += b"\x00" * 16

    with open(out_path, "wb") as f:
        f.write(bytes(lead))
        f.write(sig_hdr)
        f.write(b"\x00" * pad)
        f.write(main_hdr)
        f.write(payload)

    print("[+] RPM 생성 완료:", out_path)
    print("    main header :", len(main_hdr), "bytes")
    print("    payload     :", len(payload), "bytes (gzip cpio)")
    print("    sig md5     :", sig_md5.hex())


if __name__ == "__main__":
    main()
