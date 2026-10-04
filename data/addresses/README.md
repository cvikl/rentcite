# Sample multifamily addresses (`addresses.csv`)

468 real multifamily property addresses with building facts, 52 per city, across
9 cities: Los Angeles, San Francisco, San Diego, Berkeley (CA); Jersey City,
Hoboken, Newark (NJ); Boston, Cambridge (MA). Built 2026-10-04 by
`scripts/build_addresses.py` from public open data, no API keys.

Rebuild: `.venv/bin/python scripts/build_addresses.py` (add `--no-cache` to refetch;
raw API responses are cached in `cache/addresses/`). Sampling is deterministic
(`--seed 42`), but a `--no-cache` rebuild can pick different rows if the sources
change.

No row in the current file is synthetic. The script falls back to
`source=synthetic_fallback` rows only if a source is unreachable after 3 retries,
and prints that in its summary.

## Columns

| column | meaning |
| --- | --- |
| `address_id` | `addr_0001` .. in file order |
| `street` | house number + street name, title case |
| `postal_city` | postal city as the source gives it (Boston keeps Dorchester, Roxbury, Jamaica Plain etc.; San Diego keeps assessor situs community) |
| `state` | CA / NJ / MA |
| `zip` | 5-digit ZIP |
| `year_built` | integer, blank if unknown, 0 or < 1700 |
| `units` | integer, blank if unknown or 0 |
| `use_code` | the source's use / property class code plus its description |
| `source` | short source label + dataset id |

Sanity rules applied everywhere: street must start with a house number, ZIP must
be 5 digits, duplicates on (street, zip) dropped, max 60 rows per city.

## Sources and exact queries

### Los Angeles (52 rows, all with units, 51 with year built)
- Source: LA County Assessor, "Assessor Parcel Data 2026" ArcGIS feature layer
  `https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/Assessor_Parcel_Data_2026/FeatureServer/0`
  (the old Socrata `data.lacounty.gov/resource/9trm-uz8i` now redirects to ArcGIS Hub).
- Licence: LA County GIS open data terms (public, attribution to LA County Assessor).
- Query: `where=SitusCity LIKE 'LOS ANGELES%' AND UseCode LIKE '05%'`,
  `outFields=SitusHouseNo,SitusFraction,SitusDirection,SitusStreet,SitusZIP5,YearBuilt,Units,UseCode,UseCodeDescChar2,UseCodeDescChar3`,
  `orderByFields=AIN`, 8 pages of 52 at evenly spaced `resultOffset` (the layer is
  ordered geographically, so spread offsets give citywide coverage). Use code
  `05xx` = "Five or More Units or Apartments".
- Fields: `street` = SitusHouseNo [+fraction] [+direction] + SitusStreet; `zip` = SitusZIP5;
  `year_built` = YearBuilt; `units` = Units.

### San Francisco (52 rows, all with year built and units)
- Source: DataSF, Assessor Historical Secured Property Tax Rolls `wv5m-vpq2`
  (`https://data.sf.gov/resource/wv5m-vpq2.json`, data.sfgov.org redirects there), joined to
  San Francisco Addresses, Enterprise Addressing System `3mea-di5p` for the canonical
  address and ZIP (the roll has no ZIP column).
- Licence: PDDL (DataSF default).
- Query 1: `$where=closed_roll_year='2025' AND use_code='MRES' AND number_of_units>=5`
  (`use_definition` = "Multi-Family Residential"; this is the only matching code in roll 2025,
  there is no "Apartment%" definition), `$select=property_location,parcel_number,year_property_built,number_of_units,use_code,use_definition`,
  `$limit=20000`. 8,934 parcels; 156 sampled.
- Query 2: `https://data.sf.gov/resource/3mea-di5p.json?$where=parcel_number in('..')`
  in chunks of 50, `$select=parcel_number,address_number,street_full_street_name,zip_code`.
  For range parcels the EAS address matching the roll's low house number is used.

### San Diego (52 rows, all with units, 42 with effective year)
- Source: SanGIS regional parcel layer, read from a public ArcGIS Online republication
  `https://services7.arcgis.com/3kQCXzNCo2WKILzp/arcgis/rest/services/SanGIS_Parcels/FeatureServer/0`
  (owner `Hunsakersd`, data last edited 2025-05-29). The official SANDAG/SanGIS service
  (`geo.sandag.org/server/rest/services/Parcel_MapService`) answers HTTP 403 to non-browser
  clients and `data.sandiego.gov` has no parcel attribute dataset, so this mirror is the
  best reachable copy. Treat as "SanGIS data as of mid 2025, third-party hosted".
- Licence: SanGIS data are public, redistribution subject to SanGIS terms of use.
- Query: `where=SITUS_JURI='SD' AND UNITQTY>=5 AND ASR_LANDUS IN (14,15,16) AND SITUS_ZIP<>' '`,
  `outFields=SITUS_ADDR,SITUS_FRAC,SITUS_PRE_,SITUS_STRE,SITUS_SUFF,SITUS_POST,SITUS_COMM,SITUS_ZIP,YEAR_EFFEC,UNITQTY,ASR_LANDUS,NUCLEUS_US`,
  `orderByFields=APN`, 8 pages at spread offsets. ASR_LANDUS 14/15/16 are the county
  assessor's multi-family (5+ unit) land-use groups; they hold almost all 5+ unit parcels.
- Caveat: `year_built` here is the assessor "effective year" (`YEAR_EFFEC`, 2-digit,
  blank when `00`), not a construction year. `postal_city` is the assessor situs community
  (`SITUS_COMM`), mostly "San Diego"; one row is "Del Mar".

