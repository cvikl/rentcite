# Housing-law corpus

Plain-text copies of official housing-law documents (statutes, ordinances, bills) for
California, New Jersey and Massachusetts, used by the HomeRule pipeline. The pipeline
quotes verbatim from these files, so the text keeps the source's original characters
(curly quotes, section signs); only whitespace is normalised.

## Files

- `manifest.csv`: one row per target document. Columns:
  `doc_id,title,kind,state,county,city,citation,url,retrieval_date,file,status`.
  `kind` is `statute`, `ordinance` or `bill`; `status` is `ok` or `unreachable`.
  Unreachable targets keep their row (so the gap is visible) with an empty `file`.
- `doc_NNN.txt`: UTF-8. First line is
  `# <title> | <citation> | <url> | retrieved <date>`, then a blank line, then the
  document's main text (navigation, scripts and menus stripped, paragraph breaks kept).

## Provenance

Every file comes from an official government source, fetched directly by
`scripts/build_corpus.py` on the retrieval date in the manifest. Sources used:

- California statutes and bills: `leginfo.legislature.ca.gov` (Legislative Counsel).
- Los Angeles RSO: a PDF of LAMC Chapter XV hosted by LA City Planning
  (`planning.lacity.gov`). It is an archival 2013 copy of the code; the current
  official code host (amlegal.com) refuses automated requests. Treat it as historical.
- San Francisco Chapter 37: the Rent Board's edition of the ordinance on `sf.gov`
  (`media.api.sf.gov`), 11-24-2024 version. The Rent Board notes that this edition is
  printed for convenience and is not the official record. Section 37.10C is sliced
  out of the same PDF into its own file.
- San Diego: the city's own municipal code PDF on `docs.sandiego.gov`.
- Berkeley: ordinance PDFs on `rentboard.berkeleyca.gov` and `berkeleyca.gov`
  (Ordinance 7,950-N.S. for Chapter 13.76; Ordinances 7,956-N.S. and 7,974-N.S. for
  Chapter 13.63). `berkeley.municipal.codes` refuses automated requests.
- Santa Ana and Jersey City codes: the municode API (`api.municode.com`) that serves
  `library.municode.com`; the manifest URL is the public library page.
- Jersey City Ordinance 25-057 (section 218-12): the city's CivicWeb legislative portal.
- New Jersey statutes: PDFs published by NJ state agencies (Department of Community
  Affairs on `nj.gov`, Attorney General on `njoag.gov`), because the Legislature's own
  hosts (`njleg.state.nj.us`) did not answer from this network. The 2A:18-61.1 file is
  cut before the publisher's case annotations.
- Newark: the city's certified rent control ordinance PDF on `newarknj.gov`. It is a
  scanned image, so the text is tesseract OCR and may contain recognition errors;
  verify against the PDF before quoting.
- Massachusetts: `malegislature.gov` (and `mass.gov` fallbacks) were attempted.

Law-firm, news, legal-aggregator and other unofficial pages are never fetched or
included. Nothing is written by hand; if a document could not be retrieved it is
marked `unreachable` and no file exists for it.

## Rebuilding

```
.venv/bin/python scripts/build_corpus.py              # full rebuild
.venv/bin/python scripts/build_corpus.py --only doc_001,doc_002
.venv/bin/python scripts/build_corpus.py --skip-existing
```

The script fetches single pages only (no crawling), waits 1.5 s between requests,
sends a normal browser User-Agent, retries each URL up to 4 times with a 40 s timeout,
and does not retry hosts that answer 403. PDFs are converted with `pdftotext`
(scanned PDFs with `tesseract`). Each saved file is checked to contain real document
text (at least 800 characters, no bot-challenge or error page); otherwise the target is
recorded as unreachable. Dependencies: `httpx` (in `.venv`), `pdftotext`, `pdftoppm`,
`tesseract`.
