# LeadScraper + Sales Team — Proxmox LXC Installer + Web UI (mit KI)

Lokale Lead-Recherche für **Consulting-Firmen (DACH)** als **LXC-Container auf Proxmox VE**
im Stil der [Proxmox VE Community Scripts](https://community-scripts.github.io/ProxmoxVE/):
**Einzeiler auf dem Host → Container + App + Web UI + systemd läuft.**

Der komplette Fachinhalt aus deinen Dokumenten ist eingearbeitet:
- **5-Fragen-Nischen-Framework** (Schmerz, Kaufkraft, Auffindbarkeit, Wachstum, eigener Vorteil)
- **Business-ICP Consulting-Firmen** (8–25 MA, inhabergeführt, Strategie/IT-Digital/Ops)
- **Buyer-Hypothese** (KI-Lücke = Glaubwürdigkeits-/Statusproblem)
- **7 Signale S1–S7** nach Hook-Priorität, **A/B/C-Bewertung**, **Ausschluss E1–E7**
- **Austauschbares ICP-System**: Code kennt nur `icp/SCHEMA.md`, Zielgruppe steht in
  `icp/consulting-dach.yaml`/`.json` → neue Nische = neue Datei, kein Code-Umbau.
  Architektur: **Discovery → Qualification → Enrichment → Gewinn-Strategie**.

| Feld | Wert |
|---|---|
| App-Name | `leadscraper` (v2.0) |
| Zweck | Leads finden (KI + CSV + manuell), nach A/B/C kategorisieren, anreichern, Gewinn-Strategie pro Lead |
| Tech-Stack | Python 3 **stdlib only** (kein pip) + SQLite + Vanilla-JS; KI via **OpenRouter-API** |
| GitHub-Repo | https://github.com/HatchetMan111/Leads-Scraper |
| Web-UI-Port | `8080` (konfigurierbar) |
| Default-Ressourcen | 2 vCPU · 2048 MB RAM · 8 GB Disk · Debian 12 LXC, `onboot: 1` |

## 1 · Installation (Einzeiler auf dem Proxmox-Host als root)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Leads-Scraper/main/install/leadscraper.sh)"
```

Das Script fragt interaktiv ab (sinnvolle Defaults):
`CT-ID` (160, belegt → **nächste freie** inkl. VM-Check) · Hostname (`leadscraper`,
bei Kollision `-<CTID>` suffixiert) · vCPU (2) · RAM (2048) · Disk (8G) ·
Storage (`local-lvm`) · Bridge (`vmbr0`, DHCP) · Web-Port (8080).

Danach vollautomatisch: Template → `pct create` + `onboot: 1` → App-Dateien per
Tarball-Push → `install/setup-container.sh` (Pakete, `py_compile`, ICP-Check,
systemd-Unit `leadscraper.service` mit `enable`, `Restart=always`) →
Selbst-Verifikation (`systemctl is-active` + HTTP auf `localhost:8080/healthz`).

**Erwartete Ausgabe (Ende):**

```text
 ✅ Fertig! LeadScraper Web UI: http://192.168.1.60:8080
    CT-ID 160 (leadscraper), onboot=1, Service=leadscraper
```

## 2 · Inbetriebnahme: KI einrichten (Pflicht für Discovery & Strategien)

1. Key holen: **openrouter.ai/keys** (Guthaben dort aufladen, Pay-per-Use).
2. Web UI → **⚙️ Einstellungen** → Key einfügen → Speichern.
   Der Key liegt nur auf dem Server (`/var/lib/leadscraper/config.json`, `0600`),
   wird nie vollständig angezeigt oder geloggt.
3. **🤖 Modelle**: Liste lädt live alle ~450 OpenRouter-Modelle (Name, Kontext,
   Preis/M Token) mit Filter → **Wählen** = Standard-Modell (gespeichert, 24h-Cache).
4. **📦 Mein Angebot** im selben Tab beschreiben — das ist die Basis, aus der die
   KI pro Lead die Gewinn-Strategie baut.

## 3 · Workflow: Finden → Kategorisieren → Anreichern → Gewinnen

1. **🔍 KI-Discovery**: Nische + Region + Anzahl eingeben → KI liefert
   Firmenkandidaten **plus Suchaufträge** zur Verifikation. Treffer landen als
   `unverifiziert` — erst prüfen (Google/Maps/LinkedIn), dann Haken setzen.
   Alternativ: CSV-Import oder manuelle Anlage.
2. **🏢 Leads**: S1–S7-Signale eintragen → automatische **A/B/C + Score + Hook**
   nach ICP-Profil (datierte Trigger schlagen Merkmale; ehrliches C > erfundenes A).
3. **🤖 Anreicherung** (pro Lead, Button): Zusammenfassung, Signal-Einschätzung
   mit Verifikations-Hinweisen, Personalisierungs-Hooks, Recherche-Empfehlungen.
   Stage springt automatisch auf `angereichert`.
4. **🏆 Gewinn-Strategie** (pro Lead, braucht dein Angebot aus §2): Win-Chance %,
   Kernargument, Kanal + Timing, **Nachrichtenentwurf**, Einwandbehandlung,
   nächste Schritte. Übersicht im Tab **✉️ Outreach**.
5. **📦 Sales-Pipeline**: neu → qualifiziert → angereichert → kontaktiert →
   Termin → Kunde (Klick = öffnen, Button = weiterziehen).

## 4 · Update / mehrere Instanzen

Jeder Installer-Lauf erstellt einen **neuen** Container (belegte ID → nächste freie).
Update im **bestehenden** Container:

```bash
pct exec 160 -- bash /opt/leadscraper/install/setup-container.sh
# danach in der UI: "Alle neu bewerten"
```

Die SQLite-DB wird automatisch migriert (neue Spalten werden ergänzt, Daten bleiben).
Neue Nische ohne Code-Umbau: `icp/neue-nische.yaml` + `.json` nach `icp/SCHEMA.md`
anlegen, als `ICP_FILE` setzen, Service neu starten.

## 5 · Deinstallation

```bash
pct stop 160 && pct destroy 160
```

## 6 · Reboot-Test (Nachweis Reboot-Sicherheit)

```bash
pct reboot 160
sleep 20
pct exec 160 -- systemctl is-active leadscraper   # -> active
curl -fsS http://<LXC-IP>:8080/healthz            # -> {"status":"ok",...}
```

## 7 · Debugging (volle Fehlerkette)

- Installer mit Trace: `DEBUG=1 bash -x install/leadscraper.sh`
- Setup im Container: `DEBUG=1 bash -x /opt/leadscraper/install/setup-container.sh`
- Service-Logs: `pct exec 160 -- journalctl -u leadscraper -f`
- KI-Fehler (z. B. 401 falscher Key, Rate-Limit): UI zeigt **Fehlermeldung +
  vollständigen Traceback**, Server-Log via journald. Der API-Key erscheint
  niemals in Logs oder API-Antworten (nur `…letzte4`).

## 8 · Repo-Struktur

```text
install/leadscraper.sh       Host-Installer (Einzeiler, Community-Scripts-Stil)
install/setup-container.sh   Setup IM Container (idempotent, set -euo pipefail)
app/app.py                   Engine v2.0: Qualifikation + OpenRouter (Discovery/Enrich/Strategie)
app/static/index.html        Web UI (Dashboard, Discovery, Leads, Pipeline, ICP, Outreach, Einstellungen)
icp/consulting-dach.yaml     Austauschbares ICP-Profil (Quelle, menschenlesbar)
icp/consulting-dach.json     Maschinenspiegel (wird geladen, kein YAML-Dep nötig)
icp/SCHEMA.md                Profil-Schema + Anleitung für neue Nischen
systemd/leadscraper.service  systemd-Unit (enable, Restart=always)
.env.example                 PORT / DB_PATH / ICP_FILE
```

## 9 · Hinweise

- **Kosten:** App/Hosting lokal gratis; nur OpenRouter-Calls kosten je nach Modell
  (Preise stehen in der Modellliste, günstige Modelle ab Bruchteilen von $/M Token).
- **Ehrlichkeit:** KI-Kandidaten sind Vorschläge mit Suchaufträgen, keine Fakten —
  erst verifizieren, dann anschreiben. Kein Signal erfinden.
- **LXC vs. VM:** Standard LXC reicht (stdlib + SQLite). VM nur bei hungrigen
  Zusatz-Workern nötig — App läuft dort unverändert (Debian 12).
