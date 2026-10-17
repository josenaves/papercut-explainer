#!/usr/bin/env python3
# SEO kit for a papercut episode: title, description, tags, hashtags, VTT and thumbnail.
#
#   usage (from the episode's papercut/ folder):
#     python3 $PAPERCUT_LIB/tools/seo.py
#     python3 $PAPERCUT_LIB/tools/seo.py --project . --out ../seo
#     python3 $PAPERCUT_LIB/tools/seo.py --dry-run
#
# Reads (all optional except episode.json):
#   episode.json                 comp, out, fps, narration
#   ../narration/script.json     the spoken lines
#   ../research/facts.md         the BRIEF block (Claim, Source, CTA)
#   STORYBOARD.md                the SAY line (hook)
#   public/vo/captions.json      word timings, for the VTT
#   out/<out>.mp4                duration, resolution, thumbnail
#   seo.json                     authored overrides (recommended)
#
# Writes into ../seo/ (or --out):
#   title.txt, title-options.txt, description.md, tags.txt, hashtags.txt,
#   pinned-comment.txt, social-caption.md, subtitles.vtt, thumbnail.png,
#   metadata.json, manifest.json, README.md
#
# seo.json fields (all optional; authored wins over the fallback):
#   title, titleOptions, description, tags, hashtags, hashtagsByPlatform,
#   keywords, cta, pinnedComment, social, freebie, sources
import argparse, json, os, re, subprocess, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ---------- small helpers ----------
STOP = set("""a ao aos aquela aquelas aquele aqueles aquilo as até com como da das de do dos e ela elas ele eles em entre era eram essa essas esse esses esta estas este estes foi foram há isso isto já lhe lhes mais mas me mesmo meu meus minha minhas muito na nas nem no nos nossa nossas nosso nossos nunca o os ou para pela pelas pelo pelos por qual quando que quem se sem ser seu seus sua suas são só também tem têm todo toda todos todas um uma umas uns vai vão você vocês vos neste nesta disso deste desta nisso nesse nessa daquele daquela onde quais quanto quanta quantos quantas cada outro outra outros outras pois porque algo algum alguma alguns algumas nenhum nenhuma nada tudo antes após depois sobre sob vídeo videos video shorts short""".split())
GENERIC = set("""coisa coisas parte partes forma formas jeito jeitos vez vezes exemplo exemplos agora hoje aqui fazer faz fica ficar gera geram deve devem pode podem precisa precisam aula aulas curso cursos""".split())

def norm(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def dedupe(items):
    seen, out = set(), []
    for x in items:
        k = norm(clean(str(x)))
        if not k or k in seen:
            continue
        seen.add(k); out.append(clean(str(x)))
    return out

def cut_chars(items, limit):
    out, n = [], 0
    for x in items:
        add = (1 if out else 0) + len(x)
        if n + add > limit:
            break
        out.append(x); n += add
    return out

def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def parse_brief(text: str):
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().upper() == "BRIEF"), None)
    if start is None:
        return {}
    data, last = {}, None
    for l in lines[start + 1:]:
        if l.startswith("#") and data:
            break
        if not l.strip():
            if data:
                break
            continue
        m = re.match(r"^([A-Za-z][A-Za-z ]*):\s*(.*)$", l)
        if m:
            last = m.group(1).strip().lower()
            data[last] = m.group(2).strip()
        elif last:
            data[last] += " " + l.strip()
    return data

def urls_from(s: str):
    return [u.rstrip(".,;)]") for u in re.findall(r"https?://[^\s;]+", s or "")]

def hook_from(text: str):
    m = re.search(r"^SAY:\s*(.+)$", text, re.M)
    if not m:
        return ""
    return clean(m.group(1).strip().strip('"').strip("'").rstrip("."))

def keyword_from_cta(raw: str):
    m = re.match(r"^([A-Z0-9]{2,})\s*->\s*(.+)$", clean(raw))
    if m:
        return m.group(1).strip(), clean(m.group(2)).rstrip(".")
    return "", clean(raw).rstrip(".")

