#!/usr/bin/env python3
"""LeadScraper + Sales Team — lokale Lead-Recherche-Engine (nur stdlib).

Architektur (strikt getrennt):
  Discovery     -> Kandidaten finden (CSV-Import, manuell, Places-Platzhalter).
  Qualification -> anhand ICP-Profil (icp/*.json, Schema icp/SCHEMA.md) A/B/C + Score.
  Enrichment    -> nur für A/B (Stellen-URL, Event-Datum, Notizen, Hooks).

Keine externen Cloud-Dienste, keine pip-Dependencies. SQLite + http.server.
"""
import csv
import html
import io
import json
import os
import re
import sqlite3
import traceback
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "leadscraper"
VERSION = "1.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # /opt/leadscraper/app
APP_ROOT = os.path.dirname(BASE_DIR)                           # /opt/leadscraper
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", os.environ.get("WEB_PORT", "8080")))
DB_PATH = os.environ.get("DB_PATH", "/var/lib/leadscraper/leads.db")
ICP_FILE = os.environ.get(
    "ICP_FILE",
    os.path.join(APP_ROOT, "icp", "consulting-dach.json"),
)
# Fallback für lokale Entwicklung aus dem Repo heraus:
if not os.path.exists(ICP_FILE):
    alt = os.path.join(os.path.dirname(APP_ROOT), "icp", "consulting-dach.json")
    alt2 = "/tmp/opencode/leadscraper-proxmox/icp/consulting-dach.json"
    for cand in (alt, alt2, os.path.join(os.getcwd(), "icp", "consulting-dach.json")):
        if os.path.exists(cand):
            ICP_FILE = cand
            break

PIPELINE_STAGES = ["neu", "qualifiziert", "angereichert", "kontaktiert", "termin", "kunde", "abgelehnt"]

ICP_CACHE = {"mtime": 0, "data": None, "path": None}


