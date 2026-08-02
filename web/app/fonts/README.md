# Font ospitati localmente

Questi file sono nel repository, e non caricati da Google Fonts a build time,
perché `next/font/google` scarica durante la build: dipenderne renderebbe
`docker compose build` impossibile senza rete, contraddicendo l'affermazione del
progetto di essere eseguibile offline.

È incluso solo il **subset latino** di ciascun peso — l'interfaccia è in
italiano, e la copertura CJK completa delle famiglie Zen aggiungerebbe megabyte
che nessuno renderizza. Totale: 84 KB.

| File | Famiglia | Peso |
|---|---|---|
| `ZenMaruGothic-Medium.woff2` | Zen Maru Gothic | 500 |
| `ZenMaruGothic-Bold.woff2` | Zen Maru Gothic | 700 |
| `ZenKakuGothicNew-Regular.woff2` | Zen Kaku Gothic New | 400 |
| `ZenKakuGothicNew-Medium.woff2` | Zen Kaku Gothic New | 500 |
| `ZenKakuGothicNew-Bold.woff2` | Zen Kaku Gothic New | 700 |
| `DMMono-Regular.woff2` | DM Mono | 400 |
| `DMMono-Medium.woff2` | DM Mono | 500 |

## Licenza

Tutte e tre le famiglie sono distribuite sotto **SIL Open Font License 1.1**,
che ne consente la ridistribuzione anche incorporata in un progetto. Il testo
della licenza è in [`OFL.txt`](OFL.txt).

- **Zen Maru Gothic** e **Zen Kaku Gothic New** — Copyright Yoshimichi Ohira,
  <https://github.com/googlefonts/zen-marugothic> e
  <https://github.com/googlefonts/zen-kakugothic>
- **DM Mono** — Copyright Colophon Foundry, Jonny Pinhorn, Nikhil Ranganathan,
  <https://github.com/googlefonts/dm-mono>

La OFL richiede che la licenza accompagni i file e che i font non siano venduti
separatamente: entrambe le condizioni sono soddisfatte da questa cartella.

## Rigenerare

I file sono stati scaricati dal servizio `css2` di Google Fonts selezionando il
blocco `@font-face` commentato `/* latin */` di ciascun peso.
