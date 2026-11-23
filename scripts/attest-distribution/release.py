"""Create the Attest source release from the same bytes the packer uploaded."""
import argparse
import base64
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from email import policy
from email.parser import BytesParser

HERE = Path(__file__).resolve().parent
COMMIT = "5de9ae73a2547dc11ba21bd79e8bf3b734670dc7"
VERSION = "0.0.0-20261123.5de9ae7"
ASSET = "attest-verifier-source.tar.gz"
URL = f"https://github.com/gmackie/appflare-catalog/releases/download/attest-verifier%40{VERSION}/{ASSET}"
ENTRY = Path("apps/verifier/src/index.ts")
WELL_KNOWN = "/.well-known/attest-source"


def read_json(p):
    return json.loads(Path(p).read_text())


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def verify_sri(path, sri):
    alg, expected = sri.split("-", 1)
    with open(path, "rb") as stream:
        actual = hashlib.file_digest(stream, alg).digest()
    if actual != base64.b64decode(expected, validate=True):
        raise ValueError(f"digest mismatch: {path}")


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def member_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ValueError(f"invalid archive path {name}")
    return PurePosixPath(*p.parts[1:])


def archive(folder, dest):
    with open(dest, "wb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0, compresslevel=6) as gz:
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.GNU_FORMAT) as tar:
            for p in sorted(folder.rglob("*")):
                if p.is_symlink():
                    raise ValueError(f"unexpected link in source tree {p}")
                if p.is_file():
                    spec = tarfile.TarInfo("attest-verifier-source/" + p.relative_to(folder).as_posix())
                    spec.size = p.stat().st_size
                    spec.mode = 0o644
                    with p.open("rb") as f:
                        tar.addfile(spec, f)


def uploaded_js(raw):
    boundary = raw.split(b"\r\n", 1)[0].removeprefix(b"--")
    header = b'MIME-Version: 1.0\r\nContent-Type: multipart/form-data; boundary="' + boundary + b'"\r\n\r\n'
    msg = BytesParser(policy=policy.default).parsebytes(header + raw)
    parts = [p.get_payload(decode=True) for p in msg.iter_parts() if p.get_filename() == "index.js"]
    if len(parts) != 1:
        raise ValueError("expected exactly one Worker entry in Wrangler upload")
    return parts[0]


