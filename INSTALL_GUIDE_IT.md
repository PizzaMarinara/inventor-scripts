# Guida all'installazione e utilizzo di inventor-scripts su Windows

Questa guida è rivolta agli ingegneri che usano Autodesk Inventor quotidianamente e vogliono automatizzare
l'estrazione di dati, la modifica di parametri e l'interazione con i modelli tramite un agente AI.
Non è richiesta alcuna esperienza di programmazione: si parte da zero, da un PC Windows nuovo.

---

## Indice

1. [Prerequisiti — cosa serve prima di cominciare](#1-prerequisiti--cosa-serve-prima-di-cominciare)
2. [Installazione di Python](#2-installazione-di-python)
3. [Installazione di uv (gestore pacchetti raccomandato)](#3-installazione-di-uv-gestore-pacchetti-raccomandato)
4. [Clonare o scaricare il progetto](#4-clonare-o-scaricare-il-progetto)
5. [Installazione delle dipendenze](#5-installazione-delle-dipendenze)
6. [Configurazione della chiave API](#6-configurazione-della-chiave-api)
7. [Verifica dell'installazione](#7-verifica-dellinstallazione)
8. [Preparare i file Inventor](#8-preparare-i-file-inventor)
9. [Utilizzo — i tre comandi principali](#9-utilizzo--i-tre-comandi-principali)
10. [Consigli pratici per gli ingegneri](#10-consigli-pratici-per-gli-ingegneri)
11. [Risoluzione problemi comuni (Troubleshooting)](#11-risoluzione-problemi-comuni-troubleshooting)
12. [Aggiornare il progetto](#12-aggiornare-il-progetto)

---

## 1. Prerequisiti — cosa serve prima di cominciare

Prima di iniziare, assicurarsi di avere a disposizione quanto segue.

**Software già presente (si assume installato):**

- **Autodesk Inventor** — qualsiasi versione recente supportata da COM (2019 o successiva consigliata).
  Gli script comunicano con Inventor tramite l'interfaccia COM di Windows, pertanto Inventor deve essere
  installato sulla stessa macchina su cui vengono eseguiti gli script.

**Sistema operativo:**

- **Windows 10 o Windows 11 a 64 bit** — gli script usano la libreria `pywin32`, che funziona
  esclusivamente su Windows. Non sono compatibili con macOS o Linux per quanto riguarda
  l'interazione con Inventor (i test di logica pura girano ovunque).

**Connettività:**

- **Connessione Internet** — necessaria per scaricare Python, uv, le dipendenze del progetto e per
  comunicare con l'API di Anthropic (Claude) durante l'uso dell'agente AI.

---

## 2. Installazione di Python

### 2.1 Scaricare Python

Aprire il browser e visitare il sito ufficiale:

```
https://www.python.org/downloads/windows/
```

Scaricare **Python 3.11 o superiore** (ad esempio Python 3.12). Scegliere il file denominato
"Windows installer (64-bit)".

> ⚠️ **IMPORTANTE: non installare Python dal Microsoft Store.** La versione presente nello Store
> di Windows non aggiunge Python correttamente al PATH di sistema, causando errori difficili da
> diagnosticare. Usare sempre l'installer scaricato da python.org.

### 2.2 Eseguire l'installer

1. Fare doppio clic sul file `.exe` scaricato (ad esempio `python-3.12.x-amd64.exe`).
2. Nella **prima schermata** dell'installer, **spuntare obbligatoriamente** la casella
   **"Add python.exe to PATH"** in basso. Questo passaggio è fondamentale.

   ```
   ┌─────────────────────────────────────────────────────────┐
   │  Install Python 3.12.x (64-bit)                         │
   │                                                         │
   │  [●] Install launcher for all users (recommended)       │
   │  [✓] Add python.exe to PATH          <-- SPUNTARE QUI  │
   │                                                         │
   │  [Install Now]   [Customize installation]               │
   └─────────────────────────────────────────────────────────┘
   ```

3. Fare clic su **"Install Now"** per procedere con l'installazione standard (consigliata).
4. Se Windows chiede il permesso di amministratore (UAC), fare clic su **"Sì"**.
5. Al termine, fare clic su **"Close"**.

### 2.3 Verificare l'installazione

Aprire PowerShell:

- Premere **Start** (tasto Windows) → digitare `PowerShell` → premere **Invio**.

Nel terminale digitare:

```powershell
python --version
```

L'output atteso è simile a:

```
Python 3.12.3
```

Se compare il messaggio `python: The term 'python' is not recognized...`, il PATH non è stato
configurato correttamente. Ripetere l'installazione assicurandosi di spuntare "Add python.exe to PATH",
oppure aggiungere il PATH manualmente (vedere la sezione [Troubleshooting](#11-risoluzione-problemi-comuni-troubleshooting)).

Verificare anche pip:

```powershell
pip --version
```

Output atteso:

```
pip 24.x.x from C:\Users\<utente>\AppData\Local\Programs\Python\Python312\Lib\site-packages\pip (python 3.12)
```

---

## 3. Installazione di uv (gestore pacchetti raccomandato)

### 3.1 Cos'è uv e perché usarlo

`uv` è un gestore di pacchetti Python scritto in Rust, sviluppato da Astral. È drasticamente più
veloce di `pip` (10-100x), risolve le dipendenze in modo più affidabile e gestisce gli ambienti
virtuali in modo trasparente. Per questo progetto è lo strumento raccomandato, anche se `pip`
rimane un'alternativa valida.

### 3.2 Installazione tramite PowerShell

Aprire **PowerShell** (non è necessario aprirlo come amministratore) e incollare il seguente
comando:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Il comando scarica e installa `uv` automaticamente. Al termine potrebbe essere necessario
**chiudere e riaprire PowerShell** affinché il comando `uv` sia riconosciuto.

### 3.3 Verifica

```powershell
uv --version
```

Output atteso:

```
uv 0.x.x (...)
```

### 3.4 Alternativa: usare pip invece di uv

Se per qualsiasi motivo `uv` non funziona, tutti i comandi di installazione di questa guida hanno
una variante equivalente con `pip`. Le due varianti sono sempre presentate affiancate nelle sezioni
successive. Non è necessario avere entrambi: uno qualsiasi dei due è sufficiente.

---

## 4. Clonare o scaricare il progetto

Il codice del progetto deve essere presente sulla macchina locale. Ci sono due modalità:

### Opzione A — Clonare con Git (consigliata se si vuole ricevere aggiornamenti facilmente)

**Installazione di Git for Windows** (se non già installato):

1. Andare su `https://git-scm.com/download/win` e scaricare il programma di installazione.
2. Eseguire l'installer con le opzioni predefinite — va bene per quasi tutti i casi d'uso.
3. Verificare l'installazione aprendo PowerShell e digitando:

   ```powershell
   git --version
   ```

   Output atteso: `git version 2.x.x.windows.x`

**Clonare il repository:**

```powershell
git clone https://github.com/pizzamarinara/inventor-scripts.git
cd inventor-scripts
```

### Opzione B — Scaricare lo ZIP da GitHub

1. Aprire il browser e navigare alla pagina GitHub del progetto.
2. Fare clic sul pulsante verde **"Code"**.
3. Selezionare **"Download ZIP"**.
4. Estrarre lo ZIP in una cartella a scelta, ad esempio `C:\Progetti\inventor-scripts\`.

### Aprire PowerShell nella cartella del progetto

Indipendentemente dal metodo scelto, tutti i comandi devono essere eseguiti **dalla cartella radice
del progetto**. Il modo più rapido su Windows:

1. Aprire **Esplora file** e navigare fino alla cartella `inventor-scripts`.
2. Tenere premuto **Shift** e fare clic con il **tasto destro del mouse** su uno spazio vuoto
   nella cartella.
3. Dal menu contestuale scegliere **"Apri finestra PowerShell qui"** (oppure
   "Apri in Terminale" su Windows 11).

In alternativa, aprire PowerShell e spostarsi nella cartella manualmente:

```powershell
cd C:\Progetti\inventor-scripts
```

---

## 5. Installazione delle dipendenze

Con PowerShell aperto nella cartella del progetto, eseguire uno dei seguenti comandi:

**Con uv (consigliato):**

```powershell
uv pip install -e ".[dev]"
```

**Con pip (alternativa):**

```powershell
pip install -e ".[dev]"
```

### Cosa significa `-e ".[dev]"`

- `-e` (modalità "editable"): installa il pacchetto in modalità modificabile. Significa che le
  eventuali modifiche al codice sorgente hanno effetto immediato senza dover reinstallare.
- `.` (punto): installa il pacchetto definito nella cartella corrente (quella che contiene
  `pyproject.toml`).
- `[dev]`: installa anche le dipendenze opzionali del gruppo "dev", che includono gli strumenti
  per l'esecuzione dei test (`pytest`, `pytest-mock`).

### Dipendenze installate

L'installazione scarica automaticamente:

| Pacchetto | Scopo |
|---|---|
| `pywin32` | Interfaccia COM con Autodesk Inventor (solo Windows) |
| `anthropic` | Client per l'API di Claude (agente AI) |
| `typer` | Framework per la CLI |
| `rich` | Output colorato e tabelle nel terminale |
| `pydantic` | Validazione dei dati |
| `python-dotenv` | Lettura del file `.env` con la chiave API |
| `pytest`, `pytest-mock` | Esecuzione dei test (solo gruppo `dev`) |

> ⚠️ **Nota su `pywin32`:** questa libreria funziona solo su Windows. Su macOS o Linux l'installazione
> segnalerà un avviso, ma i test di logica pura continueranno a funzionare normalmente. Su Windows,
> se si riceve un errore durante la prima importazione di `win32com`, vedere la sezione
> [Troubleshooting](#11-risoluzione-problemi-comuni-troubleshooting).

---

## 6. Configurazione della chiave API

Per usare il comando `ask` (agente AI), il sistema ha bisogno di comunicare con Claude.
Esistono due modalità di autenticazione: tramite una chiave API Anthropic dedicata, oppure
tramite Claude Code CLI se già installato sulla macchina.

---

### Opzione A — Chiave API Anthropic (ANTHROPIC_API_KEY)

Questa è la modalità standard: si ottiene una chiave API e la si configura nel progetto.

#### Passo 1: Ottenere la chiave

1. Aprire il browser e andare su `https://console.anthropic.com`.
2. Accedere o creare un account Anthropic.
3. Nel menu laterale scegliere **"API Keys"**.
4. Fare clic su **"Create Key"**, assegnare un nome descrittivo (ad esempio `inventor-scripts`).
5. Copiare la chiave generata — inizia con `sk-ant-`. **Attenzione: viene mostrata una sola volta.**

#### Passo 2: Creare il file `.env`

Nella cartella radice del progetto è presente un file `.env.example`. Copiarlo e rinominarlo in `.env`:

```powershell
copy .env.example .env
```

#### Passo 3: Incollare la chiave

Aprire il file `.env` con un editor di testo (Blocco Note, Notepad++, VS Code, ecc.):

```powershell
notepad .env
```

Il contenuto del file sarà:

```
# Copy this file to .env and fill in your key
ANTHROPIC_API_KEY=sk-ant-...
```

Sostituire `sk-ant-...` con la chiave copiata al Passo 1. Ad esempio:

```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Salvare e chiudere il file.

> ⚠️ **SICUREZZA — non committare mai il file `.env` su Git.** Il file `.env` è già elencato nel
> `.gitignore` del progetto, quindi Git non lo traccerà automaticamente. Non aggiungere mai la
> chiave API a file versionati come `main.py`, `pyproject.toml` o README. Una chiave esposta
> accidentalmente su GitHub va revocata immediatamente dalla console Anthropic.

---

### Opzione B — Claude Code CLI (se già installato)

Se sulla macchina è già installato **Claude Code** (il client CLI ufficiale di Anthropic),
non è necessaria alcuna chiave API separata: l'autenticazione è già gestita dall'installazione
esistente di Claude Code.

#### Verificare se Claude Code è installato

```powershell
claude --version
```

Se il comando restituisce un numero di versione (ad esempio `1.x.x`), Claude Code è disponibile.

#### Usare Claude Code con gli script

In questo caso non occorre una chiave API separata. Per attivare Claude Code CLI:

1. Aprire il file `.env` nella cartella radice del progetto (crearlo da `.env.example` se non esiste ancora).
2. Impostare `CLAUDE_CODE=true`.
3. Con questa impostazione, l'applicazione userà automaticamente Claude Code CLI — nessuna chiave API necessaria.

`CLAUDE_CODE=true` ha sempre la precedenza su `ANTHROPIC_API_KEY`.

```
CLAUDE_CODE=true
```

Per verificare che Claude Code sia funzionante e autenticato, eseguire:

```powershell
claude -p "Ciao, funzioni?"
```

Se Claude risponde, l'autenticazione è attiva e tutto è pronto.

---

## 7. Verifica dell'installazione

Prima di lavorare con i file Inventor, è consigliabile eseguire la suite di test per assicurarsi
che tutto sia installato correttamente.

```powershell
python -m pytest -m "not inventor" -v
```

Il flag `-m "not inventor"` esclude i test che richiedono un'istanza di Inventor attiva
(i test COM), eseguendo solo quelli di logica pura — compatibili con qualsiasi macchina.

**Output atteso (tutti i test verdi):**

```
collected 36 items

tests/test_agent_describe.py::test_describe_part_model PASSED
tests/test_agent_describe.py::test_describe_assembly_model PASSED
tests/test_agent_llm.py::test_llm_client_chat PASSED
...
tests/test_utils.py::test_write_csv PASSED
tests/test_utils.py::test_output_path PASSED

============================== 36 passed in X.XXs ==============================
```

### Se qualcosa fallisce

| Sintomo | Possibile causa | Soluzione |
|---|---|---|
| `ModuleNotFoundError` per un pacchetto | Dipendenza non installata | Rieseguire `uv pip install -e ".[dev]"` |
| `ImportError: win32com` | pywin32 non configurato | Vedere sezione Troubleshooting |
| Errori di sintassi o import da `agent/` | Cartella sbagliata | Assicurarsi di essere nella radice del progetto |

---

## 8. Preparare i file Inventor

### Copiare i file nella cartella di input

Lo script lavora con file `.ipt` (parti), `.iam` (assiemi) e `.ipn` (presentazioni).
Copiare i file su cui si vuole lavorare nella sottocartella `input\` del progetto:

```
inventor-scripts\
├── input\            <-- copiare qui i file .ipt / .iam / .ipn
│   ├── assembly.iam
│   └── componente.ipt
├── output\           <-- creata automaticamente; qui appariranno i risultati
...
```

La cartella `output\` viene creata automaticamente al primo utilizzo, non è necessario crearla
a mano.

### Inventor aperto o chiuso?

Entrambe le situazioni sono gestite automaticamente dagli script:

- **Inventor già aperto:** lo script si collega all'istanza in esecuzione.
- **Inventor chiuso:** lo script lo avvia automaticamente prima di aprire il file richiesto.

In entrambi i casi non è necessario fare nulla di speciale — basta eseguire il comando.

> ⚠️ **I file originali non vengono mai modificati.** Il comando `modify` e l'agente AI salvano
> sempre una copia nel percorso `output\`, lasciando il file originale in `input\` intatto.

---

## 9. Utilizzo — i tre comandi principali

Tutti i comandi si eseguono da PowerShell nella cartella radice del progetto.

---

### 9.1 Estrarre dati da un file

Il comando `extract` legge un file Inventor e ne estrae proprietà, parametri e distinta base (BOM),
salvando i risultati in `output\` e stampando un riepilogo a schermo.

```powershell
# Salva i dati in formato JSON (predefinito)
python main.py extract input\assembly.iam

# Salva i dati in formato CSV
python main.py extract input\assembly.iam --format csv

# Salva sia JSON che CSV
python main.py extract input\assembly.iam --format both
```

**Cosa produce:**

- **File JSON** (`output\assembly_extracted.json`): struttura completa con proprietà del documento,
  tutti i parametri (nome, valore, unità, commento) e la distinta base.
- **File CSV** (`output\assembly_parameters.csv` e/o `output\assembly_bom.csv`): gli stessi dati
  in formato tabellare, apribile direttamente in Excel.
- **Tabella a schermo**: riepilogo immediato di tutti i parametri con nome, valore e unità.

Esempio di output a schermo:

```
                Parameters — assembly.iam
┌─────────────────────┬──────────┬───────┬─────────────────┐
│ Name                │ Value    │ Units │ Comment         │
├─────────────────────┼──────────┼───────┼─────────────────┤
│ LunghezzaCilindro   │ 200      │ mm    │ Lunghezza totale│
│ DiametroPerno       │ 25       │ mm    │                 │
│ Spessore            │ 10       │ mm    │                 │
└─────────────────────┴──────────┴───────┴─────────────────┘
```

---

### 9.2 Modificare parametri direttamente

Il comando `modify` applica modifiche a parametri specifici e salva il file modificato in `output\`.

```powershell
# Modificare un solo parametro
python main.py modify input\componente.ipt --changes "{\"Larghezza\": \"150 mm\"}"

# Modificare più parametri contemporaneamente
python main.py modify input\componente.ipt --changes "{\"Larghezza\": \"150 mm\", \"Altezza\": \"75 mm\"}"

# Specificare il nome del file di output
python main.py modify input\componente.ipt --changes "{\"Larghezza\": \"150 mm\"}" --output componente_v2.ipt
```

Al termine lo script chiede se aprire il file modificato in Inventor. Rispondere `y` per aprirlo
o `n` per saltare.

#### Nota sulle virgolette in PowerShell

In PowerShell le virgolette doppie all'interno di una stringa vanno precedute dal carattere di
escape `\"`. Questa è la sintassi corretta:

```powershell
--changes "{\"NomeParametro\": \"valore\"}"
```

In alternativa, se si usa il **Prompt dei comandi (CMD)** tradizionale di Windows invece di
PowerShell, si possono usare le virgolette semplici all'esterno:

```cmd
--changes '{"NomeParametro": "valore"}'
```

---

### 9.3 Chiedere all'agente AI

Il comando `ask` consente di impartire istruzioni in linguaggio naturale. L'agente AI capisce la
richiesta, analizza il modello Inventor, applica le modifiche necessarie e riporta cosa ha fatto.

```powershell
# Con un file specifico
python main.py ask "descrivi questo modello ed elenca tutti i parametri" --file input\assembly.iam

# Usando il documento già aperto in Inventor (senza specificare --file)
python main.py ask "rendi il parametro CylinderLength 200mm più lungo, salva come extended.iam e aprilo"
```

> **Nota:** per usare Claude Code CLI invece della chiave API, basta impostare `CLAUDE_CODE=true`
> nel file `.env`. Non è necessario alcun flag aggiuntivo sulla riga di comando.

#### Flusso di lavoro dell'agente

Quando si esegue `ask`, l'agente segue questi passi automaticamente:

1. **Chiama `describe_model`** — legge il documento Inventor e costruisce un sommario semantico
   con tipo di documento, proprietà e lista completa dei parametri.
2. **Identifica i parametri rilevanti** — incrocia la richiesta con i parametri disponibili,
   anche se i nomi sono leggermente diversi da quelli scritti nell'istruzione.
3. **Applica le modifiche** — usa lo strumento `set_parameters` per modificare i valori nel modello.
4. **Salva il file** — salva una copia del file modificato in `output\` con il nome indicato
   nella richiesta (o un nome generato automaticamente).
5. **Apre il file in Inventor** — apre il risultato in Inventor per consentire la verifica visiva
   immediata.

Durante l'elaborazione viene mostrato un indicatore di avanzamento. Al termine, la risposta
dell'agente e un riepilogo degli strumenti utilizzati vengono stampati a schermo.

---

## 10. Consigli pratici per gli ingegneri

### Nominare i parametri in Inventor

L'agente AI lavora meglio con nomi di parametri descrittivi. Quando si costruisce o si modifica
un modello in Inventor, vale la pena rinominare i parametri generati automaticamente:

| Invece di... | Usare... |
|---|---|
| `d37` | `LunghezzaCilindro` |
| `d12` | `DiametroPerno` |
| `d58` | `SpessoreParete` |

Per rinominare i parametri in Inventor: **Gestisci → Parametri** (o `F` se è stata configurata
la scorciatoia) → fare doppio clic sul nome del parametro per modificarlo.

### Inventor aperto o chiuso

Non importa se Inventor è aperto o chiuso quando si lancia uno script. Se è chiuso, lo script
lo avvierà automaticamente. Se è già aperto, lo script si collegherà all'istanza esistente.
Se è aperto un documento specifico, si può omettere il flag `--file` per operare sul documento
attivo.

### I file originali non vengono mai toccati

Tutti i file modificati vengono sempre salvati in `output\`. Il file originale in `input\` rimane
invariato. Questo significa che si può sperimentare liberamente senza rischiare di perdere i
modelli originali.

### In caso di errore "Parameter not found"

Se l'agente o il comando `modify` segnalano che un parametro non è stato trovato, usare prima
il comando `extract` per vedere l'elenco esatto dei nomi dei parametri nel file:

```powershell
python main.py extract input\componente.ipt
```

Dalla tabella stampata a schermo si può copiare il nome esatto del parametro e usarlo nel comando
successivo.

---

## 11. Risoluzione problemi comuni (Troubleshooting)

| Problema | Causa probabile | Soluzione |
|---|---|---|
| `python` non riconosciuto in PowerShell | Python non aggiunto al PATH | Reinstallare Python con la casella "Add python.exe to PATH" spuntata |
| `uv` non riconosciuto dopo l'installazione | La shell non ha aggiornato il PATH | Chiudere e riaprire PowerShell |
| `ModuleNotFoundError: No module named 'win32com'` | `pywin32` non installato correttamente | Eseguire `pip install pywin32` |
| Errore al primo import di `win32com` dopo installazione | Script post-installazione non eseguito | Eseguire `python Scripts\pywin32_postinstall.py -install` nella cartella Python (vedere sotto) |
| `ConnectionError: Inventor is not running` | Inventor non si è avviato automaticamente | Aprire Inventor manualmente, poi rieseguire il comando |
| `Parameter 'X' not found` | Nome del parametro errato o con maiuscole diverse | Usare `python main.py extract <file>` per vedere i nomi esatti |
| `ANTHROPIC_API_KEY not set` | File `.env` mancante o chiave non inserita | Creare il file `.env` da `.env.example` e inserire la chiave, oppure impostare `CLAUDE_CODE=true` nel file `.env` |
| Test falliti su macOS/Linux per `win32com` | Piattaforma non Windows | Normale — i test COM funzionano solo su Windows con Inventor installato |
| `pip install` molto lento | pip standard | Usare `uv pip install` che è molto più veloce |
| Inventor si apre ma il file non si carica | Percorso con spazi o caratteri speciali | Racchiudere il percorso tra virgolette: `python main.py extract "input\nome file.iam"` |

### Risolvere l'errore post-installazione di pywin32

Se dopo aver installato `pywin32` si riceve un errore come `ImportError: DLL load failed` al primo
uso, è necessario eseguire manualmente lo script di configurazione post-installazione. Aprire
PowerShell **come amministratore** e digitare:

```powershell
python Scripts\pywin32_postinstall.py -install
```

Se non si conosce il percorso della cartella `Scripts` di Python, si può trovarlo con:

```powershell
python -c "import sys; print(sys.prefix)"
```

Il percorso della cartella `Scripts` si trova dentro la directory stampata da quel comando.
Ad esempio:

```
C:\Users\<utente>\AppData\Local\Programs\Python\Python312\Scripts\pywin32_postinstall.py
```

### Verificare che pywin32 funzioni

```powershell
python -c "import win32com.client; print('pywin32 OK')"
```

Se stampa `pywin32 OK`, la libreria è installata e funzionante.

---

## 12. Aggiornare il progetto

Quando vengono rilasciati aggiornamenti al progetto, aggiornarsi è semplice.

**Se il progetto è stato clonato con Git (Opzione A della sezione 4):**

```powershell
git pull
uv pip install -e ".[dev]"
```

Il primo comando scarica le modifiche più recenti dal repository. Il secondo aggiorna le
dipendenze nel caso in cui siano state aggiunte o modificate nuove librerie.

**Se il progetto era stato scaricato come ZIP (Opzione B della sezione 4):**

Scaricare di nuovo lo ZIP aggiornato da GitHub, estrarlo nella stessa cartella (sovrascrivendo
i file esistenti) e rieseguire:

```powershell
uv pip install -e ".[dev]"
```

> **Consiglio:** Per ricevere gli aggiornamenti più facilmente in futuro, considerare di passare
> alla modalità Git (Opzione A). Git permette di ottenere gli aggiornamenti con un solo comando
> e di tracciare le modifiche locali.

---

*Guida redatta per inventor-scripts v0.1.x — Windows 10/11 a 64 bit.*
