"""Build the vocabulary site from the pinned KU-ArtLex studio recordings."""

import argparse
from array import array
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.parse import urlencode
import wave

ARTLEX_URL = "https://gitlab.com/chredmon/ku-artlex_eng1.git"
ARTLEX_COMMIT = "785ab39b274fef3ab2066ca875e5830e8a6fa423"
DICTIONARY_URL = "https://www.youdao.com/result"


def read_rows(source):
    html = (source / "index.html").read_text(encoding="utf-8")
    match = re.search(r"^const ITEMS\s*=\s*(\[.*\]);$", html, re.MULTILINE)
    if not match:
        raise ValueError("Vocabulary data is missing from index.html")
    words = [item["en"] for item in json.loads(match.group(1))]
    rows = json.loads((source / "pronunciation-map.json").read_text(encoding="utf-8"))
    if words != [row[0] for row in rows]:
        raise ValueError("Pronunciation entries must follow the vocabulary list exactly")
    for word, recording, *detail in rows:
        if recording is None:
            if len(detail) != 1 or not isinstance(detail[0], str) or not detail[0]:
                raise ValueError(f"Dictionary lookup is missing for {word!r}")
        elif detail:
            if (not re.fullmatch(r"[0-9]+-[0-9]+\.wav", recording)
                or len(detail) != 2
                or any(not isinstance(value, (int, float)) for value in detail)
                or not 0 <= detail[0] < detail[1]):
                raise ValueError(f"Invalid recording segment for {word!r}")
        elif not re.fullmatch(r"[\w.' -]+\.wav", recording):
            raise ValueError(f"Invalid recording mapping for {word!r}")
    return rows


def recording_path(filename, bounds):
    directory = "raw_files" if bounds else "lexicon"
    return Path(directory) / filename


def fetch_recordings(destination, rows):
    paths = sorted({
        recording_path(recording, bounds).as_posix()
        for _, recording, *bounds in rows if recording is not None
    })
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
    patterns = ["/LICENSE", *(f"/{path}" for path in paths)]
    subprocess.run(
        [*git, "sparse-checkout", "set", "--no-cone", "--stdin"],
        input="\n".join(patterns) + "\n",
        text=True,
        check=True,
    )
    subprocess.run([*git, "checkout", "--detach", ARTLEX_COMMIT], check=True)


def encode(file, output, bounds):
    with wave.open(str(file)) as audio:
        sample_rate = audio.getframerate()
        samples = audio.getnframes()
        first, last = (round(time * sample_rate) for time in bounds) if bounds else (0, samples)
        if not 0 <= first < last <= samples or not 0.12 <= (last - first) / sample_rate <= 4:
            raise ValueError(f"Unexpected duration for {file.name}")
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError(f"Expected mono 16-bit PCM for {file.name}")
        audio.setpos(first)
        frames = audio.readframes(last - first)
    levels = array("h", frames)
    peak = max(max(levels), -min(levels))
    if peak < 100:
        raise ValueError(f"Silent recording for {file.name}")
    gain = min(1.41, 30000 / peak)
    command = ["lame", "--quiet", "-m", "m", "-b", "64", "--scale", f"{gain:.5f}"]
    if bounds:
        with NamedTemporaryFile(suffix=".wav") as clip:
            with wave.open(clip.name, "wb") as wav:
                wav.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                wav.writeframes(frames)
            subprocess.run([*command, clip.name, str(output)], check=True)
    else:
        subprocess.run([*command, str(file), str(output)], check=True)
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
        index, (_, recording, *detail) = row
        if recording is None:
            return DICTIONARY_URL + "?" + urlencode({"word": detail[0], "lang": "en"})
        file = corpus / recording_path(recording, detail)
        encode(file, audio / f"{index}.mp3", detail)
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