def cta_sentence(keyword: str, deliverable: str):
    if keyword and deliverable:
        d = deliverable
        if re.match(r"^(lista|planilha|checklist|mapa|guia)\b", d, re.I):
            d = "a " + d
        return f"Comenta {keyword} que eu te mando {d}."
    if keyword:
        return f"Comenta {keyword} que eu te mando o material."
    return "Comenta MATERIAL que eu te mando o material."

def extract_tags(texts, extra=(), max_items=20):
    freq = {}
    for text in texts:
        # URLs and the BRIEF keys are not keywords.
        text = re.sub(r"https?://\S+", " ", text or "")
        text = re.sub(r"^\s*(Source|Claim|Role|Mode|Format|Audience|CTA|Length):.*$", " ", text, flags=re.M)
        for w in re.findall(r"[a-zà-ú0-9]{4,}", text.lower()):
            if w in STOP or w in GENERIC or w.isdigit() or w in {"http", "https", "www"}:
                continue
            freq[w] = freq.get(w, 0) + 1
    ranked = [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))]
    tags = dedupe([*extra, *ranked, "curiosidades", "brasil", "shorts"])
    return cut_chars(tags[:max_items], 500)

def hashtag(w: str):
    h = re.sub(r"[^a-z0-9]", "", norm(w))
    if h in {"http", "https", "www"}:
        return ""
    return "#" + h if h else ""

def build_hashtags(keywords):
    weak = {"nome", "cidade", "video", "shorts", "historia", "curiosidades", "brasil",
            "coisa", "parte", "lugar", "pais", "mundo", "gente", "forma"}
    tags = [hashtag(k) for k in keywords if norm(k) not in weak]
    tags = [t for t in tags if t and len(t) > 2]
    if "#shorts" not in tags:
        tags.append("#shorts")
    return dedupe(tags)[:7]

