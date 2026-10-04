"""Fetch the law corpus from official sources into data/corpus/ and write manifest.csv.

  .venv/bin/python scripts/build_corpus.py            # fetch what is missing, keep what exists
  .venv/bin/python scripts/build_corpus.py --force    # refetch everything

Only official government hosts are used (state legislatures, city sites, official municipal-code hosts).
When an official host is unreachable from this network (malegislature.gov and pub.njleg.state.nj.us
time out from Europe), the Internet Archive's copy of the same official page is used and the manifest
records the archive URL. HTML is reduced to its main text; PDFs go through pdftotext. Text is kept
as retrieved (curly quotes, section signs) because rules quote it verbatim.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import subprocess
import sys
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "corpus"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36 homerule-corpus/0.1"
TODAY = date.today().isoformat()
LEG = "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode={code}&sectionNum={sec}"
BILL = "https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id={bid}"

# doc_id, title, kind, state, county, city, citation, url, status_hint
TARGETS = [
    ("doc_001", "California Civil Code section 1947.12 (Tenant Protection Act rent cap, AB 1482)", "statute", "CA", "", "", "Cal. Civ. Code § 1947.12", LEG.format(code="CIV", sec="1947.12"), ""),
    ("doc_002", "California Civil Code section 1946.2 (just cause eviction, AB 1482)", "statute", "CA", "", "", "Cal. Civ. Code § 1946.2", LEG.format(code="CIV", sec="1946.2"), ""),
    ("doc_003", "California Civil Code section 1950.5 (security deposits, as amended by AB 12)", "statute", "CA", "", "", "Cal. Civ. Code § 1950.5", LEG.format(code="CIV", sec="1950.5"), ""),
    ("doc_004", "California Civil Code section 1950.6 (application screening fee)", "statute", "CA", "", "", "Cal. Civ. Code § 1950.6", LEG.format(code="CIV", sec="1950.6"), ""),
    ("doc_005", "California Government Code section 12955 (FEHA housing discrimination, source of income)", "statute", "CA", "", "", "Cal. Gov. Code § 12955", LEG.format(code="GOV", sec="12955"), ""),
    ("doc_006", "California Government Code section 12927 (FEHA definitions, source of income)", "statute", "CA", "", "", "Cal. Gov. Code § 12927", LEG.format(code="GOV", sec="12927"), ""),
    ("doc_007", "California Civil Code section 1954.52 (Costa-Hawkins Rental Housing Act)", "statute", "CA", "", "", "Cal. Civ. Code § 1954.52", LEG.format(code="CIV", sec="1954.52"), ""),
    ("doc_008", "California Civil Code section 1954.53 (Costa-Hawkins Rental Housing Act)", "statute", "CA", "", "", "Cal. Civ. Code § 1954.53", LEG.format(code="CIV", sec="1954.53"), ""),
    ("doc_009", "California AB 325 (2025-2026), common pricing algorithms, chaptered bill text", "bill", "CA", "", "", "Cal. AB 325 (2025-2026 Reg. Sess.), Stats. 2025", BILL.format(bid="202520260AB325"), ""),
    ("doc_010", "California SB 763 (2025-2026), Cartwright Act penalties, chaptered bill text", "bill", "CA", "", "", "Cal. SB 763 (2025-2026 Reg. Sess.), Stats. 2025", BILL.format(bid="202520260SB763"), ""),
    ("doc_011", "California Business and Professions Code section 16756.1 (common pricing algorithms)", "statute", "CA", "", "", "Cal. Bus. & Prof. Code § 16756.1", LEG.format(code="BPC", sec="16756.1"), ""),
    ("doc_012", "California Business and Professions Code section 16755 (Cartwright Act penalties)", "statute", "CA", "", "", "Cal. Bus. & Prof. Code § 16755", LEG.format(code="BPC", sec="16755"), ""),
    ("doc_013", "Los Angeles Rent Stabilization Ordinance, LAMC Chapter XV Article 1 (copy hosted by LA City Planning)", "ordinance", "CA", "Los Angeles", "Los Angeles", "L.A. Mun. Code § 151.00 et seq.", "https://planning.lacity.gov/eir/CrossroadsHwd/deir/files/references/J203.pdf", ""),
    ("doc_014", "San Francisco Residential Rent Stabilization and Arbitration Ordinance, Administrative Code Chapter 37 (Rent Board edition, 11-24-2024)", "ordinance", "CA", "San Francisco", "San Francisco", "S.F. Admin. Code ch. 37", "https://media.api.sf.gov/documents/600_Ordinance_11-24-24.pdf", ""),
    ("doc_015", "San Francisco Administrative Code section 37.10C (use and sale of algorithmic devices prohibited; sliced from the Chapter 37 PDF)", "ordinance", "CA", "San Francisco", "San Francisco", "S.F. Admin. Code § 37.10C", "https://media.api.sf.gov/documents/600_Ordinance_11-24-24.pdf", ""),
    ("doc_016", "San Diego Municipal Code Chapter 9 Article 8 Division 11, sections 98.1101-98.1104 (algorithmic rental pricing)", "ordinance", "CA", "San Diego", "San Diego", "San Diego Mun. Code §§ 98.1101-98.1104", "https://docs.sandiego.gov/municode/MuniCodeChapter09/Ch09Art08Division11.pdf", ""),
    ("doc_017", "Berkeley Rent Stabilization and Eviction for Good Cause Ordinance, BMC Chapter 13.76", "ordinance", "CA", "Alameda", "Berkeley", "Berkeley Mun. Code ch. 13.76", "https://rentboard.berkeleyca.gov/sites/default/files/documents/Rent%20Stabilization%20Ordinance_BMC%20Chapter%2013.76.pdf", ""),
    ("doc_018", "Berkeley Ordinance 7,956-N.S. adding BMC Chapter 13.63 (prohibition on pricing algorithms to set rents)", "ordinance", "CA", "Alameda", "Berkeley", "Berkeley Mun. Code ch. 13.63 (Ord. 7,956-N.S.)", "https://berkeleyca.gov/sites/default/files/documents/2025-03-25%20Item%2002%20Ordinance%207956.pdf", ""),
    ("doc_019", "Berkeley Ordinance 7,974-N.S. amending BMC Chapter 13.63 (coordinated pricing algorithms)", "ordinance", "CA", "Alameda", "Berkeley", "Berkeley Mun. Code ch. 13.63 (Ord. 7,974-N.S.)", "https://berkeleyca.gov/sites/default/files/documents/2025-07-08%20Item%2001%20Amendments%20to%20Ordinance%20Prohibiting.pdf", ""),
    ("doc_020", "Santa Ana Rent Stabilization and Just Cause Eviction Ordinance, Municipal Code Chapter 8 Article XIX", "ordinance", "CA", "Orange", "Santa Ana", "Santa Ana Mun. Code ch. 8, art. XIX (§§ 8-3100 et seq.)", "https://library.municode.com/ca/santa_ana/codes/code_of_ordinances?nodeId=PTIITHCO_CH8BUST_ARTXIXRESTJUCAEVOR", ""),
    ("doc_021", "Santa Ana Prohibition of Anti-Competitive Automated Rent Price-Fixing, Municipal Code Chapter 8 Article XXIV (Ordinance NS-3090)", "ordinance", "CA", "Orange", "Santa Ana", "Santa Ana Mun. Code ch. 8, art. XXIV (Ord. NS-3090)", "https://library.municode.com/ca/santa_ana/codes/code_of_ordinances?nodeId=PTIITHCO_CH8BUST_ARTXXIVPRANMPAUREPRXI", ""),
    ("doc_022", "N.J.S.A. 2A:18-61.1 et seq., Anti-Eviction Act (NJ Department of Community Affairs copy)", "statute", "NJ", "", "", "N.J.S.A. 2A:18-61.1", "https://www.nj.gov/dca/codes/codreg/pdf_regs/2A_18_61.pdf", ""),
    ("doc_023", "N.J.S.A. 46:8-19 through 46:8-26, Security Deposit Law including 46:8-21.2 (NJ DCA copy)", "statute", "NJ", "", "", "N.J.S.A. 46:8-21.2", "https://www.nj.gov/dca/codes/publications/pdf_lti/sdepsit_law.pdf", ""),
    ("doc_024", "N.J.S.A. 46:8-52 et seq., Fair Chance in Housing Act, P.L.2021, c.110 (NJ Attorney General copy)", "statute", "NJ", "", "", "N.J.S.A. 46:8-52 to 46:8-64", "https://www.njoag.gov/wp-content/uploads/2021/12/Fair-Chance-in-Housing-Act_NJSA-46-8-52-et-seq.pdf", ""),
    ("doc_025", "New Jersey P.L.2025, c.405 (rental application fee cap)", "statute", "NJ", "", "", "P.L.2025, c.405", "https://pub.njleg.state.nj.us/Bills/2024/PL25/405_.HTM", ""),
    ("doc_026", "New Jersey FAIR Act, P.L.2026, c.43 (algorithmic rent pricing)", "statute", "NJ", "", "", "P.L.2026, c.43", "https://pub.njleg.state.nj.us/Bills/2026/PL26/43_.HTM", ""),
    ("doc_028", "Jersey City Ordinance 25-057 adding Code section 218-12, Preventing Algorithmic Rent-Fixing in the Rental Housing Market", "ordinance", "NJ", "Hudson", "Jersey City", "Jersey City Code § 218-12 (Ord. 25-057)", "https://cityofjerseycity.civicweb.net/document/429156/", ""),
    ("doc_029", "Hoboken Code Chapter 155, Rent Control", "ordinance", "NJ", "Hudson", "Hoboken", "Hoboken Code ch. 155", "https://ecode360.com/15252438", ""),
    ("doc_030", "Hoboken Code Chapter 158, Rent Increases (algorithmic rent pricing)", "ordinance", "NJ", "Hudson", "Hoboken", "Hoboken Code ch. 158", "https://ecode360.com/15252579", ""),
    ("doc_031", "Newark Rent Control Ordinance, Revised General Ordinances Title XIX Chapter 2, certified ordinance 6PSF-a 09/05/2017", "ordinance", "NJ", "Essex", "Newark", "Newark Rev. Gen. Ord. tit. XIX, ch. 2 (§ 19:2-1 et seq.)", "https://www.newarknj.gov/DocumentCenter/View/1020/Rent-Control-Certified-Ordinance-6PSF-a-090517-PDF", ""),
    ("doc_032", "Newark Rent Control Ordinance amendment, certified ordinance 09/11/2018", "ordinance", "NJ", "Essex", "Newark", "Newark Rev. Gen. Ord. tit. XIX, ch. 2 (2018 amendment)", "https://www.newarknj.gov/DocumentCenter/View/1021/Rent-Control-Certified-Ordinance-091118-PDF", ""),
    ("doc_033", "Massachusetts General Laws Chapter 40P, Massachusetts Rent Control Prohibition Act", "statute", "MA", "", "", "Mass. Gen. Laws ch. 40P", "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleVII/Chapter40P", ""),
    ("doc_034", "Massachusetts General Laws Chapter 186 Section 15B (security deposits, upfront charges)", "statute", "MA", "", "", "Mass. Gen. Laws ch. 186, § 15B", "https://malegislature.gov/Laws/GeneralLaws/PartII/TitleI/Chapter186/Section15B", ""),
    ("doc_035", "Massachusetts General Laws Chapter 112 Section 87DDD 1/2 (broker fees)", "statute", "MA", "", "", "Mass. Gen. Laws ch. 112, § 87DDD½", "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXVI/Chapter112/Section87DDD1~2", ""),
    ("doc_036", "Massachusetts Senate Bill S.2983 (194th General Court), algorithmic rent pricing, bill text", "bill", "MA", "", "", "Mass. S.2983 (194th Gen. Ct.)", "https://malegislature.gov/Bills/194/S2983.pdf", "pending"),
    ("doc_037", "Massachusetts House Bill H.5222 (194th General Court), algorithmic rent pricing, bill text", "bill", "MA", "", "", "Mass. H.5222 (194th Gen. Ct.)", "https://malegislature.gov/Bills/194/H5222.pdf", "pending"),
]
# A word the fetched text must contain, to catch a capture of the wrong page.
EXPECT = {"doc_030": "algorithm", "doc_029": "rent control", "doc_036": "algorithm", "doc_037": "algorithm", "doc_033": "rent control", "doc_034": "security deposit"}
# Hosts that time out from this network: use the Internet Archive's copy of the official page.
ARCHIVE_HOSTS = ("malegislature.gov", "pub.njleg.state.nj.us", "ecode360.com", "library.municode.com")
FIELDS = ["doc_id", "title", "kind", "state", "county", "city", "citation", "url", "retrieval_date", "file", "status", "status_hint", "source_note"]


class Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article", "blockquote", "pre", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    # leginfo pages carry the statute in a known container; keep only that when present
    m = re.search(r'<div[^>]+id="(?:codeLawSectionContent|manylawsections|bill_all|content_main)"[^>]*>(.*)', raw, re.S)
    if m:
        raw = m.group(1)
    p = Text()
    p.feed(raw)
    t = "".join(p.out)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # leginfo.legislature.ca.gov: the statute follows the "Code Text" line, a bill follows "Date Published:"
    for marker in (r"\nCode Text\n", r"\nDate Published:[^\n]*\n"):
        m2 = re.search(marker, t)
        if m2:
            t = t[m2.end():]
            break
    return t.strip()


def pdf_to_text(data: bytes, tmp: Path) -> str:
    tmp.write_bytes(data)
    r = subprocess.run(["pdftotext", "-enc", "UTF-8", str(tmp), "-"], capture_output=True, text=True, timeout=120)
    t = r.stdout.replace("\f", "\n\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fetch(client: httpx.Client, url: str, tries: int = 6) -> tuple[bytes, str, str]:
    """Returns (content, content_type, fetched_url)."""
    last = ""
    for i in range(tries):
        try:
            r = client.get(url, timeout=50)
            if r.status_code == 200 and len(r.content) > 500:
                return r.content, r.headers.get("content-type", ""), url
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):
                break
        except httpx.HTTPError as e:
            last = type(e).__name__
        time.sleep(3 + 3 * i)
    raise RuntimeError(last or "no content")


def fetch_archive(client: httpx.Client, url: str) -> tuple[bytes, str, str]:
    """Latest Internet Archive capture of the official page (raw, id_ flag)."""
    for i in range(5):
        try:
            a = client.get("https://archive.org/wayback/available", params={"url": url}, timeout=50)
            if a.status_code == 429:
                time.sleep(20 + 15 * i)
                continue
            snap = (a.json().get("archived_snapshots") or {}).get("closest") or {}
            if not snap.get("available"):
                raise RuntimeError("no archive capture")
            ts = snap["timestamp"]
            raw_url = f"https://web.archive.org/web/{ts}id_/{url}"
            r = client.get(raw_url, timeout=60)
            if r.status_code == 429:
                time.sleep(20 + 15 * i)
                continue
            if r.status_code == 200 and len(r.content) > 500:
                return r.content, r.headers.get("content-type", ""), raw_url
            raise RuntimeError(f"archive HTTP {r.status_code}")
        except httpx.HTTPError as e:
            time.sleep(10)
            last = type(e).__name__
    raise RuntimeError("archive unavailable")


def looks_like_law(text: str, doc_id: str = "") -> bool:
    if len(text) < 800 or re.search(r"(access denied|too many requests|page not found|enable javascript)", text[:3000], re.I):
        return False
    want = EXPECT.get(doc_id)
    return bool(re.search(want, text, re.I)) if want else True


def ocr_pdf(data: bytes, tmp: Path) -> str:
    """Scanned PDF: rasterise with pdftoppm and read with tesseract (page by page)."""
    tmp.write_bytes(data)
    workdir = tmp.parent / ".ocr"
    workdir.mkdir(exist_ok=True)
    for old in workdir.glob("*"):
        old.unlink()
    subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", str(tmp), str(workdir / "p")], check=True, timeout=600)
    pages = []
    for png in sorted(workdir.glob("p-*.png")):
        r = subprocess.run(["tesseract", str(png), "-", "--psm", "6"], capture_output=True, text=True, timeout=300)
        pages.append(r.stdout)
        png.unlink()
    workdir.rmdir()
    t = "\n\n".join(pages)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", action="append")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    existing = {}
    mp = OUT / "manifest.csv"
    if mp.exists():
        with mp.open(newline="", encoding="utf-8") as f:
            existing = {r["doc_id"]: r for r in csv.DictReader(f)}
    rows = []
    tmp = OUT / ".tmp.pdf"
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, follow_redirects=True) as client:
        for doc_id, title, kind, state, county, city, citation, url, hint in TARGETS:
            if a.only and doc_id not in a.only:
                if doc_id in existing:
                    rows.append(existing[doc_id])
                continue
            fname = f"{doc_id}.txt"
            prev = existing.get(doc_id)
            if not a.force and prev and prev.get("status") == "ok" and (OUT / fname).exists():
                rows.append({**prev, "file": fname})
                print(f"{doc_id} kept")
                continue
            row = {"doc_id": doc_id, "title": title, "kind": kind, "state": state, "county": county, "city": city, "citation": citation,
                   "url": url, "retrieval_date": TODAY, "file": "", "status": "unreachable", "status_hint": hint, "source_note": ""}
            text, note = "", ""
            try:
                try:
                    data, ctype, fetched = fetch(client, url, tries=2 if any(h in url for h in ARCHIVE_HOSTS) else 6)
                except RuntimeError as e:
                    if any(h in url for h in ARCHIVE_HOSTS):
                        data, ctype, fetched = fetch_archive(client, url)
                        note = f"official host unreachable from the build network ({e}); Internet Archive copy of the official page: {fetched}"
                    else:
                        raise
                if data[:5] == b"%PDF-" or "pdf" in ctype:
                    text = pdf_to_text(data, tmp)
                    if len(text) < 300:
                        text = ocr_pdf(data, tmp)
                        note = (note + "; " if note else "") + "scanned PDF read with tesseract OCR; quotes are OCR text"
                else:
                    text = html_to_text(data.decode("utf-8", errors="replace"))
                if not looks_like_law(text, doc_id):
                    raise RuntimeError(f"content does not look like statute text ({len(text)} chars)")
                header = f"# {title} | {citation} | {url} | retrieved {TODAY}\n\n"
                (OUT / fname).write_text(header + text + "\n", encoding="utf-8")
                row.update({"file": fname, "status": "ok", "source_note": note})
                print(f"{doc_id} ok {len(text)} chars" + (" (archive)" if note else ""))
            except Exception as e:  # noqa: BLE001
                row["source_note"] = str(e)[:160]
                print(f"{doc_id} unreachable: {e}")
            rows.append(row)
            time.sleep(1.5)
    tmp.unlink(missing_ok=True)
    with mp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"{ok}/{len(rows)} documents ok -> {mp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
