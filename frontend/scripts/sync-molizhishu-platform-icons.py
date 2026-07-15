import urllib.request
from pathlib import Path

out = Path(r"d:\py代码\GEO优化\frontend\public\platform-icons")
out.mkdir(parents=True, exist_ok=True)
base = "https://doc.molizhishu.com/images/svg"

# molizhishu asset -> our local filenames (used by platformMeta)
mapping = {
    "deepseek-color.svg": ["deepseek.svg"],
    "doubao-color.svg": ["doubao.svg", "doubao.png"],  # keep png path working: write svg also as doubao used; update meta to svg
    "yuanbao-color.svg": ["yuanbao.svg"],
    "kimi-color.svg": ["kimi.svg", "kimi.png"],
    "qwen-color.svg": ["qianwen.svg"],
    "quark-color.svg": ["quark.svg", "quark.png"],
    "baidu-color.svg": ["baiduai.svg"],
    "weibo-color.svg": ["weibo_zhisou.svg"],
    "antafu-color.svg": ["antafu.svg"],
}

ua = {"User-Agent": "Mozilla/5.0 GEO-Monitor-icon-sync"}
for remote, locals_ in mapping.items():
    url = f"{base}/{remote}"
    req = urllib.request.Request(url, headers=ua)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    for name in locals_:
        # always write svg content; for .png targets write sibling .svg and also save as .svg named
        if name.endswith(".png"):
            # save svg with code name; don't overwrite png with svg bytes wrongly for browsers expecting png
            # only ensure matching .svg exists
            svg_name = name.replace(".png", ".svg")
            (out / svg_name).write_bytes(data)
            print("wrote", svg_name, len(data), "from", remote)
        else:
            (out / name).write_bytes(data)
            print("wrote", name, len(data), "from", remote)

print("files:", sorted(p.name for p in out.iterdir()))
