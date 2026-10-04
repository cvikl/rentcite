# Housing-law corpus

Plain-text copies of official housing-law documents (statutes, ordinances, bills) for California, New Jersey and Massachusetts. The pipeline quotes verbatim from these files, so the text keeps the source's characters; only whitespace is normalised. Built by `scripts/build_corpus.py` on 2026-10-04 (`.venv/bin/python scripts/build_corpus.py`, `--force` to refetch).

## Files

- `manifest.csv`: one row per target. Columns: `doc_id,title,kind,state,county,city,citation,url,retrieval_date,file,status,status_hint,source_note`. `status` is `ok` or `unreachable`; unreachable targets keep their row so the gap is visible. `status_hint` (`pending` for bills) is data from the manifest, not a per-rule edit. `source_note` records an archive copy or OCR.
- `doc_NNN.txt`: UTF-8, first line `# <title> | <citation> | <url> | retrieved <date>`, blank line, then the main text.

## What is in (34 of 39)

- doc_001: California Civil Code section 1947.12 (Tenant Protection Act rent cap, AB 1482) (Cal. Civ. Code § 1947.12)
- doc_002: California Civil Code section 1946.2 (just cause eviction, AB 1482) (Cal. Civ. Code § 1946.2)
- doc_003: California Civil Code section 1950.5 (security deposits, as amended by AB 12) (Cal. Civ. Code § 1950.5)
- doc_004: California Civil Code section 1950.6 (application screening fee) (Cal. Civ. Code § 1950.6)
- doc_005: California Government Code section 12955 (FEHA housing discrimination, source of income) (Cal. Gov. Code § 12955)
- doc_006: California Government Code section 12927 (FEHA definitions, source of income) (Cal. Gov. Code § 12927)
- doc_007: California Civil Code section 1954.52 (Costa-Hawkins Rental Housing Act) (Cal. Civ. Code § 1954.52)
- doc_008: California Civil Code section 1954.53 (Costa-Hawkins Rental Housing Act) (Cal. Civ. Code § 1954.53)
- doc_009: California AB 325 (2025-2026), common pricing algorithms, chaptered bill text (Cal. AB 325 (2025-2026 Reg. Sess.), Stats. 2025)
- doc_010: California SB 763 (2025-2026), Cartwright Act penalties, chaptered bill text (Cal. SB 763 (2025-2026 Reg. Sess.), Stats. 2025)
- doc_011: California Business and Professions Code section 16756.1 (common pricing algorithms) (Cal. Bus. & Prof. Code § 16756.1)
- doc_012: California Business and Professions Code section 16755 (Cartwright Act penalties) (Cal. Bus. & Prof. Code § 16755)
- doc_013: Los Angeles Rent Stabilization Ordinance, LAMC Chapter XV Article 1 (copy hosted by LA City Planning) (L.A. Mun. Code § 151.00 et seq.)
- doc_014: San Francisco Residential Rent Stabilization and Arbitration Ordinance, Administrative Code Chapter 37 (Rent Board edition, 11-24-2024) (S.F. Admin. Code ch. 37)
- doc_015: San Francisco Administrative Code section 37.10C (use and sale of algorithmic devices prohibited) (S.F. Admin. Code § 37.10C)
- doc_016: San Diego Municipal Code Chapter 9 Article 8 Division 11, sections 98.1101-98.1104 (algorithmic rental pricing) (San Diego Mun. Code §§ 98.1101-98.1104)
- doc_017: Berkeley Rent Stabilization and Eviction for Good Cause Ordinance, BMC Chapter 13.76 (Berkeley Mun. Code ch. 13.76)
- doc_018: Berkeley Ordinance 7,956-N.S. adding BMC Chapter 13.63 (prohibition on pricing algorithms to set rents) (Berkeley Mun. Code ch. 13.63 (Ord. 7,956-N.S.))
- doc_019: Berkeley Ordinance 7,974-N.S. amending BMC Chapter 13.63 (coordinated pricing algorithms) (Berkeley Mun. Code ch. 13.63 (Ord. 7,974-N.S.))
- doc_020: Santa Ana Rent Stabilization and Just Cause Eviction Ordinance, Municipal Code Chapter 8 Article XIX (Santa Ana Mun. Code ch. 8, art. XIX (§§ 8-3100 et seq.))
- doc_022: N.J.S.A. 2A:18-61.1, Anti-Eviction Act, grounds for removal of tenants (NJ DCA copy) (N.J.S.A. 2A:18-61.1)
- doc_023: N.J.S.A. 46:8-19 through 46:8-26, Security Deposit Law including 46:8-21.2 (NJ DCA copy) (N.J.S.A. 46:8-21.2)
- doc_024: N.J.S.A. 46:8-52 et seq., Fair Chance in Housing Act, P.L.2021, c.110 (NJ Attorney General copy) (N.J.S.A. 46:8-52 to 46:8-64)
- doc_028: Jersey City Ordinance 25-057 adding Code section 218-12, Preventing Algorithmic Rent-Fixing in the Rental Housing Market (Jersey City Code § 218-12 (Ord. 25-057))
- doc_031: Newark Rent Control Ordinance, Revised General Ordinances Title XIX Chapter 2, certified ordinance 6PSF-a 09/05/2017 (Newark Rev. Gen. Ord. tit. XIX, ch. 2 (§ 19:2-1 et seq.))
- doc_032: Newark Rent Control Ordinance amendment, certified ordinance 09/11/2018 (Newark Rev. Gen. Ord. tit. XIX, ch. 2 (2018 amendment))
- doc_033: Massachusetts General Laws Chapter 40P, Massachusetts Rent Control Prohibition Act (Mass. Gen. Laws ch. 40P)
- doc_034: Massachusetts General Laws Chapter 186 Section 15B (security deposits, upfront charges) (Mass. Gen. Laws ch. 186, § 15B)
- doc_035: Massachusetts General Laws Chapter 112 Section 87DDD 1/2 (broker fees) (Mass. Gen. Laws ch. 112, § 87DDD½)
- doc_036: Massachusetts Senate Bill S.2983 (194th General Court), algorithmic rent pricing, bill text (Mass. S.2983 (194th Gen. Ct.))
- doc_038: California Business and Professions Code section 16729 (common pricing algorithms prohibited, AB 325) (Cal. Bus. & Prof. Code § 16729)
- doc_039: Massachusetts General Laws Chapter 40P Section 4 (general prohibition of rent control; exception) (Mass. Gen. Laws ch. 40P, § 4)
- doc_040: Massachusetts General Laws Chapter 40P Section 5 (preemption of local rent control) (Mass. Gen. Laws ch. 40P, § 5)
- doc_037: Massachusetts House Bill H.5222 (194th General Court), algorithmic rent pricing, bill text (Mass. H.5222 (194th Gen. Ct.))