def run(*args, cwd=None):
    # No credentials are needed by these public downloads and local builds.
    env = {k: v for k, v in os.environ.items() if k in
           {"PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "CI", "PNPM_HOME", "LANG", "LC_ALL", "COREPACK_HOME"}}
    env.update({"WRANGLER_SEND_METRICS": "false", "CI": "true", "GIT_TERMINAL_PROMPT": "0"})
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, env=env)


def get_file(cache, name, url, sri=None):
    target = cache / name
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
            temp = Path(tmp.name)
        try:
            run("curl", "-fsSL", "--retry", "3", "--max-time", "420", "--proto", "=https", url, "-o", temp)
            if sri:
                verify_sri(temp, sri)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    elif sri:
        verify_sri(target, sri)
    return target


def git_text(checkout, *args):
    return subprocess.check_output(["git", *args], cwd=checkout, text=True).strip()


def unpack_upstream(cache, root, entry):
    rev = entry["commit"]
    if entry.get("gitBlobs"):
        # Zupass includes unrelated large artifacts; fetch the audited paths only.
        files = read_json(HERE / entry["gitBlobs"])
        out = root / "upstreams" / entry["repository"].replace("/", "--") / rev
        def copy_blob(item):
            name, blob = item
            path = member_path("source/" + name)
            url = f"https://raw.githubusercontent.com/{entry['repository']}/{rev}/{name}"
            src = get_file(cache, "git-" + blob, url)
            data = src.read_bytes()
            digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if digest != blob:
                raise ValueError(f"Git blob mismatch for {name}")
            target = out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as threads:
            list(threads.map(copy_blob, files.items()))
        shutil.copyfile(HERE / entry["gitBlobs"], root / entry["gitBlobs"])
        return out
    src = get_file(cache, rev + ".tgz", f"https://codeload.github.com/{entry['repository']}/tar.gz/{rev}")
    out = root / "upstreams" / entry["repository"].replace("/", "--") / rev
    out.mkdir(parents=True)
    with tarfile.open(src, "r|gz") as tar:
        for m in tar:
            path = member_path(m.name)
            if not m.isfile() or not path.parts:
                continue
            selected = len(path.parts) == 1 or any(
                path == PurePosixPath(i) or PurePosixPath(i) in path.parents for i in entry["include"])
            if not selected:
                continue
            dest = out / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                shutil.copyfileobj(tar.extractfile(m), f)
    digest = hashlib.sha256()
    for p in sorted(out.rglob("*")):
        if p.is_file():
            digest.update(p.relative_to(out).as_posix().encode() + b"\0" + bytes.fromhex(sha256(p)))
    if digest.hexdigest() != entry["filesSha256"]:
        raise ValueError(f"upstream source tree digest mismatch for {entry['repository']}: {digest.hexdigest()}")
    return out


def package_tar(cache, package):
    sri = package["integrity"]
    name = sri.split("-", 1)[1].rstrip("=").replace("/", "_").replace("+", "-") + ".tgz"
    return get_file(cache, name, package["tarball"], sri)


def package_data(file, dest, needed):
    # Read installed inputs against the integrity-checked registry tarball.
    notices, found = {}, {}
    with tarfile.open(file, "r|gz") as tar:
        for m in tar:
            rel = member_path(m.name)
            if not m.isfile() or not rel.parts:
                continue
            upper = rel.name.upper()
            legal = len(rel.parts) == 1 and (
                upper.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "THIRD_PARTY", "THIRD-PARTY"))
                or (dest.startswith("poseidon-lite@") and upper == "README.MD"))
            if legal or rel.as_posix() in needed:
                data = tar.extractfile(m).read()
                if legal:
                    notices[rel.as_posix()] = data.decode("utf-8-sig")
                if rel.as_posix() in needed:
                    found[rel.as_posix()] = hashlib.sha256(data).hexdigest()
    if needed != found:
        raise ValueError(f"installed inputs differ from pinned {dest} registry bytes")
    if not notices:
        raise ValueError(f"no license text for {dest}")
    return notices


def collect_sources(cache, folder, expected):
    pkgs = read_json(HERE / "packages.lock.json")
    if set(expected) != set(pkgs):
        raise ValueError(f"the Worker package inventory differs from lock: {set(expected) ^ set(pkgs)}")
    upstreams = read_json(HERE / "upstreams.lock.json")
    circuit = read_json(HERE / "circuit-inputs.lock.json")
    npm = folder / "npm"
    npm.mkdir()
    credits = {}
    def copy_npm(pair):
        key, data = pair
        tgz = package_tar(cache, data)
        dest = npm / (key.replace("/", "--") + ".tgz")
        shutil.copyfile(tgz, dest)
        if key in expected:
            return key, package_data(tgz, key, expected[key])
        return key, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for key, licenses in pool.map(copy_npm, sorted((pkgs | circuit).items())):
            if licenses:
                credits[key] = licenses
        roots = list(pool.map(lambda entry: unpack_upstream(cache, folder, entry), upstreams))
    refs = {entry["repository"]: path for entry, path in zip(upstreams, roots)}
    for repo in ["MetaMask/eth-sig-util", "iden3/js-crypto"]:
        license_files = sorted(p for p in refs[repo].glob("LICENSE*") if p.is_file())
        if not license_files:
            raise ValueError(f"missing reference license for {repo}")
        credits[repo] = {p.name: p.read_text() for p in license_files}
    credits["cryptocoinjs/blake-hash"] = {"README.md (License)": (refs["cryptocoinjs/blake-hash"] / "README.md").read_text().split("## LICENSE", 1)[1].split("[1]:", 1)[0].strip()}
    runtime = HERE / "runtime-sources"
    for name, info in read_json(runtime / "sources.json").items():
        if sha256(runtime / name) != info["sha256"]:
            raise ValueError(f"generated runtime source changed: {name}")
    shutil.copytree(runtime, folder / "runtime-sources")
    for name in ["esbuild/LICENSE.md", "workers-sdk/LICENSE-MIT", "workers-sdk/LICENSE-APACHE"]:
        credits["Generated runtime helpers from " + name] = {name: (runtime / name).read_text()}
    return credits


