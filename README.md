# Træningsprogrammer

Mine egne træningsprogrammer som statiske sider, hostet via GitHub Pages.

**Live:** https://martindamp.github.io/styrketraening/

## Struktur

```
index.html            forside med oversigt over programmer
<program>/index.html  ét program pr. mappe → pæn URL /<program>/
_skabelon/index.html  tom skabelon til et nyt program
.nojekyll
```

Eksisterende program: [`loberknae/`](loberknae/) → https://martindamp.github.io/styrketraening/loberknae/

## Tilføj et nyt program

1. Kopiér mappen `_skabelon/` og omdøb den til programmets navn, fx `knae-stabilitet/`.
2. Ret i `<programnavn>/index.html`:
   - `<title>` og hero-teksten (kicker, overskrift, intro)
   - `STORAGE_KEY` i scriptet (giv hvert program sin egen, fx `prog_knae`)
   - øvelserne i `data`-objektet (felterne er forklaret i kommentarerne)
   - teksterne under "Plan & regler"
3. Tilføj et kort på forsiden: kopiér `<a class="card">`-blokken i `index.html` og peg den på den nye mappe (`href="<programnavn>/"`).

Siderne deler designsystem, så et nyt program ser automatisk ud som resten.

## Synk til Garmin

`push_strength_to_garmin.py` opretter programmet som **workouts i Garmin Connect** (ikke i kalenderen — bare som workouts du selv starter på uret). Hvert pas (Opvarmning, Pas A, Pas B) bliver én styrke-workout med navnet `LØBERKNÆ · <pas>`.

Øvelserne læses fra den samme `loberknae/program.json`, som websiden bruger — ét sted at rette. `garmin`-blokken på hver øvelse styrer, hvad der sendes til uret (sæt, reps/tid, øvelsesnavn). Øvelser uden `garmin`-blok (ren mobilitet) springes over.

GitHub Actionen `sync-garmin-strength.yml` kører automatisk, når `program.json` ændres på main, og kan køres manuelt fra Actions-fanen. Den sletter de gamle `LØBERKNÆ`-workouts og opretter dem forfra, så uret altid matcher filen.

**Opsætning (engangs):** tilføj en repository-secret `GARMIN_TOKEN` under Settings → Secrets and variables → Actions. Generér værdien på en maskine, hvor Garmin-login allerede virker:

```bash
python -c "import garth,os; garth.resume(os.path.expanduser('~/.garminconnect')); print(garth.client.dumps())"
```

Kør lokalt med `python push_strength_to_garmin.py loberknae/program.json --dry-run` for at se payloaden uden at uploade. `--run-tests` kører de interne tests.

### Garmin øvelsesnavne

`category`/`exercise` i `program.json` er Garmins egne enum-værdier. De er slået op i:

- Regneark med hele Garmins øvelseskatalog (kategori, navn, muskelgrupper, udstyr): https://docs.google.com/spreadsheets/d/1OaqIaBhPk4xBnkqVPYvFpj2HZNk_ISX0zHgWfA0WXkQ/edit?gid=608592697#gid=608592697
- Kildeprojektet der genererer det: [maximecharriere/GarminExercisesCollector](https://github.com/maximecharriere/GarminExercisesCollector)

Skal en øvelse have et nyt navn, så find `CATEGORY_GARMIN` + `NAME_GARMIN` i regnearket og skriv dem ind i `program.json`.