## Provenance

Every file comes from an official government host: leginfo.legislature.ca.gov (California statutes and chaptered bills), sf.gov (Rent Board edition of Admin. Code ch. 37; the Rent Board notes it is printed for convenience), docs.sandiego.gov, berkeleyca.gov and rentboard.berkeleyca.gov, library.municode.com (Santa Ana), nj.gov/dca and njoag.gov (New Jersey statutes as published by state agencies), cityofjerseycity.civicweb.net, newarknj.gov, malegislature.gov. The Los Angeles RSO text is an archival copy of LAMC Chapter XV hosted by LA City Planning; the current code host (amlegal.com) refuses automated requests. Law-firm and news pages are never used.

**Internet Archive copies (7).** malegislature.gov and pub.njleg.state.nj.us time out from the build network (Europe), so these are the Internet Archive's captures of the official pages; the manifest `source_note` holds the exact archive URL: doc_033, doc_034, doc_035, doc_036, doc_039, doc_040, doc_037.

**OCR (2).** The Newark rent-control ordinances are scanned PDFs; their text was read with tesseract and carries OCR noise (line numbers, stray characters). Quotes from them are quotes of the OCR text.

## Not reachable

- doc_021: Santa Ana Prohibition of Anti-Competitive Automated Rent Price-Fixing, Municipal Code Chapter 8 Article XXIV (Ordinance NS-3090). https://library.municode.com/ca/santa_ana/codes/code_of_ordinances?nodeId=PTIITHCO_CH8BUST_ARTXXIVPRANMPAUREPRXI (content does not look like statute text (16 chars))
- doc_025: New Jersey P.L.2025, c.405 (rental application fee cap). https://pub.njleg.state.nj.us/Bills/2024/PL25/405_.HTM (no archive capture)
- doc_026: New Jersey FAIR Act, P.L.2026, c.43 (algorithmic rent pricing). https://pub.njleg.state.nj.us/Bills/2026/PL26/43_.HTM (archive unavailable)
- doc_029: Hoboken Code Chapter 155, Rent Control. https://ecode360.com/15252438 (content does not look like statute text (756 chars))
- doc_030: Hoboken Code Chapter 158, Rent Increases (algorithmic rent pricing). https://ecode360.com/15252579 (content does not look like statute text (33161 chars))

Consequences: no Hoboken algorithmic-pricing rule (T2 shows Jersey City only), no NJ application-fee cap and no NJ FAIR Act (T3 has no rule to track), no Santa Ana pricing ordinance (Santa Ana has no addresses in the sample anyway). The official starter pack's corpus replaces this folder; drop its files in, rewrite `manifest.csv` with the columns above, and rerun `make all`.
