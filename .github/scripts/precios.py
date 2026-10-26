#!/usr/bin/env python3
"""
Precios de Trick or Trade para GotchaDex (se ejecuta una vez al día en GitHub).

- Cardmarket (euros): su guía de precios y su catálogo, los archivos públicos de su página «Data».
- TCGplayer (dólares): a través de tcgcsv.com, que copia cada día los datos de TCGplayer.

La app no llama a esas webs: lee el archivo pequeño que deja este script (precios/trickortrade.json).
También deja precios/diagnostico.json para ver qué se ha encontrado.
"""
import json, re, sys, time, unicodedata, urllib.request, datetime

UA = {"User-Agent": "GotchaDex/3.7 (+https://github.com/M4RDR1Z/GotchaDex)"}
CM_PRODUCTS = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json"
CM_GUIDE = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
TCGCSV = "https://tcgcsv.com/tcgplayer/3"  # 3 = Pokémon


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def key(s):
    """«Mimikyu ex (Trick or Trade)» -> «mimikyuex»"""
    s = re.sub(r"\s*[\[(].*$", "", str(s or ""))
    s = unicodedata.normalize("NFD", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def num(s):
    m = re.match(r"\D*0*(\d+)", str(s or ""))
    return int(m.group(1)) if m else None


def r2(x):
    return round(float(x), 2) if isinstance(x, (int, float)) and x > 0 else None


data = json.load(open("precios/tot-cartas.json"))
# año -> [(código de la app, nombre, número original)]
cards = {y: [(f"{abbr} {int(n):03d}", name, int(n)) for name, abbr, n in rows] for y, rows in data["editions"].items()}
out = {"updated": datetime.date.today().isoformat(), "cards": {f"tot{y}": {} for y in cards}}
diag = {"tcgplayer": {}, "cardmarket": {}}

# ---------------- TCGplayer (tcgcsv) ----------------
try:
    groups = [g for g in get(f"{TCGCSV}/groups")["results"] if "trick or trade" in g["name"].lower()]
    diag["tcgplayer"]["groups"] = [{"id": g["groupId"], "name": g["name"]} for g in groups]
    for g in groups:
        y = next((yy for yy in cards if yy in g["name"]), "2022")
        time.sleep(0.2)
        products = get(f"{TCGCSV}/{g['groupId']}/products")["results"]
        time.sleep(0.2)
        prices = get(f"{TCGCSV}/{g['groupId']}/prices")["results"]
        by_prod = {}
        for p in prices:
            by_prod.setdefault(p["productId"], []).append(p)
        found, missing = 0, []
        for code, name, n in cards[y]:
            cands = [p for p in products if key(p.get("name")) == key(name)]
            if len(cands) > 1:
                same = [p for p in cands if num(next((e["value"] for e in p.get("extendedData", []) if e["name"] == "Number"), None)) == n]
                cands = same or cands[:1]
            if not cands:
                missing.append(name)
                continue
            rows = by_prod.get(cands[0]["productId"], [])
            base = next((r for r in rows if r.get("subTypeName") == "Normal"), None) or next((r for r in rows if r.get("subTypeName") == "Holofoil"), None) or (rows[0] if rows else None)
            if not base:
                missing.append(name)
                continue
            tp = {"market": r2(base.get("marketPrice")) or r2(base.get("midPrice")), "low": r2(base.get("lowPrice")), "id": cands[0]["productId"]}
            out["cards"][f"tot{y}"].setdefault(code, {})["tp"] = tp
            found += 1
        diag["tcgplayer"][g["name"]] = {"year": y, "products": len(products), "found": found, "missing": missing}
except Exception as e:
    diag["tcgplayer"]["error"] = repr(e)

# ---------------- Cardmarket ----------------
try:
    products = get(CM_PRODUCTS)["products"]
    guide = get(CM_GUIDE)
    by_id = {g["idProduct"]: g for g in guide["priceGuides"]}
    diag["cardmarket"]["guideDate"] = guide.get("createdAt")
    by_exp = {}
    for p in products:
        by_exp.setdefault(p.get("idExpansion"), []).append(p)
    for y, rows in cards.items():
        names = {key(name) for _, name, _ in rows}
        # la expansión de Cardmarket de ese año: unas 30 cartas y casi todas con nombres de la lista
        cands = []
        for exp, ps in by_exp.items():
            if not 20 <= len(ps) <= 60:
                continue
            hit = sum(1 for p in ps if key(p["name"]) in names)
            if hit >= 15:
                dates = sorted(str(p.get("dateAdded", "")) for p in ps)
                cands.append({"idExpansion": exp, "size": len(ps), "matches": hit, "added": dates[0][:10] if dates else None,
                              "sample": [p["name"] for p in ps[:6]]})
        # del año correcto: añadidas ese año (salen en septiembre u octubre)
        cands.sort(key=lambda c: (str(c["added"] or "").startswith(y), c["matches"] / c["size"]), reverse=True)
        diag["cardmarket"][y] = cands[:5]
        if not cands or not str(cands[0]["added"] or "").startswith(y):
            continue
        ps = by_exp[cands[0]["idExpansion"]]
        for code, name, n in rows:
            same = sorted([p for p in ps if key(p["name"]) == key(name)], key=lambda p: p["idProduct"])
            if not same:
                continue
            g = by_id.get(same[0]["idProduct"])
            if not g:
                continue
            cm = {"trend": r2(g.get("trend")), "avg30": r2(g.get("avg30")), "low": r2(g.get("low")),
                  "trendHolo": r2(g.get("trend-holo")), "avg30Holo": r2(g.get("avg30-holo")), "id": same[0]["idProduct"]}
            out["cards"][f"tot{y}"].setdefault(code, {})["cm"] = cm
except Exception as e:
    diag["cardmarket"]["error"] = repr(e)

json.dump(out, open("precios/trickortrade.json", "w"), ensure_ascii=False, indent=1)
json.dump(diag, open("precios/diagnostico.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({y: len(v) for y, v in out["cards"].items()}))