def metadata_inputs(checkout, meta):
    configdir = checkout / "apps/verifier"
    workspace, npm = set(), {}
    entries = [o for path, o in meta["outputs"].items() if path.endswith(".js")]
    if len(entries) != 1:
        raise ValueError("expected one emitted JavaScript module")
    active = {name for name, rec in entries[0]["inputs"].items() if rec["bytesInOutput"] > 0}
    for name in meta["inputs"]:
        if name in {"node-built-in-modules:buffer", "node-built-in-modules:crypto"}:
            continue
        path = (configdir / name).resolve(strict=True)
        rel = path.relative_to(checkout)
        if "node_modules" not in rel.parts:
            workspace.add(rel)
        elif name in active:
            parts = rel.parts
            start = len(parts) - parts[::-1].index("node_modules")
            stop = start + (2 if parts[start].startswith("@") else 1)
            pkg = read_json(checkout.joinpath(*parts[:stop], "package.json"))
            key = pkg["name"] + "@" + pkg["version"]
            package_file = PurePosixPath(*parts[stop:]).as_posix()
            npm.setdefault(key, {})[package_file] = sha256(path)
    return workspace, npm


def get_worker(wrangler, checkout, tmp):
    tmp.mkdir()
    run("node", wrangler, "deploy", "--dry-run", "--config", ".appflare.wrangler.jsonc",
        "--outdir", tmp / "out", "--outfile", tmp / "upload.form", "--metafile", tmp / "metafile.json",
        cwd=checkout / "apps/verifier")
    return uploaded_js((tmp / "upload.form").read_bytes()), read_json(tmp / "metafile.json")


def notice_text(credits, license_file):
    text = [(HERE / "NOTICE.txt").read_text(), "Matching source download: " + URL,
            "Attest original code — Apache License 2.0\n" + license_file.read_text()]
    # Keep each upstream notice verbatim; equivalent texts only print once.
    texts = {}
    for pkg, files in sorted(credits.items()):
        for name, body in sorted(files.items()):
            texts.setdefault(body, []).append(f"{pkg} — {name}")
    for body, owners in texts.items():
        text.append("\n".join(owners) + "\n\n" + body)
    return "\n\n".join(text).rstrip() + "\n"


def patch_entry(original, notices):
    anchor = "    try {\n      return await handler(request, env);"
    if original.count(anchor) != 1:
        raise ValueError("the audited Worker entry changed")
    replacement = (f'    if (request.method === "GET" && new URL(request.url).pathname === "{WELL_KNOWN}") {{\n'
                   f'      return new Response({json.dumps(notices, ensure_ascii=True)}, '
                   '{ headers: { "content-type": "text/plain; charset=utf-8" } });\n    }\n' + anchor)
    return "// Modified by the gmackie Appflare catalog on 2026-11-23 to serve the source and licenses.\n" + original.replace(anchor, replacement)


def copy_inputs(checkout, root, paths):
    tracked = set(git_text(checkout, "ls-files").splitlines())
    files = paths | {Path(name) for name in tracked if name.endswith("/package.json")}
    files |= {Path(x) for x in ["package.json","tsconfig.json","pnpm-lock.yaml","pnpm-workspace.yaml",
                                  "apps/verifier/LICENSE","apps/verifier/LICENSING.md","apps/verifier/wrangler.jsonc",
                                  "apps/verifier/scripts/new-result-key.mjs"]}
    for path in sorted(files):
        if path.as_posix() not in tracked:
            raise ValueError(f"untracked Worker source {path}")
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / path, dest)
    shutil.copyfile(checkout / "apps/verifier/.appflare.wrangler.jsonc", root / "apps/verifier/.appflare.wrangler.jsonc")


