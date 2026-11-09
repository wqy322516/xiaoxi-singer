from pathlib import Path
import shutil, ast

src = Path("C:/Users/wqy32/AppData/Local/Temp/ACE-Step-main/acestep/models/lyrics_utils/lyric_tokenizer.py")
dst = Path(r"D:\UserProfile\wqy32\dsh\home\work\xiaoxi-singer\orig\pylibs\acestep\models\lyrics_utils\lyric_tokenizer.py")
shutil.copyfile(src, dst)

s = dst.read_text(encoding="utf-8")
old_imports = "from spacy.lang.ar import Arabic\nfrom spacy.lang.en import English\nfrom spacy.lang.es import Spanish\nfrom spacy.lang.ja import Japanese\nfrom spacy.lang.zh import Chinese"
new_imports = (
    "try:  # spacy 只用于超长歌词断句，装不上也能跑（退化成正则切分）\n"
    "    from spacy.lang.ar import Arabic\n"
    "    from spacy.lang.en import English\n"
    "    from spacy.lang.es import Spanish\n"
    "    from spacy.lang.ja import Japanese\n"
    "    from spacy.lang.zh import Chinese\n"
    "except Exception:  # pragma: no cover\n"
    "    Arabic = English = Spanish = Japanese = Chinese = None"
)
assert old_imports in s
s = s.replace(old_imports, new_imports)

anchor = '    if text_split_length is not None and len(text) >= text_split_length:\n        text_splits.append("")\n        nlp = get_spacy_lang(lang)'
assert anchor in s
lines = s.splitlines(True)
i = next(k for k, l in enumerate(lines) if l.startswith(anchor.split("\n")[0]))
block = [
    "    if text_split_length is not None and len(text) >= text_split_length and Chinese is None:\n",
    "        flat = text.replace(chr(10), chr(0x3002))\n",
    "        parts = [x for x in re.split(r\"(?<=[\u3002\uff01\uff1f\uff1b!?;])\", flat) if x.strip()]\n",
    "        out, cur = [], \"\"\n",
    "        for part in parts:\n",
    "            if len(cur) + len(part) <= text_split_length:\n",
    "                cur += part\n",
    "            else:\n",
    "                if cur:\n",
    "                    out.append(cur.strip())\n",
    "                cur = part\n",
    "        if cur.strip():\n",
    "            out.append(cur.strip())\n",
    "        text_splits = out or [text.lstrip()]\n",
    "    elif " + anchor.split("\n")[0].strip() + ":\n",
    '        text_splits.append("")\n',
    "        nlp = get_spacy_lang(lang)\n",
]
lines[i:i + 3] = block
s = "".join(lines)
ast.parse(s)
dst.write_text(s, encoding="utf-8")
print("patched ok")
