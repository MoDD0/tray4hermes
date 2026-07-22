# tray4hermes (česky)

> **Jazyk:** [English](../README.md) · **[Čeština](README.cs.md)**

Toto je český překlad README. Primární (anglická) verze je v
[`../README.md`](../README.md). Obsah je stejný, jen přeložený.
Pokud najdeš rozpor, **anglická verze je autoritativní**.

Českou verzi udržujeme proto, že původní autor je čech a psát
v rodném jazyce je pohodlnější. Pokud bys chtěl českou verzi
aktualizovat, commity jsou vždy v anglické verzi; cz verze se
překládá z angličtiny.

---

## Proč to vzniklo

Hermes Agent je šikovný kus softwaru, ale jeho `hermes-gateway` běží
jako **`systemd --user` service** — to znamená, že se ti defaultně
spustí při loginu a zůstane běžet na pozadí, i když ho zrovna
nepotřebuješ. Trochu jako Slack, Discord nebo Telegram na Windows —
ty běží taky furt, ale mají **iconku v systray**, aby ses mohl
rozhodnout, jestli je chceš mít aktivní, nebo je na chvíli umrtvit.

Hermes tohle (zatím) nemá. Přišlo mi to škoda, a tak vznikl
**tray4hermes** — malý Python tray, který:

- **ukazuje stav gateway** přímo v KDE liště (zelená/oranžová/červená),
- **umožňuje Start / Stop / Restart** bez nutnosti otevírat terminál,
- **přepíná profily** (`default`, `work`, `off`…) z menu,
- **zobrazuje logy** v docela vyladěném vieweru (barevné levely,
  filtry, hledání, traceback-aware, time-window),
- a hlavně — **nesnaží se být chytřejší než samotný Hermes**. Jen
  pozoruje, občas klikne, a mluví přes standardní `systemctl`.

Pokud ti tedy vyhovuje filozofie "Hermes běží jen když chci, a já vidím
co se děje" — tohle je pro tebe.

> ⚠️ **Disclaimer:** tray4hermes is a *passive convenience addon*, not
> an official Hermes Agent component. Hermes Agent runs perfectly
> fine without it. Use it if you like it; ignore it if you don't.

---

## Features

- 📊 **Live status icon** v system trayi (🟢 active, 🟠 warming,
  🔵 activating, ⚫ inactive, 🔴 failed, ⚪ unknown)
- ▶️ **Start / Stop / Restart** of `hermes-gateway.service` z jednoho kliku
- 🔄 **Profile switcher** submenu, driven by `~/.hermes/profiles/`
- 📋 **Log viewer** — *see below*, je to docela vyladěné
- ⚙️ **Open Hermes config** v default editoru
- 💻 **Launch Hermes CLI** v novém terminálu

### Log viewer

`~/.hermes/logs/gateway.log` je často obrovský soubor plný tracebacků,
který je potřeba *rychle* projít, ne číst od shora dolů. Proto viewer
nabízí:

- **Barevné log levely**: `DEBUG` šedá, `INFO` bílá, `WARNING` žlutá,
  `ERROR` červená, `CRITICAL` červená + celořádkový highlight
- **Line number gutter** jako Qt Creator/VS Code
- **Filtry per level** (toggle na toolbaru) — vidíš jen to, co chceš
- **TRACEBACK toggle** — zvláštní kategorie pro stack trace; můžeš je
  vypnout a vidět jen zprávy, nebo naopak
- **Time-window filter** (Vše / 5m / 15m / 1h / 6h / 24h) — vidíš
  jen logy z poslední hodiny apod.
- **Reverse order** (Obrátit) — přepne na `journalctl` styl
  (nejnovější nahoře)
- **Max řádků** spinbox — rolling buffer (0 = unlimited)
- **Search** (`Ctrl+F` → `F3` next, `Shift+F3` prev, `Esc` close)
- **Auto-scroll toggle** (default ON; OFF = zachová pozici při refresh)
- **Word-wrap toggle**
- **Copy / Clear / Refresh** akce
- **Settings dialog** (font size, max lines, per-level visibility, …)
- **Persisted** — všechna nastavení se ukládají do
  `~/.config/tray4hermes/state.json`

![Log viewer demo](images/log_viewer.png)

UI toolbaru je v češtině (`Max řádků`, `Hledat`, `Nastavení`…), protože
původní vývojář je čech. Pokud bys chtěl anglickou lokalizaci,
podívej se na [Roadmap → Localization](../README.md#roadmap-next-up-ideas).

---

## Architektura / požadavky / podpora platforem

Vše důležité je v anglické verzi:

- [Architecture](../README.md#architecture)
- [Requirements](../README.md#requirements)
- [Platform support](../README.md#platform-support) — včetně
  kompletního průvodce pro Ubuntu a vysvětlení, proč Manjaro KDE
  je primární platforma
- [Installation](../README.md#installation)
- [Security](../README.md#security)
- [Development](../README.md#development)
- [Project layout](../README.md#project-layout)
- [Contributing](../README.md#contributing)
- [Roadmap](../README.md#roadmap-next-up-ideas)
- [Credits](../README.md#credits--thanks)

Pokud je v anglické verzi něco nejasného a rád bys to v češtině,
napiš issue a přidáme CZ objasnění sem.

---

## Licence

MIT — viz [LICENSE](../LICENSE).

## Hosting a mirror

Primární host je **GitHub** (https://github.com/MoDD0/tray4hermes), kde
se vyvíjí, řeší issues a přijímají PR. Forgejo
(https://forgejo.he1.co/HERMbuddy/tray4hermes) je **read-only mirror** —
tam prosím neotvírej issues ani PR.

Detaily viz anglická verze: [Hosting & mirror](../README.md#hosting--mirror).

---

## Jak přispět (krátká poznámka)

Detailní pokyny pro PR najdeš v anglické verzi:
[Contributing](../README.md#contributing).

Krátce: nezlom testy, nepřidávej runtime závislosti bez diskuze, žádné
tajné klíče v diffu, nic nepiš do `~/.hermes/*` (to je owned Hermes
Agent), zůstaň u MIT licence.