def build(args):
    checkout, out, packer = args.checkout.resolve(), args.out.resolve(), args.packer.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"expected empty output {out}")
    if git_text(checkout, "rev-parse", "HEAD") != COMMIT or git_text(checkout, "diff", "HEAD", "--name-only"):
        raise ValueError("expected a clean checkout at the audited Attest source pin")
    manifest = read_json(args.manifest)
    if (manifest["source"].get("sha"), manifest["source"].get("version"), manifest["license"], manifest["slug"]) != (COMMIT, VERSION, "GPL-3.0-only", "attest-verifier"):
        raise ValueError("expected the audited release pin, version, combined GPLv3 license and app slug")
    wrangler = packer.parent.parent / "node_modules/wrangler/bin/wrangler.js"
    if not wrangler.is_file() or read_json(wrangler.parent.parent / "package.json")["version"] != "4.136.2":
        raise ValueError("packer must use the audited Wrangler 4.136.2")
    if not args.no_install:
        run("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", cwd=checkout)
    cache = (args.cache or (out.parent / ".attest-source-cache")).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    manifest_file = args.manifest.resolve()
    with tempfile.TemporaryDirectory(prefix="attest-source-", dir=out.parent) as temp:
        tmp = Path(temp)
        distribution = tmp / "distribution"
        distribution.mkdir()
        run("node", packer, "inspect", checkout, "--config", "apps/verifier/wrangler.jsonc", "--manifest", manifest_file)
        _, meta = get_worker(wrangler, checkout, tmp / "before")
        files, inventory = metadata_inputs(checkout, meta)
        licenses = collect_sources(cache, distribution, inventory)
        notices = notice_text(licenses, checkout / "apps/verifier/LICENSE")
        (distribution / "NOTICES.txt").write_text(notices)
        original = (checkout / ENTRY).read_bytes()
        built = tmp / "packed"
        try:
            (checkout / ENTRY).write_text(patch_entry(original.decode(), notices))
            key = ["--key-id", args.key_id] if args.key_id and args.key_id != "unsigned" else []
            run("node", packer, checkout, "--manifest", manifest_file, "--out", built, "--no-install", *key)
            run("node", packer, "verify", built, "--hashes-only", "--check-upload")
            packed = read_json(built / "manifest.json")
            if packed["version"] != VERSION or len(packed["worker"]["modules"]) != 1:
                raise ValueError("unexpected artifact version or modules")
            with zipfile.ZipFile(next(built.glob("*.zip"))) as z:
                binary = z.read("worker/index.js")
            direct, final_meta = get_worker(wrangler, checkout, tmp / "final")
            if direct != binary:
                raise ValueError("Wrangler's independently rebuilt upload differs from actual Appflare zip")
            if metadata_inputs(checkout, final_meta) != (files, inventory):
                raise ValueError("the final Worker changed the dependency or workspace inventory")
            if URL.encode() not in binary or WELL_KNOWN.encode() not in binary:
                raise ValueError("source endpoint and URL missing from packed Worker")
            # Exercise the public source offer in exactly the JS from the zip.
            (tmp / "worker.mjs").write_bytes(binary)
            (tmp / "verify-offer.mjs").write_text(
                'import worker from "./worker.mjs";\n'
                'import {readFileSync} from "node:fs";\n'
                f'const response = await worker.fetch(new Request("https://verify.invalid{WELL_KNOWN}"), {{}});\n'
                'if (response.status !== 200 || await response.text() !== '
                'readFileSync(new URL("./distribution/NOTICES.txt", import.meta.url), "utf8")) '
                'throw new Error("Worker source offer or notice text differs");\n')
            run("node", tmp / "verify-offer.mjs")
            copy_inputs(checkout, distribution / "attest", files)
        finally:
            (checkout / ENTRY).write_bytes(original)
        binary_hash = hashlib.sha256(binary).hexdigest()
        write_json(distribution / "build-inputs.json", {"workerSha256": binary_hash, "sourceCommit":COMMIT,
                    "sourceUrl":URL, "files":sorted(f.as_posix() for f in files), "packages":inventory})
        shutil.copyfile(manifest_file, distribution / "appflare.json")
        (distribution / "toolchain").mkdir()
        for name in ["package.json", "package-lock.json"]:
            shutil.copyfile(HERE / "toolchain" / name, distribution / "toolchain" / name)
        for name in ["release.py","rebuild.py","NOTICE.txt","README.md","packages.lock.json","upstreams.lock.json","circuit-inputs.lock.json"]:
            shutil.copyfile(HERE / name, distribution / name)
        archive(distribution, built / ASSET)
        built.replace(out)
        print(f"Worker sha256 {binary_hash}\nCorresponding source sha256 {sha256(out / ASSET)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    for arg in ("checkout", "out", "packer", "manifest"):
        parser.add_argument("--" + arg, required=True, type=Path)
    parser.add_argument("--key-id", help="record the real catalog release key ID for later signing")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--no-install", action="store_true", help="reuse this checkout's existing frozen dependency install")
    build(parser.parse_args())
