"""Rebuild worker/index.js without Appflare, an account, or a signing key."""
import argparse
import hashlib
from pathlib import Path
import tempfile

import release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("rebuilt-index.js"))
    parser.add_argument("--wrangler", type=Path, help="use an existing Wrangler 4.136.2 bin/wrangler.js")
    parser.add_argument("--no-install", action="store_true", help="reuse previously installed Attest dependencies")
    parser.add_argument("--modified", action="store_true", help="build local edits and print their new hash")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    checkout = root / "attest"
    if not args.no_install:
        release.run("pnpm", "install", "--ignore-scripts", "--frozen-lockfile", cwd=checkout)
    if args.wrangler:
        wrangler = args.wrangler.resolve()
    else:
        release.run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=root / "toolchain")
        wrangler = root / "toolchain/node_modules/wrangler/bin/wrangler.js"
    if release.read_json(wrangler.parent.parent / "package.json")["version"] != "4.136.2":
        raise ValueError("the release was built with Wrangler 4.136.2")
    with tempfile.TemporaryDirectory() as tmp:
        binary, _ = release.get_worker(wrangler, checkout, Path(tmp) / "dry-run")
    digest = hashlib.sha256(binary).hexdigest()
    expected = release.read_json(root / "build-inputs.json")["workerSha256"]
    if not args.modified and digest != expected:
        raise ValueError(f"Worker differs from release: {digest} (expected {expected})")
    args.out.write_bytes(binary)
    print(f"{digest}  {args.out}")


if __name__ == "__main__":
    main()
