# Ordbok for Linjeforeningen Elektra

Ordboka ligger alltid oppdatert på **https://elektra.io/ordbok**.

Mangler et ord? Foreslå det på **https://elektra.io/ordbok/forslag**, der alle kan like
forslagene. Ordbokansvarlig legger de beste inn her i `ord/`.

## Slik er repoet bygd opp

```
ord/            ett ord per fil, f.eks. ord/arrkom.toml
template/       LaTeX-malen (forside, forord, oppsett, utskriftshefte)
assets/         logo og signaturer
build.py        sjekker ordene og lager PDF-ene
```

Hver push til `main` bygger PDF-ene og legger dem på utgivelsen
[`ordbok`](../../releases/tag/ordbok), som elektra.io viser:

- `ordbok.pdf`: den digitale versjonen, med lenker mellom ordene
- `ordbok-utskrift.pdf`: A5-hefte på A4. Skriv ut tosidig, vend langs kortsiden,
  brett på midten og stift.

## Et ord

Filnavnet er ordets id: små bokstaver a–z, tall og bindestrek (`ord/alt-var-bedre-for.toml`).

```toml
ord = "Arrkom"
nynorsk = "Arrkjem"
stikkord = "Komité"
definisjon = """
Komiteen som arrangerer fester. Ansvarlig for [[Åre]]-turen og
*veldig* mye "moro".
"""
```

- `ord` må være med. `nynorsk` og `stikkord` kan stå tomme (`""`).
- `[[Ord]]` eller `[[vist tekst|ord eller id]]` lager en lenke til et annet ord.
- `*tekst*` blir kursiv, `"tekst"` blir sitat.
- Linjeskift i definisjonen spiller ingen rolle, de blir til mellomrom.
- `definisjon = ""` skjuler ordet i PDF-en til den er fylt ut.
- Rekkefølgen ordnes automatisk: tall og tegn først, så A–Å.
- Hvert ord har et anker i PDF-en: `https://elektra.io/ordbok#nameddest=arrkom`.

Du kan legge til eller endre et ord rett på GitHub (*Add file* i `ord/`). På forslagssiden
har Tek-Kom en knapp *Kopier som TOML* som gir deg fila ferdig, med filnavnet øverst.
Sjekken i pull requesten sier fra om feil, f.eks. en lenke som ikke peker på noe ord.

## Bygge lokalt

Krever Python 3.11+ (ingen pakker å installere) og en LaTeX-installasjon med `latexmk`.

```shell
python build.py --check     # sjekk ordene, uten LaTeX
python build.py             # lag build/ordbok.pdf og utskriftsversjonene
```

## Lisens

LaTeX-malen bygger på [Dictionary-malen fra LaTeXTemplates.com](http://www.latextemplates.com)
(CC BY-NC-SA 3.0).
