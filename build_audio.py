"""Build the vocabulary site with a Youdao lookup for every entry."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode


def build(source, output):
    html = (source / "index.html").read_text(encoding="utf-8")
    match = re.search(r"^const ITEMS\s*=\s*(\[.*\]);$", html, re.MULTILINE)
    if match is None:
        raise ValueError("Vocabulary data is missing from index.html")
    words = [item["en"] for item in json.loads(match.group(1))]
    rows = json.loads((source / "pronunciation-map.json").read_text(encoding="utf-8"))
    if words != [row[0] for row in rows]:
        raise ValueError("Pronunciation entries must follow the vocabulary list exactly")
    links = []
    for word, recording, *detail in rows:
        # Preserve the existing dictionary spelling and expand combined spellings
        # to a real headword, rather than searching for the study-list shorthand.
        if recording is None:
            lookup = detail[0]
        elif any(char in word for char in "(/"):
            lookup = Path(recording).stem if not detail else re.sub(r"\([^)]*\)", "", word.split("/")[0])
            lookup = {"fulfil": "fulfill", "fulfilment": "fulfillment"}.get(lookup, lookup)
        else:
            lookup = word
        if not lookup.strip():
            raise ValueError(f"No dictionary headword for {word!r}")
        links.append("https://www.youdao.com/result?" + urlencode({"word": lookup, "lang": "en"}))
    output.mkdir(parents=True, exist_ok=True)
    script = "const DICTIONARY_LINKS = " + json.dumps(links, separators=(",", ":")) + ";\n"
    (output / "pronunciations.js").write_text(script, encoding="utf-8")
    revision = sha256(script.encode("utf-8")).hexdigest()[:12]
    html = html.replace('src="./pronunciations.js"', f'src="./pronunciations.js?v={revision}"')
    (output / "index.html").write_text(html, encoding="utf-8")
    print(f"Built {len(links)} Youdao pronunciation links.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(Path(__file__).resolve().parent, args.output)
