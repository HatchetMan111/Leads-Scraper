# LeadScraper + Sales Team — Proxmox LXC Installer + Web UI

Lokale Lead-Recherche für **Consulting-Firmen (DACH)** als **LXC-Container auf Proxmox VE**
im Stil der [Proxmox VE Community Scripts](https://community-scripts.github.io/ProxmoxVE/):
**Einzeiler auf dem Host → Container + App + Web UI + systemd läuft.**

Der komplette Fachinhalt aus deinen Dokumenten ist eingearbeitet:
- **5-Fragen-Nischen-Framework** (Schmerz, Kaufkraft, Auffindbarkeit, Wachstum, eigener Vorteil)
- **Business-ICP Consulting-Firmen** (8–25 MA, inhabergeführt, Strategie/IT-Digital/Ops)
- **Buyer-Hypothese** (KI-Lücke = Glaubwürdigkeits-/Statusproblem)
- **7 Signale S1–S7** nach Hook-Priorität (KI-Stellen, KI-Gap, Partner/Zert., Events, Wachstum, Budget-Timing, Regulierung)
- **A/B/C-Bewertung** (datierte Trigger schlagen Merkmale; ehrliches C > erfundenes A)
- **Ausschlusskriterien E1–E7** (u. a. Recruiting-Fehlklassifikation sauber markieren)
- **Austauschbares ICP-System**: Code kennt nur `icp/SCHEMA.md`, Zielgruppe steht in
  `icp/consulting-dach.yaml`/`.json` → neue Nische = neue Datei, kein Code-Umbau.
  Architektur: **Discovery → Qualification → Enrichment** (Places nur Discovery).

| Feld | Wert |
|---|---|
| App-Name | `leadscraper` |
| Zweck | Consulting-Leads recherchieren, A/B/C qualifizieren, Sales-Pipeline fahren |
| Tech-Stack | Python 3 **stdlib only** (kein pip, kein Cloud) + SQLite + Vanilla-JS |
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

Danach vollautomatisch:
1. Debian-12-Template sicherstellen (`pveam download` falls nötig)
2. `pct create` + `onboot: 1` + Start
3. App-Dateien per `pct push` (Tarball) in den Container
4. `install/setup-container.sh` im Container: Pakete, `py_compile`-Check,
   ICP-JSON-Check, systemd-Unit `leadscraper.service`
   (`enable`, `Restart=always`, `After=network-online.target`)
5. Selbst-Verifikation: `systemctl is-active` + HTTP-Check auf `localhost:8080/healthz`

**Erwartete Ausgabe (Ende):**

```text
[6/7] Verifikation: HTTP-Check auf localhost:8080 ...
{"status": "ok", "db": "ok", "icp": "consulting-dach.json", "version": "1.0.0"}
  - Web UI antwortet.
[7/7] Fertig. URL: http://<LXC-IP>:8080 (Bind 0.0.0.0, onboot: 1 hostseitig)
==================================================================
 ✅ Fertig! LeadScraper Web UI: http://192.168.1.60:8080
    CT-ID 160 (leadscraper), onboot=1, Service=leadscraper
==================================================================
```

Web UI öffnen → **Leads** anlegen/CSV importieren → auto **A/B/C + Score + Hook** →
**Sales-Pipeline** (neu → qualifiziert → angereichert → kontaktiert → Termin → Kunde).

## 2 · Update / mehrere Instanzen

Jeder Installer-Lauf erstellt einen **neuen** Container (belegte ID → nächste freie).
Update im **bestehenden** Container (z. B. neues ICP-Profil einspielen):

```bash
pct push 160 icp/consulting-dach.json /opt/leadscraper/icp/consulting-dach.json
pct exec 160 -- bash /opt/leadscraper/install/setup-container.sh
# danach in der UI: "Alle neu bewerten"
```

Neue Nische ohne Code-Umbau: `icp/neue-nische.yaml` + `.json` nach
`icp/SCHEMA.md` anlegen, als `ICP_FILE` setzen (systemd-Env), Service neu starten.

## 3 · Deinstallation

```bash
pct stop 160 && pct destroy 160
```

## 4 · Reboot-Test (Nachweis Reboot-Sicherheit)

```bash
pct reboot 160
sleep 20
pct exec 160 -- systemctl is-active leadscraper   # -> active
curl -fsS http://<LXC-IP>:8080/healthz            # -> {"status":"ok",...}
# Web UI im Browser neu laden -> wieder erreichbar
```

Container startet durch `onboot: 1` nach Host-Reboot automatisch;
die Web UI durch `systemctl enable` + `Restart=always`.

## 5 · Debugging (volle Fehlerkette)

- Installer mit Trace: `DEBUG=1 bash -x install/leadscraper.sh`
- Setup im Container: `DEBUG=1 bash -x /opt/leadscraper/install/setup-container.sh`
- Service-Logs: `pct exec 160 -- journalctl -u leadscraper -f`
- App-Fehler: API antwortet mit **vollständigem Traceback** (Exception-Chain),
  nie nur letzte Zeile; Installer-`fail()` druckt Exit-Code, Befehl, Zeile,
  Funktions-Stack + `pct status`-Auszug.

## 6 · Repo-Struktur

```text
install/leadscraper.sh       Host-Installer (Einzeiler, Community-Scripts-Stil)
install/setup-container.sh   Setup IM Container (idempotent, set -euo pipefail)
app/app.py                   Recherche-Engine (Discovery/Qualification/Enrichment, stdlib)
app/static/index.html        Web UI (Dashboard, Leads, Pipeline, ICP, Outreach — kein CDN)
icp/consulting-dach.yaml     Austauschbares ICP-Profil (Quelle, menschenlesbar)
icp/consulting-dach.json     Maschinenspiegel (wird geladen, kein YAML-Dep nötig)
icp/SCHEMA.md                Profil-Schema + Anleitung für neue Nischen
systemd/leadscraper.service  systemd-Unit (enable, Restart=always)
.env.example                 PORT / DB_PATH / ICP_FILE
```

## 7 · Hinweise

- **LXC vs. VM:** Standard ist LXC (reicht locker: stdlib + SQLite).
  VM nur nötig, wenn du später hungrige Enrichment-Worker (Browser-Crawling,
  Embeddings) mit viel RAM willst — App läuft dort unverändert (Debian 12).
- **Google Places:** dient nur der Discovery. Ob ein Lead passt, entscheidet
  immer das aktive ICP-Profil in der Qualification. Ohne API-Key: CSV-Import
  oder manuelle Anlage nutzen.
- **Ehrliches C:** kein Signal erfinden — lieber C parken als A faken.
