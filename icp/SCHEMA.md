# ICP-Profil-Schema (Version 1.0)

Der Code (`app/app.py`) kennt **nur dieses Schema**. Alle Zielgruppen-Details
stehen in der ICP-Datei (z. B. `icp/consulting-dach.yaml` + `.json`).

## Neue Nische anlegen

1. `icp/consulting-dach.yaml` kopieren → z. B. `icp/zahnaerzte-dach.yaml`
2. Felder anpassen (siehe unten), `.json`-Spiegel aktualisieren
   (inhaltsgleich, wird von der App ohne YAML-Dependency geladen)
3. App mit `ICP_FILE=/opt/leadscraper/icp/zahnaerzte-dach.json` starten
   (systemd: `Environment=ICP_FILE=...` oder `/etc/leadscraper.env`)
4. Kein Code-Umbau nötig. Discovery → Qualification → Enrichment bleiben getrennt.

## Pflichtfelder

| Feld | Typ | Bedeutung |
|---|---|---|
| `icp_name` | string | Eindeutiger Profil-Name (Dateiname ohne Endung) |
| `version` | string | Profil-Version |
| `region` | string | z. B. `DACH (DE, AT, CH)` |
| `zielgruppe.beschreibung` | string | Wer wird gesucht |
| `zielgruppe.mitarbeiter_min/max` | int | Größenkorridor |
| `zielgruppe.inhabergefuehrt_pflicht` | bool | z. B. `true` bei Consulting |
| `consulting_arten` / äquivalent | list | Akzeptierte Unterkategorien (Name frei, Liste Pflicht) |
| `buyer_hypothese` | string | Zentraler Pain in 2–4 Sätzen |
| `signale[]` | list | Mind. 1 Signal; jedes: `id`, `name`, `prioritaet` (1 = wichtigste), `gewicht` (0–100), `typ` (`datiert`/`merkmal`/`verstaerker`/`datiert_oder_merkmal`), `beschreibung` |
| `bewertung.A/B/C` | object | A = datierter Trigger (mit `trigger_mindestens_eins`), B = Merkmal ohne Datum, C = keine Evidenz; je mit `score_range` |
| `ausschlusskriterien[]` | list | Jedes: `id`, `regel` |
| `oekonomie` | string | Optional, z. B. „Brief kostet mehr als Recherche“ |
| `nische_framework_5_fragen[]` | list | Optional, 5 Fragen (Schmerz, Kaufkraft, Auffindbarkeit, Wachstum, eigener Vorteil) |
| `outreach_hinweise` | object | Optional, Personalisierungs-Hooks |

## Scoring-Vertrag (Engine-seitig)

- **Excluded** wenn irgendein `ausschlusskriterien`-Treffer vom Nutzer markiert
  (`excluded_reason` gesetzt) → Klasse `X`, Score 0.
- **A** wenn mind. ein datierter Trigger mit Datum+Nachweis vorliegt
  (S1 mit URL+Datum, S4 mit Event-Datum, S3 neu mit Datum, S5 Welle mit Datum).
- **B** wenn ICP-Kern passt (Größe im Korridor, inhabergeführt, passende Art,
  KI-Gap) aber kein datierter Trigger.
- **C** sonst. Regel: ehrliches C > erfundenes A.
- Score = Summe Signal-Gewichte (gecappt 0–100), A floor 80, B 50–79, C 0–49.

## Discovery / Qualification / Enrichment

- **Discovery** findet Kandidaten (Google Places, OSM, CSV-Import, manuell).
  Liefert nur Rohdaten (Name, Adresse, Website).
- **Qualification** bewertet anhand des geladenen Profils (dieses Schema).
- **Enrichment** (Stellen-URL, Event-Datum, Notizen, Hooks) nur für A/B.
