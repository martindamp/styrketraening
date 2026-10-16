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
