"""Fetch the frida-il2cpp-bridge bundle from npm (one-time setup).

Run once to populate ``vendor/il2cpp_bridge.js`` before using dump_it_run.py.
No Node/npm required — grabs the tarball, extracts the compiled JS.
"""
from __future__ import annotations
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.13.1"
TARBALL_URL = (
    f"https://registry.npmjs.org/frida-il2cpp-bridge/-/"
    f"frida-il2cpp-bridge-{VERSION}.tgz"
)
INNER_PATH = "package/dist/index.js"
OUT = Path(__file__).parent / "vendor" / "il2cpp_bridge.js"


def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    print(f"[*] downloading frida-il2cpp-bridge@{VERSION}...")
    tarball_path = OUT.parent / f"bridge-{VERSION}.tgz"
    urllib.request.urlretrieve(TARBALL_URL, tarball_path)
    print(f"[+] {tarball_path.stat().st_size // 1024} KB downloaded")

    with tarfile.open(tarball_path, "r:gz") as tar:
        member = tar.getmember(INNER_PATH)
        f = tar.extractfile(member)
        assert f is not None
        OUT.write_bytes(f.read())
    tarball_path.unlink()
    print(f"[+] wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"[+] setup done — you can now run dump_it_run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