### Berkeley (52 rows, no year built, no units)
- Source: City of Berkeley Open Data, Parcels / TaxParcel2017 `rax9-nuvx`
  (`https://data.cityofberkeley.info/resource/rax9-nuvx.json`), attributes from Alameda County.
- Licence: City of Berkeley open data (public domain style, attribution City of Berkeley IT).
- Query: `$where=use_code in('2400','2500','2600','2700')`,
  `$select=situs_stree,situs_str_1,situs_city,situs_zip,use_code,apn`, `$limit=5000`.
  (The portal's WAF returns 403 for `IS NOT NULL` or `$order` variants, so keep it minimal.)
- Caveat: the dataset carries only the Alameda County use code (2400-2700 = multi-family
  5+ units per the county use-code list); year built and unit count are not published, so
  both are blank. Parcel data is the 2017 vintage.

### Jersey City, Hoboken, Newark (52 rows each)
- Source: NJ Office of GIS, Parcels Composite of NJ (MOD-IV attributes)
  `https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0`
  joined to NJOGIS AddressPoints
  `https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/AddressPoints/FeatureServer/0`
  for the postal city and ZIP (MOD-IV's `ZIP_CODE` is the owner's mailing ZIP, not the situs).
- Licence: NJOGIS open data (public domain, attribution NJ Office of GIS).
- Query 1: `where=PCL_MUN='<code>' AND PROP_CLASS='4C'` with codes 0906 Jersey City
  (1,770 parcels), 0905 Hoboken (336), 0714 Newark (1,213);
  `outFields=PROP_LOC,YR_CONSTR,DWELL,BLDG_DESC,PCL_GUID,PAMS_PIN`, `orderByFields=PAMS_PIN`,
  `resultRecordCount=2000`. Class 4C = apartments (5+ units). Queries are POSTed.
- Query 2: `where=PCL_GUID IN ('..')` in chunks of 50 (POST),
  `outFields=FULLADDR,POST_COMM,POST_CODE,PCL_GUID,ADD_NUMBER`. The address point whose
  number equals the parcel's low house number is preferred.
- Caveats: `YR_CONSTR` is sparse (48 of 156 rows). `units` = `DWELL` when >= 2; otherwise
  parsed from `BLDG_DESC` (e.g. `3S-B-8U` -> 8); Newark often codes DWELL = 1 for
  apartments, so many Newark rows have no unit count. `use_code` = "4C " + BLDG_DESC.

### Boston (52 rows, all with year built, no units)
- Source: Analyze Boston, Property Assessment FY2026 (package `property-assessment`,
  resource `ee73430d-96c0-423e-ad21-c4cfb54c8961`), read through the CKAN datastore:
  `https://data.boston.gov/api/3/action/datastore_search_sql`.
- Licence: ODC-PDDL.
- Query: `SELECT "ST_NUM","ST_NAME","CITY","ZIP_CODE","YR_BUILT","RES_UNITS","NUM_BLDGS","LU","LU_DESC"
  FROM "ee73430d-96c0-423e-ad21-c4cfb54c8961" WHERE "LU" IN ('A','R4') LIMIT 20000`
  (LU `A` = apartments 7+ units, `R4` = apartments 4-6 units; 5,601 rows). Rows whose
  `ST_NUM` is not a number or number range are dropped.
- Caveats: `RES_UNITS` is empty for every A/R4 parcel in FY2026 (also FY2025 and FY2024),
  so `units` is blank; `use_code` carries the LU description ("APT 4-6 UNITS",
  "APT 7-30 UNITS", "LUXURY APARTMENT", ...). `postal_city` is the assessing `CITY`
  field, kept as given (Dorchester, Roxbury, South Boston, ...).

### Cambridge (52 rows, all with year built and units)
- Source: Cambridge Open Data, Cambridge Property Database FY2016-FY2026 `eey2-rv59`
  (`https://data.cambridgema.gov/resource/eey2-rv59.json`).
- Licence: Cambridge open data terms (public).
- Query 1: `$where=yearofassessment='2026' AND propertyclass in('4-8-UNIT-APT','>8-UNIT-APT','AFFORDABLE APT')`,
  `$select=address,owner_address,owner_city,owner_zip,condition_yearbuilt,interior_numunits,propertyclass,stateclasscode,map_lot`,
  `$limit=5000` (880 rows).
- ZIP: the property database has no situs ZIP. Query 2 pulls owner-occupied Cambridge
  parcels (`$where=yearofassessment='2026' AND upper(address)=owner_address AND owner_city='CAMBRIDGE' AND owner_zip like '021%'`,
  `$select=address,owner_zip`, 6,895 rows) and builds a street -> (house number, ZIP) index.
  A sampled apartment uses its own `owner_zip` when owner-occupied, otherwise the ZIP of the
  nearest house number on the same street. Cambridge ZIPs are 02138-02142 so the
  approximation is reliable but not authoritative.
- Fields: `year_built` = `condition_yearbuilt`, `units` = `interior_numunits`,
  `use_code` = state class code + property class (111 "4-8-UNIT-APT", 112 ">8-UNIT-APT",
  114 "AFFORDABLE APT").

## Known gaps

- Berkeley: no year built or units in open data.
- Boston: no unit counts for apartment parcels in the assessing file.
- San Diego: effective year instead of year built; data from a third-party ArcGIS mirror.
- NJ (MOD-IV): year built sparse, Newark unit counts mostly missing.
- Cambridge: ZIP inferred from same-street owner-occupied parcels for non-owner-occupied rows.
