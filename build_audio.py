"""Build the vocabulary site from the pinned KU-ArtLex studio recordings."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
import wave

ARTLEX_URL = "https://gitlab.com/chredmon/ku-artlex_eng1.git"
ARTLEX_COMMIT = "785ab39b274fef3ab2066ca875e5830e8a6fa423"
DICTIONARY_URL = "https://dictionary.cambridge.org/us/search/english/"


def read_rows(source):
    html = (source / "index.html").read_text(encoding="utf-8")
    match = re.search(r"^const ITEMS\s*=\s*(\[.*\]);$", html, re.MULTILINE)
    if not match:
        raise ValueError("Vocabulary data is missing from index.html")
    words = [item["en"] for item in json.loads(match.group(1))]
    rows = json.loads((source / "pronunciation-map.json").read_text(encoding="utf-8"))
    if words != [row[0] for row in rows]:
        raise ValueError("Pronunciation entries must follow the vocabulary list exactly")
    for word, *entry in rows:
        if entry and entry[0] is None and len(entry) == 2 and entry[1]:
            continue
        if not entry or any(
            not isinstance(name, str) or not re.fullmatch(r"[\w.' -]+\.wav", name)
            for name in entry
        ):
            raise ValueError(f"Invalid recording mapping for {word!r}")
    return rows


def fetch_recordings(destination, rows):
    filenames = sorted({file for _, *entry in rows if entry[0] for file in entry})
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
         ARTLEX_URL, str(destination)],
        check=True,
    )
    git = ["git", "-C", str(destination)]
    subprocess.run(
        [*git, "fetch", "--depth=1", "--filter=blob:none", "origin", ARTLEX_COMMIT],
        check=True,
    )
    paths = ["/LICENSE", *(f"/lexicon/{name}" for name in filenames)]
    subprocess.run(
        [*git, "sparse-checkout", "set", "--no-cone", "--stdin"],
        input="\n".join(paths) + "\n",
        text=True,
        check=True,
    )
    subprocess.run([*git, "checkout", "--detach", ARTLEX_COMMIT], check=True)


def encode(files, output):
    for file in files:
        with wave.open(str(file)) as audio:
            duration = audio.getnframes() / audio.getframerate()
            if not 0.12 <= duration <= 4:
                raise ValueError(f"Unexpected duration for {file.name}: {duration:.2f}s")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y"]
    for file in files:
        command.extend(["-i", str(file)])
    gain = "volume=3dB,alimiter=limit=0.95:level=false:latency=true"
    if len(files) > 1:
        command.extend(["-filter_complex", f"concat=n={len(files)}:v=0:a=1,{gain}"])
    else:
        command.extend(["-af", gain])
    command.extend(["-map_metadata", "-1", "-ac", "1", "-ar", "22050",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(output)])
    subprocess.run(command, check=True)
    if output.stat().st_size < 1000:
        raise ValueError(f"Invalid MP3 for {output.name}")


def build(source, out, corpus, rows):
    audio = out / "us-audio"
    audio.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "index.html", out / "index.html")
    shutil.copyfile(source / "pronunciation-sources.html", out / "pronunciation-sources.html")
    shutil.copyfile(corpus / "LICENSE", out / "ku-artlex-license.txt")
    public = []

    def render(row):
        index, (word, *entry) = row
        if entry[0] is None:
            return DICTIONARY_URL + "?" + urlencode({"q": entry[1]})
        files = [corpus / "lexicon" / name for name in entry]
        encode(files, audio / f"{index}.mp3")
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        public.extend(pool.map(render, enumerate(rows)))
    (out / "pronunciations.js").write_text(
        "const DICTIONARY_LINKS = " + json.dumps(public, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    count = public.count(None)
    print(f"Built {count} US-English studio recordings and {len(public) - count} dictionary links.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--corpus", type=Path, help="Use an existing KU-ArtLex checkout")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    rows = read_rows(source)
    if args.corpus:
        build(source, args.output, args.corpus, rows)
    else:
        with TemporaryDirectory(prefix="ku-artlex-") as tmp:
            corpus = Path(tmp) / "source"
            fetch_recordings(corpus, rows)
            build(source, args.output, corpus, rows)


if __name__ == "__main__":
    main()
