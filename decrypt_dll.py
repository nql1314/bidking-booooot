import os
import sys

KEY = b"ryrs"
DEFAULT_DIR = r"F:\SteamLibrary\backup\BidKing\BidKing_Data\StreamingAssets\dll"

PE_MAGIC = b"MZ"
PDB_MAGIC = b"BSJB"


def is_plaintext(data: bytes, expect_pdb: bool) -> bool:
    if len(data) < 4:
        return False
    if expect_pdb:
        return data[:4] == PDB_MAGIC
    return data[:2] == PE_MAGIC


def decrypt_bytes(data: bytes) -> bytes:
    return bytes(data[i] ^ KEY[i % 4] for i in range(len(data)))


def process_file(src: str, dst: str) -> None:
    data = open(src, "rb").read()
    expect_pdb = src.lower().endswith(".pdb.bytes")
    name = os.path.basename(src)

    if is_plaintext(data, expect_pdb):
        out = data
        action = "复制"
    else:
        out = decrypt_bytes(data)
        if not is_plaintext(out, expect_pdb):
            raise ValueError(f"解密后格式异常: {name}")
        action = "解密"

    open(dst, "wb").write(out)
    print(f"[{action}] {name} -> {os.path.basename(dst)} ({len(out)} bytes)")


def collect_targets(directory: str) -> list[str]:
    names = []
    for entry in sorted(os.listdir(directory)):
        lower = entry.lower()
        if not (lower.endswith(".dll.bytes") or lower.endswith(".pdb.bytes")):
            continue
        if ".bak" in lower:
            continue
        names.append(entry)
    return names


def main() -> None:
    args = sys.argv[1:]
    directory = DEFAULT_DIR
    names: list[str] = []

    if args and args[0] in ("-d", "--dir"):
        if len(args) < 2:
            print("用法: python decrypt_dll.py [-d 目录] [文件1 文件2 ...]")
            sys.exit(1)
        directory = args[1]
        args = args[2:]

    if args:
        names = args
    else:
        names = collect_targets(directory)

    if not names:
        print(f"未找到 .dll.bytes / .pdb.bytes: {directory}")
        sys.exit(1)

    ok = 0
    for name in names:
        src = os.path.join(directory, name)
        if not os.path.isfile(src):
            print(f"[跳过] 不存在: {name}")
            continue
        dst = os.path.join(directory, name.replace(".bytes", ""))
        try:
            process_file(src, dst)
            ok += 1
        except Exception as exc:
            print(f"[失败] {name}: {exc}")

    print(f"\n完成: {ok}/{len(names)}")


if __name__ == "__main__":
    main()