def ts(ms: int):
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000; ms %= 60000
    s = ms // 1000; ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def write_vtt(captions, path: Path):
    if not captions:
        return False
    cues, cur = [], []
    for i, c in enumerate(captions):
        cur.append(c)
        nxt = captions[i + 1] if i + 1 < len(captions) else None
        punct = c["text"].strip().endswith((".", "!", "?", "…", ","))
        gap = (nxt["startMs"] - c["endMs"] > 280) if nxt else True
        if len(cur) >= 5 or punct or gap:
            cues.append(cur); cur = []
    if cur:
        cues.append(cur)
    total = captions[-1]["endMs"] + 400
    lines = ["WEBVTT", ""]
    for i, cue in enumerate(cues, 1):
        start = cue[0]["startMs"]
        end = cue[-1]["endMs"] + 140
        if i < len(cues):
            end = min(end, cues[i][0]["startMs"] - 30)
        else:
            end = min(end, total)
        if end <= start:
            end = start + 250
        text = " ".join(w["text"].strip() for w in cue)
        lines += [str(i), f"{ts(start)} --> {ts(end)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return True

def probe_video(path: Path):
    if not path.exists():
        return {}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
        st = (data.get("streams") or [{}])[0]
        dur = float(data.get("format", {}).get("duration") or 0)
        fps_raw = st.get("r_frame_rate") or "30/1"
        try:
            num, den = fps_raw.split("/")
            fps = round(float(num) / float(den), 2)
        except Exception:
            fps = 30
        return {"durationSec": round(dur, 2) if dur else 0,
                "resolution": f"{st.get('width', 1080)}x{st.get('height', 1920)}",
                "fps": fps}
    except Exception:
        return {}

def make_thumb(video: Path, out: Path):
    if not video.exists():
        return False
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "0.1", "-i", str(video),
             "-frames:v", "1", str(out)],
            check=True,
        )
        return out.exists()
    except Exception:
        return False

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Generate the SEO kit for a papercut episode.")
    ap.add_argument("--project", default=".", help="episode papercut/ folder (default: cwd)")
    ap.add_argument("--out", default="", help="output folder (default: <episode>/seo)")
    ap.add_argument("--no-thumb", action="store_true", help="do not extract a thumbnail from the mp4")
    ap.add_argument("--dry-run", action="store_true", help="print the summary, write nothing")
    ap.add_argument("--json", action="store_true", help="print a JSON summary")
    args = ap.parse_args()

    project = Path(args.project).expanduser().resolve()
    # Allow `--project <episode>/` as well as `--project <episode>/papercut/`.
    if not (project / "episode.json").exists() and (project / "papercut" / "episode.json").exists():
        project = project / "papercut"
    episode_dir = project.parent
    out_dir = Path(args.out).expanduser().resolve() if args.out else episode_dir / "seo"

    ep = read_json(project / "episode.json")
    if not ep:
        print(f"seo: no episode.json in {project}", file=sys.stderr)
        return 2

    # ---------- inputs ----------
    narration = (project / ep.get("narration", "../narration")).resolve()
    script = read_json(narration / "script.json", []) or []
    lines = [clean(x.get("text", "")) for x in script if clean(x.get("text", ""))]
    facts_path = episode_dir / "research" / "facts.md"
    facts = read_text(facts_path)
    brief = parse_brief(facts)
    storyboard = read_text(project / "STORYBOARD.md")
    authored = read_json(project / "seo.json", {}) or {}
    captions = read_json(project / "public" / "vo" / "captions.json", []) or []

    # ---------- derived copy ----------
    claim = clean(brief.get("claim", "")) or (lines[0] if lines else "")
    hook = hook_from(storyboard) or (lines[0] if lines else claim)
    keyword, deliverable = keyword_from_cta(brief.get("cta", ""))
    keyword = clean(authored.get("keyword", "")) or keyword or "MATERIAL"
    cta = clean(authored.get("cta", "")) or cta_sentence(keyword, deliverable)
    sources = authored.get("sources") or urls_from(brief.get("source", ""))
    sources = dedupe(sources)

    slug_words = [w for w in re.split(r"[-_]", episode_dir.name) if w and not w.isdigit()]
    extra = [" ".join(slug_words)] if slug_words else []
    tags = authored.get("tags")
    if not tags:
        texts = [claim, hook, *lines, facts]
        tags = extract_tags(texts, extra=extra, max_items=20)
    tags = cut_chars(dedupe(tags), 500)

    keywords = authored.get("keywords") or tags[:8]
    hashtags = authored.get("hashtags") or build_hashtags(keywords)
    hashtags = [h if h.startswith("#") else "#" + h.lstrip("#") for h in dedupe(hashtags)][:7]
    if not hashtags:
        hashtags = ["#shorts"]
    hb = authored.get("hashtagsByPlatform") or {}
    hashtags_by_platform = {
        "youtube": hashtags,
        "instagram": dedupe(hashtags + ["#reels", "#explorar", "#brasil"]),
        "tiktok": dedupe(hashtags + ["#fyp", "#foryou"]),
    }
    for k, v in hb.items():
        hashtags_by_platform[k] = dedupe(v)

    title = clean(authored.get("title", "")) or hook or claim or episode_dir.name
    title = title if len(title) <= 100 else title[:97].rstrip() + "…"

    title_options = authored.get("titleOptions") or dedupe([
        title,
        claim if claim and claim != title else "",
        (lines[0] if lines and lines[0] != title else ""),
        ("A história por trás de " + title) if title else "",
    ])
    title_options = [t if len(t) <= 100 else t[:97].rstrip() + "…" for t in title_options]

    description = clean(authored.get("description", ""))
    if not description:
        parts = [claim or hook]
        body = [l for l in lines[1:] if not re.search(r"\bcomenta\b", l, re.I)]
        if body:
            parts.append(" ".join(body))
        parts.append("🎁 " + cta)
        if sources:
            hosts = []
            for u in sources:
                h = urlparse(u).netloc.replace("www.", "")
                if h:
                    hosts.append(h)
            parts.append("Fontes: " + ", ".join(hosts))
        description = "\n\n".join(p for p in parts if p)
    # make sure the hashtags are present at the end
    missing = [h for h in hashtags if h not in description]
    if missing:
        description = description.rstrip() + "\n\n" + " ".join(missing)

    pinned = clean(authored.get("pinnedComment", "")) or cta
    social = clean(authored.get("social", ""))
    if not social:
        social = "\n\n".join(p for p in [hook or claim, cta, " ".join(hashtags)] if p)

    freebie = clean(authored.get("freebie", ""))
    if not freebie:
        cands = sorted(episode_dir.glob("freebie*.md"))
        freebie = cands[0].name if cands else ""
    freebie_path = f"../{freebie}" if freebie else ""

    video_rel = f"papercut/out/{ep.get('out', 'episode')}.mp4"
    video_abs = project / "out" / f"{ep.get('out', 'episode')}.mp4"
    info = probe_video(video_abs)
    if not info:
        plan = read_json(project / "src" / "plan.json", {}) or {}
        info = {
            "durationSec": round((plan.get("durationInFrames", 0) or 0) / (plan.get("fps", 30) or 30), 2),
            "resolution": "1080x1920",
            "fps": plan.get("fps", 30),
        }

    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "platform": "youtube",
        "format": "short",
        "episode": episode_dir.name,
        "video": video_rel,
        "durationSec": info.get("durationSec", 0),
        "resolution": info.get("resolution", "1080x1920"),
        "fps": info.get("fps", 30),
        "title": title,
        "titleOptions": title_options,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "hashtagsByPlatform": hashtags_by_platform,
        "keywords": keywords,
        "keyword": keyword,
        "cta": cta,
        "pinnedComment": pinned,
        "thumbnail": "seo/thumbnail.png",
        "subtitles": "seo/subtitles.vtt",
        "freebie": freebie,
        "freebiePath": freebie_path,
        "sources": sources,
        "generatedBy": "library/tools/seo.py",
        "generatedAt": now,
    }

    files = [
        "seo/README.md", "seo/title.txt", "seo/title-options.txt", "seo/description.md",
        "seo/tags.txt", "seo/hashtags.txt", "seo/pinned-comment.txt", "seo/social-caption.md",
        "seo/subtitles.vtt", "seo/metadata.json", "seo/manifest.json", "seo/thumbnail.png",
    ]
    warnings = []
    if not captions:
        warnings.append("public/vo/captions.json ausente: sem subtitles.vtt")
    if not video_abs.exists():
        warnings.append(f"{video_rel} ausente: thumbnail e duração vieram do plano")
    if not authored:
        warnings.append("seo.json ausente: usando fallback do BRIEF/roteiro")

    summary = {
        "episode": episode_dir.name,
        "out": str(out_dir),
        "title": title,
        "titleLength": len(title),
        "tags": len(tags),
        "tagsLength": len(",".join(tags)),
        "hashtags": hashtags,
        "durationSec": meta["durationSec"],
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"episode: {episode_dir.name}")
        print(f"title:   {title}  ({len(title)}/100)")
        print(f"tags:    {len(tags)} tags, {len(','.join(tags))}/500 chars")
        print(f"hashtags:{' '.join(hashtags)}")
        print(f"video:   {video_rel}  {meta['durationSec']}s  {meta['resolution']}")
        for w in warnings:
            print(f"warning: {w}")
    if args.dry_run:
        return 0

    # ---------- write ----------
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "title.txt").write_text(title + "\n", encoding="utf-8")
    (out_dir / "title-options.txt").write_text("\n".join(title_options) + "\n", encoding="utf-8")
    (out_dir / "description.md").write_text(description + "\n", encoding="utf-8")
    (out_dir / "tags.txt").write_text(", ".join(tags) + "\n", encoding="utf-8")
    (out_dir / "hashtags.txt").write_text(" ".join(hashtags) + "\n", encoding="utf-8")
    (out_dir / "pinned-comment.txt").write_text(pinned + "\n", encoding="utf-8")
    (out_dir / "social-caption.md").write_text(social + "\n", encoding="utf-8")
    write_vtt(captions, out_dir / "subtitles.vtt")
    if not args.no_thumb:
        ok = make_thumb(video_abs, out_dir / "thumbnail.png")
        if not ok:
            warnings.append("thumbnail.png não gerado (mp4 ausente ou ffmpeg falhou)")
    meta["thumbnail"] = "seo/thumbnail.png" if (out_dir / "thumbnail.png").exists() else ""
    meta["subtitles"] = "seo/subtitles.vtt" if (out_dir / "subtitles.vtt").exists() else ""
    json.dump(meta, open(out_dir / "metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    readme = f"""# Kit SEO — {episode_dir.name}

> Gerado por `library/tools/seo.py`. O `papercut-explainer` termina no MP4; este kit é a etapa de publicação.

## Arquivos

| Arquivo | Uso |
|---|---|
| `title.txt` | Título escolhido ({len(title)}/100 caracteres). |
| `title-options.txt` | Opções de título para teste A/B. |
| `description.md` | Descrição do YouTube, com fatos, CTA, fontes e hashtags. |
| `tags.txt` | Tags separadas por vírgula ({len(','.join(tags))}/500 caracteres). |
| `hashtags.txt` | Hashtags principais. |
| `metadata.json` | Tudo estruturado, incluindo hashtags por plataforma. |
| `pinned-comment.txt` | Comentário fixado com a palavra-chave `{keyword}`. |
| `social-caption.md` | Legenda curta para Instagram/TikTok. |
| `subtitles.vtt` | Legendas em VTT, geradas do tempo real da voz. |
| `thumbnail.png` | Capa 1080x1920 tirada do frame 0. |
| `manifest.json` | Lista de arquivos e limites conferidos. |

## Onde colar

### YouTube Shorts
- **Título:** `title.txt`
- **Descrição:** `description.md`
- **Tags:** `tags.txt`
- **Hashtags:** já estão no fim da descrição; `hashtags.txt` é a lista limpa.
- **Legendas:** `subtitles.vtt`
- **Thumb:** `thumbnail.png`
- **Comentário fixado:** `pinned-comment.txt`

### Instagram Reels / TikTok
- **Legenda:** `social-caption.md`
- **Hashtags extras:** `metadata.json` → `hashtagsByPlatform.instagram` / `.tiktok`
- **Vídeo:** `{video_rel}`

## Limites conferidos

- Título: {len(title)}/100 caracteres.
- Tags: {len(','.join(tags))}/500 caracteres.
- Duração: {meta['durationSec']} s.
- Resolução: {meta['resolution']}, {meta['fps']} fps.

## Freebie

{f'Prometido no CTA: `{freebie}`.' if freebie else 'Nenhum freebie encontrado; o CTA é genérico.'}

## Fonte dos textos

{('Autoral: `papercut/seo.json`.' if authored else 'Fallback do BRIEF/roteiro (crie `papercut/seo.json` para copy autoral).')}
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    manifest = {
        "episode": episode_dir.name,
        "video": video_rel,
        "files": files,
        "titleLength": len(title),
        "tagsLength": len(",".join(tags)),
        "hashtags": len(hashtags),
        "durationSec": meta["durationSec"],
        "resolution": meta["resolution"],
        "fps": meta["fps"],
        "source": "seo.json" if authored else "fallback",
        "warnings": warnings,
        "generatedBy": "library/tools/seo.py",
        "generatedAt": now,
    }
    json.dump(manifest, open(out_dir / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"seo kit -> {out_dir}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