def load_icp(path=ICP_FILE):
    """Lädt das ICP-Profil (JSON). Nur generisches Schema wird vorausgesetzt."""
    global ICP_CACHE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"icp_name": "unbekannt", "signale": [], "bewertung": {}, "zielgruppe": {}}
    if ICP_CACHE["data"] is not None and ICP_CACHE["mtime"] == mtime and ICP_CACHE["path"] == path:
        return ICP_CACHE["data"]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ICP_CACHE = {"mtime": mtime, "data": data, "path": path}
    return data


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS leads (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, website TEXT DEFAULT '', stadt TEXT DEFAULT '',
          mitarbeiter INTEGER DEFAULT 0, inhabergefuehrt INTEGER DEFAULT 0,
          beratungsart TEXT DEFAULT '',
          s1_job INTEGER DEFAULT 0, s1_titel TEXT DEFAULT '', s1_datum TEXT DEFAULT '', s1_url TEXT DEFAULT '',
          s2_portfolio TEXT DEFAULT 'unbekannt',
          s3_partner INTEGER DEFAULT 0, s3_detail TEXT DEFAULT '', s3_datum TEXT DEFAULT '',
          s4_event INTEGER DEFAULT 0, s4_detail TEXT DEFAULT '', s4_datum TEXT DEFAULT '',
          s5_wachstum INTEGER DEFAULT 0, s5_detail TEXT DEFAULT '',
          s6_timing INTEGER DEFAULT 0, s7_regulierung INTEGER DEFAULT 0,
          excluded_reason TEXT DEFAULT '', notizen TEXT DEFAULT '',
          klasse TEXT DEFAULT 'C', score INTEGER DEFAULT 0,
          stage TEXT DEFAULT 'neu', hook TEXT DEFAULT '',
          created_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''
        )"""
    )
    return con


def qualify(lead):
    """Generische A/B/C-Logik anhand des geladenen ICP-Profils.

    Datierte Ereignisse schlagen allgemeine Eigenschaften.
    Gibt (klasse, score, hook, begruendung) zurück.
    """
    icp = load_icp()
    gew = {s.get("id"): int(s.get("gewicht", 0)) for s in icp.get("signale", [])}
    g = lambda sid: gew.get(sid, 0)  # noqa: E731
    z = icp.get("zielgruppe", {}) or {}
    try:
        lo, hi = int(z.get("mitarbeiter_min", 8)), int(z.get("mitarbeiter_max", 25))
    except (TypeError, ValueError):
        lo, hi = 8, 25

    def b(v):
        return bool(v) and str(v) not in ("0", "False", "false", "")

    reasons = []
    score = 0

    # --- Ausschluss (X) ---
    if (lead.get("excluded_reason") or "").strip():
        return "X", 0, "", "Ausgeschlossen: " + lead["excluded_reason"].strip()
    try:
        ma = int(lead.get("mitarbeiter") or 0)
    except (TypeError, ValueError):
        ma = 0
    if ma and ma < 5:
        return "X", 0, "", "Ausgeschlossen E1: < 5 Mitarbeitende."
    if (lead.get("s2_portfolio") or "") == "starke_ki_praxis":
        return "X", 0, "", "Ausgeschlossen E4: etablierte eigene KI-Praxis."
    if b(lead.get("excluded_flag")):
        return "X", 0, "", "Ausgeschlossen (manuell markiert)."

    # --- Signale einsammeln ---
    datierte_trigger = []
    if b(lead.get("s1_job")) and (lead.get("s1_titel") or lead.get("s1_url")) and lead.get("s1_datum"):
        score += g("S1")
        datierte_trigger.append("S1 KI-Stelle")
        reasons.append(f"S1: {lead.get('s1_titel','')} ({lead.get('s1_datum','')})")
    if b(lead.get("s4_event")) and lead.get("s4_datum"):
        score += g("S4")
        datierte_trigger.append("S4 Event")
        reasons.append(f"S4: {lead.get('s4_detail','Event')} ({lead.get('s4_datum','')})")
    if b(lead.get("s3_partner")) and lead.get("s3_datum"):
        score += g("S3")
        datierte_trigger.append("S3 Partner/Zert.")
        reasons.append(f"S3: {lead.get('s3_detail','')} ({lead.get('s3_datum','')})")
    elif b(lead.get("s3_partner")):
        score += g("S3") // 2
        reasons.append("S3: Partner vorhanden (ohne Datum)")
    if b(lead.get("s5_wachstum")):
        score += g("S5")
        reasons.append("S5: Wachstum/Hiring")
    portfolio = (lead.get("s2_portfolio") or "unbekannt")
    if portfolio in ("kein_ki", "buzzwords"):
        score += g("S2")
        reasons.append("S2: KI-Lücke (" + portfolio + ")")
    if b(lead.get("s6_timing")):
        score += g("S6")
        reasons.append("S6: Budget-Timing")
    if b(lead.get("s7_regulierung")):
        score += g("S7")
        reasons.append("S7: Regulatorik")

    # ICP-Kernpassung (für B)
    kern = []
    if lo <= ma <= hi:
        kern.append(f"{ma} MA im Korridor {lo}-{hi}")
    if b(lead.get("inhabergefuehrt")):
        kern.append("inhabergeführt")
    if (lead.get("beratungsart") or "").strip():
        kern.append(str(lead.get("beratungsart")).strip())
    if portfolio in ("kein_ki", "buzzwords"):
        kern.append("KI-Gap")

    score = max(0, min(100, score))
    hook_parts = [r for r in reasons if r.startswith(("S1", "S4", "S3"))][:2]
    hook = "; ".join(hook_parts)

    if datierte_trigger:
        score = max(score, 80)
        return "A", score, hook, "A — datierter Trigger: " + ", ".join(datierte_trigger)
    if len(kern) >= 2:
        score = max(50, min(score, 79)) if score < 50 else min(score, 79)
        if score < 50:
            score = 55
        return "B", score, hook, "B — passt (" + ", ".join(kern) + "), aber ohne datierten Trigger."
    return "C", score, hook, "C — keine individuelle Evidenz (" + (", ".join(kern) if kern else "Kern passt nicht") + "). Ehrliches C > erfundenes A."


# ------------------------------ HTTP-Layer ---------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "LeadScraper/1.0"

    def log_message(self, fmt, *args):  # über stdout/journald
        print(f"{self.address_string()} {fmt % args}")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        ln = int(self.headers.get("Content-Length") or 0)
        if not ln:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            p = u.path
            if p in ("/", "/index.html"):
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if p.startswith("/static/"):
                return self._serve_static(p[len("/static/"):], None)
            if p == "/healthz":
                ok = True
                detail = "ok"
                try:
                    con = db()
                    con.execute("SELECT 1").fetchone()
                    con.close()
                except Exception as e:  # volle Kette im Log, kurze Antwort
                    ok, detail = False, str(e)[:200]
                    traceback.print_exc()
                return self._json({"status": "ok" if ok else "error", "db": detail,
                                   "icp": os.path.basename(ICP_FILE), "version": VERSION},
                                  200 if ok else 500)
            if p == "/api/icp":
                icp = load_icp()
                raw_yaml = ""
                ypath = ICP_FILE[:-5] + ".yaml" if ICP_FILE.endswith(".json") else ICP_FILE
                try:
                    with open(ypath, encoding="utf-8") as f:
                        raw_yaml = f.read()
                except OSError:
                    pass
                return self._json({"profile": icp, "yaml": raw_yaml, "file": os.path.basename(ICP_FILE)})
            if p == "/api/stats":
                return self._json(self._stats())
            if p == "/api/leads":
                qs = urllib.parse.parse_qs(u.query)
                return self._json(self._list_leads(qs))
            if p.startswith("/api/leads/"):
                lid = int(p.rsplit("/", 1)[1])
                return self._json(self._get_lead(lid))
            self._json({"error": "not found"}, 404)
        except Exception:
            traceback.print_exc()  # komplette Kette, nie nur letzte Zeile
            self._json({"error": "interner Fehler", "trace": traceback.format_exc()[-4000:]}, 500)

    def do_POST(self):
        try:
            u = urllib.parse.urlparse(self.path)
            p = u.path
            data = self._read_json()
            if p == "/api/leads":
                return self._json(self._upsert_lead(data))
            if p == "/api/import-csv":
                return self._json(self._import_csv(data.get("csv", "")))
            if p == "/api/score-all":
                return self._json(self._score_all())
            self._json({"error": "not found"}, 404)
        except Exception:
            traceback.print_exc()
            self._json({"error": "interner Fehler", "trace": traceback.format_exc()[-4000:]}, 500)

    def do_PUT(self):
        try:
            lid = int(urllib.parse.urlparse(self.path).path.rsplit("/", 1)[1])
            data = self._read_json()
            data["id"] = lid
            return self._json(self._upsert_lead(data))
        except Exception:
            traceback.print_exc()
            self._json({"error": "interner Fehler", "trace": traceback.format_exc()[-4000:]}, 500)

    def do_DELETE(self):
        try:
            lid = int(urllib.parse.urlparse(self.path).path.rsplit("/", 1)[1])
            con = db()
            cur = con.execute("DELETE FROM leads WHERE id=?", (lid,))
            con.commit()
            con.close()
            return self._json({"deleted": cur.rowcount})
        except Exception:
            traceback.print_exc()
            self._json({"error": "interner Fehler", "trace": traceback.format_exc()[-4000:]}, 500)

    # --- Handler-Helfer ---
    def _serve_static(self, name, ctype):
        safe = os.path.normpath(name).lstrip("/")
        fpath = os.path.join(STATIC_DIR, safe)
        if not fpath.startswith(STATIC_DIR) or not os.path.isfile(fpath):
            self._json({"error": "not found"}, 404)
            return
        if ctype is None:
            ctype = "text/html; charset=utf-8" if safe.endswith(".html") else \
                "application/javascript" if safe.endswith(".js") else \
                "text/css" if safe.endswith(".css") else "application/octet-stream"
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _row_to_dict(self, r):
        return dict(r) if r is not None else None

    def _list_leads(self, qs):
        con = db()
        q = "SELECT * FROM leads"
        clauses, params = [], []
        if qs.get("klasse", [""])[0] in ("A", "B", "C", "X"):
            clauses.append("klasse=?")
            params.append(qs["klasse"][0])
        if qs.get("stage", [""])[0] in PIPELINE_STAGES:
            clauses.append("stage=?")
            params.append(qs["stage"][0])
        if qs.get("q", [""])[0]:
            clauses.append("(name LIKE ? OR stadt LIKE ? OR website LIKE ?)")
            like = "%" + qs["q"][0] + "%"
            params += [like, like, like]
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY score DESC, updated_at DESC LIMIT 1000"
        rows = [self._row_to_dict(r) for r in con.execute(q, params).fetchall()]
        con.close()
        return {"leads": rows, "count": len(rows)}

    def _get_lead(self, lid):
        con = db()
        r = con.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        con.close()
        if r is None:
            return {"error": "not found"}
        return self._row_to_dict(r)

    def _upsert_lead(self, d):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fields = ["name", "website", "stadt", "mitarbeiter", "inhabergefuehrt", "beratungsart",
                  "s1_job", "s1_titel", "s1_datum", "s1_url", "s2_portfolio",
                  "s3_partner", "s3_detail", "s3_datum", "s4_event", "s4_detail", "s4_datum",
                  "s5_wachstum", "s5_detail", "s6_timing", "s7_regulierung",
                  "excluded_reason", "notizen", "stage"]
        clean = {}
        for f in fields:
            v = d.get(f, "")
            if f == "mitarbeiter":
                try:
                    v = int(v or 0)
                except (ValueError, TypeError):
                    v = 0
            elif f in ("s1_job", "s3_partner", "s4_event", "s5_wachstum",
                       "s6_timing", "s7_regulierung", "inhabergefuehrt"):
                if v is True or str(v).strip().lower() in ("1", "true", "ja", "yes", "on"):
                    v = 1
                else:
                    try:
                        v = 1 if int(v) != 0 else 0
                    except (ValueError, TypeError):
                        v = 0
            else:
                v = str(v or "").strip()
            clean[f] = v
        if not clean["name"]:
            return {"error": "Name ist Pflicht."}
        if clean["stage"] not in PIPELINE_STAGES:
            clean["stage"] = "neu"
        klasse, score, hook, begr = qualify(clean)
        clean["klasse"], clean["score"], clean["hook"] = klasse, score, hook
        clean["notizen"] = (clean.get("notizen") or "")
        con = db()
        if d.get("id"):
            clean["updated_at"] = now
            cols = ", ".join(f"{k}=?" for k in list(clean) + ["klasse", "score", "hook", "updated_at"])
            con.execute(f"UPDATE leads SET {cols} WHERE id=?",
                        list(clean.values()) + [klasse, score, hook, now, int(d["id"])])
            lid = int(d["id"])
        else:
            clean["created_at"], clean["updated_at"] = now, now
            cols = list(clean) + ["klasse", "score", "hook", "created_at", "updated_at"]
            cur = con.execute(f"INSERT INTO leads ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                              list(clean.values()) + [klasse, score, hook, now, now])
            lid = cur.lastrowid
        con.commit()
        r = con.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        con.close()
        out = self._row_to_dict(r)
        out["begruendung"] = begr
        return out

    def _import_csv(self, text):
        """Discovery-Import: Name,Website,Stadt,Mitarbeiter pro Zeile (Header optional)."""
        if not text.strip():
            return {"error": "Leeres CSV."}
        reader = csv.DictReader(io.StringIO(text)) if "name" in text.splitlines()[0].lower() else None
        n = 0
        errors = []
        con = db()
        try:
            if reader is None:
                for i, line in enumerate(text.splitlines(), 1):
                    parts = [p.strip() for p in line.split(",")]
                    if not parts or not parts[0]:
                        continue
                    lead = {"name": parts[0], "website": parts[1] if len(parts) > 1 else "",
                            "stadt": parts[2] if len(parts) > 2 else "", "mitarbeiter": parts[3] if len(parts) > 3 else 0}
                    try:
                        self._insert_direct(con, lead)
                        n += 1
                    except Exception as e:
                        errors.append(f"Zeile {i}: {e}")
            else:
                for i, row in enumerate(reader, 2):
                    lname = row.get("name") or row.get("Name") or ""
                    if not lname.strip():
                        errors.append(f"Zeile {i}: Name fehlt")
                        continue
                    lead = {"name": lname.strip(), "website": (row.get("website") or row.get("Website") or "").strip(),
                            "stadt": (row.get("stadt") or row.get("Stadt") or "").strip(),
                            "mitarbeiter": (row.get("mitarbeiter") or row.get("Mitarbeiter") or 0)}
                    try:
                        self._insert_direct(con, lead)
                        n += 1
                    except Exception as e:
                        errors.append(f"Zeile {i}: {e}\n{traceback.format_exc(limit=3)}")
            con.commit()
        finally:
            con.close()
        return {"imported": n, "errors": errors[:20]}

    def _insert_direct(self, con, lead):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        base = {"website": "", "stadt": "", "mitarbeiter": 0, "inhabergefuehrt": 0, "beratungsart": "",
                "s1_job": 0, "s1_titel": "", "s1_datum": "", "s1_url": "", "s2_portfolio": "unbekannt",
                "s3_partner": 0, "s3_detail": "", "s3_datum": "", "s4_event": 0, "s4_detail": "",
                "s4_datum": "", "s5_wachstum": 0, "s5_detail": "", "s6_timing": 0, "s7_regulierung": 0,
                "excluded_reason": "", "notizen": "", "stage": "neu"}
        base.update({k: (str(v).strip() if isinstance(v, str) else v) for k, v in lead.items() if v != ""})
        try:
            base["mitarbeiter"] = int(base.get("mitarbeiter") or 0)
        except (ValueError, TypeError):
            base["mitarbeiter"] = 0
        klasse, score, hook, _ = qualify(base)
        cols = list(base) + ["klasse", "score", "hook", "created_at", "updated_at"]
        con.execute(f"INSERT INTO leads ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                    list(base.values()) + [klasse, score, hook, now, now])

    def _score_all(self):
        con = db()
        rows = con.execute("SELECT * FROM leads").fetchall()
        n = 0
        for r in rows:
            d = dict(r)
            klasse, score, hook, _ = qualify(d)
            con.execute("UPDATE leads SET klasse=?, score=?, hook=?, updated_at=? WHERE id=?",
                        (klasse, score, hook, datetime.now(timezone.utc).isoformat(timespec="seconds"), d["id"]))
            n += 1
        con.commit()
        con.close()
        return {"rescored": n, "icp": os.path.basename(ICP_FILE)}

    def _stats(self):
        con = db()
        total = con.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        by_klasse = {r["klasse"]: r["c"] for r in con.execute("SELECT klasse, COUNT(*) c FROM leads GROUP BY klasse")}
        by_stage = {r["stage"]: r["c"] for r in con.execute("SELECT stage, COUNT(*) c FROM leads GROUP BY stage")}
        top = [dict(r) for r in con.execute("SELECT id,name,klasse,score,stage FROM leads ORDER BY score DESC LIMIT 10")]
        con.close()
        return {"total": total, "by_klasse": by_klasse, "by_stage": by_stage,
                "top": top, "icp": os.path.basename(ICP_FILE), "version": VERSION}


def main():
    icp = load_icp()
    print(f"[{APP_NAME}] v{VERSION} — ICP: {icp.get('icp_name','?')} ({ICP_FILE})", flush=True)
    print(f"[{APP_NAME}] DB: {DB_PATH} — http://0.0.0.0:{PORT}", flush=True)
    db().close()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
