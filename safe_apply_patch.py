#!/usr/bin/env python3
import subprocess, sys, shutil, os

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def main():
    if len(sys.argv) < 2:
        print("usage: python safe_apply_patch.py file.patch")
        sys.exit(2)
    patch = sys.argv[1]
    if not os.path.exists(patch):
        print("patch not found")
        sys.exit(2)
    if shutil.which("git"):
        code, out, err = run(["git","apply","--3way",patch])
        if code == 0:
            print("ok: git apply --3way")
            sys.exit(0)
        code2, out2, err2 = run(["git","apply","--reject",patch])
        if code2 == 0:
            print("ok: git apply --reject (check .rej)")
            sys.exit(0)
        print(err or err2)
    if shutil.which("patch"):
        code, out, err = run(["patch","-p0","-i",patch,"--backup","--verbose"])
        if code == 0:
            print("ok: patch -p0")
            sys.exit(0)
        print(err)
    print("failed to apply patch")
    sys.exit(1)

if __name__ == "__main__":
    main()