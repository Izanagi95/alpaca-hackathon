# Checklist pre-competizione — Options Alpha Agents Hackathon

Finestra ufficiale di scoring: **lunedì 31/8 9:30 ET → venerdì 4/9 9:30 ET**
(equity misurata a EOD giovedì 3/9).

## 🔴 Da fare — bloccante, prima di lunedì mattina

### 1. Creare il nuovo account paper ufficiale
- Nuovo account Alpaca paper, $100.000, **diverso** da quello usato finora per i test.
- Puoi usare la stessa email (confermato dalle FAQ ufficiali).
- Farlo con qualche giorno di anticipo va bene — puoi crearlo anche subito, l'importante è **non farlo tradare** prima di lunedì 9:30 ET.

### 2. Verificare il nuovo account (senza tradare)
Una volta creato, con le SUE chiavi (temporaneamente, solo per verifica):
```powershell
.\.venv\Scripts\python.exe scripts\integration_check.py
```
Conferma account attivo, dati di mercato raggiungibili. Poi rimetti le chiavi vecchie finché non è davvero lunedì.

### 3. Pulire il journal prima del cambio account
`options_alpha.db` contiene ancora i trade di test (dry-run) sul vecchio account, considerati "posizioni aperte" dal Risk Engine (controllo `duplicate_exposure`/`portfolio_risk`). Vanno azzerati perché il nuovo account parte a zero posizioni reali:
- **Locale**: cancellare `options_alpha.db` (o rinominarlo come backup) prima del primo run con le nuove chiavi.
- **GitHub Actions**: la cache che persiste il DB tra le run va invalidata — cambiare la chiave di cache in `.github/workflows/agent.yml` (es. `options-alpha-db-v2-...`) oppure cancellare le cache esistenti da Settings → Actions → Caches sul repo.

### 4. Sostituire le credenziali — SOLO da lunedì 9:30 ET in poi
Non prima (le regole dicono esplicitamente che i trade fatti prima non contano, e va usato solo l'account ufficiale per lo scoring).

**Locale (`.env`)**:
```
ALPACA_API_KEY=<nuova chiave>
ALPACA_SECRET_KEY=<nuovo secret>
DRY_RUN=false
```

**GitHub Secrets** (repo `Izanagi95/alpaca-hackathon`):
```powershell
gh secret set ALPACA_API_KEY --repo Izanagi95/alpaca-hackathon --body "<nuova chiave>"
gh secret set ALPACA_SECRET_KEY --repo Izanagi95/alpaca-hackathon --body "<nuovo secret>"
gh variable set DRY_RUN --repo Izanagi95/alpaca-hackathon --body "false"
```

⚠️ **`DRY_RUN=false` è essenziale**: finché resta `true`, l'agente valuta e giornala tutto ma non invia mai un ordine reale — l'equity resterebbe fissa a $100.000 per tutta la settimana.

### 5. Primo test con l'account ufficiale
Appena il mercato apre lunedì, verifica manualmente (non aspettare solo il cron):
```powershell
gh workflow run "Options Alpha Agent" --repo Izanagi95/alpaca-hackathon
```
Controlla i log per confermare che scan/monitor partano davvero (non più "skipped") e che eventuali ordini vadano a buon fine.

## 🟡 Da verificare — non bloccante ma importante

- **cron-job.org**: conferma che il job sia attivo e schedulato ogni 5 minuti (l'abbiamo già validato, ma vale un controllo il giorno prima).
- **Submission**: verifica sulla pagina lablab.ai/Alpaca se serve compilare un form con link al repo/demo entro una scadenza specifica — non è un'informazione che ho io, va controllata direttamente.
- **Repo pubblico o privato**: le regole permettono di restare privati durante l'hackathon — se serve renderlo pubblico per la submission, va fatto solo dopo aver verificato che non ci siano segreti nella storia dei commit (già verificato: `.env` non è mai stato committato).

## ⚪ Facoltativo, se c'è tempo

- Rifinire `docs/WRITEUP.md` con i numeri reali del backtest simulato e la lezione imparata sul cron di GitHub (buona storia da raccontare ai giudici: problema reale trovato e risolto).
- Un secondo giro di `scripts/run_simulated_backtest.py` con dati più recenti prima della demo finale.
- Registrare la demo (`docs/DEMO_SCRIPT.md`) con l'account ufficiale già in esecuzione, per mostrare dati reali invece che di test.

## Promemoria

Il giudizio non è solo P&L — pesano anche creatività, autonomia e robustezza del workflow. Quello che abbiamo costruito e verificato (Risk Engine come unico gate, bug reali trovati testando dal vivo, MCP integrato, backtest onestamente etichettato) resta un punto di forza indipendentemente da come si comporta il mercato in una settimana.
