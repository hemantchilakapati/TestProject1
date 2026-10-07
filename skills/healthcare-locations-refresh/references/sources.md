# How each source works (read when a scraper breaks)

All four are public pages anyone can open in a browser. Be polite: keep worker
counts low, and never hammer a site that is returning errors.

## Jefferson Health - `scripts/jefferson.py`
- `https://www.jeffersonhealth.org/locations.model.json` (Adobe AEM page model) contains a
  `search_listings` component with `solrUrl` (SearchStax Solr), `authValue` (public read-only
  Basic auth the browser uses) and `contentType: location`. The script reads these each run,
  so a rotated key is picked up automatically.
- Query: `<solrUrl>/search-name-location?fq=content_type:health2021/content-type/location&rows=5000&fl=*`.
  `numFound` was 447 in Oct 2026.
- Per-location details: `<page_url>.model.json` -> `location_detail_head` (hours in `hoursDetail`,
  extra phones, 24h flag, links) and `location_info` (shuttle, language services).
- Known quirk: ~9 locations stay in the index after their pages are removed (404). Kept and flagged.
- Likely breakages: component renamed (search the model JSON for `solrUrl`), handler renamed
  (the React bundle maps `location` -> `/search-name-location`; grep the bundle under
  `/etc.clientlibs/health2021/clientlibs/clientlib-react.min.*.js`).

## LVHN - `scripts/lvhn.py`
- Drupal; no JSON API (`/jsonapi` and `?_format=json` are disabled).
- Listing: `/locations?page=0..N`, 15 per page; last page from the `pager__item--last` link.
  Location links are `field--name-node-title ... <a href="/locations/...">`.
- Detail page: address spans (`address-line1`, `locality`, `administrative-area`, `postal-code`)
  inside `<section class="location-header">`, `field--name-field-phone`, `field--name-field-fax`,
  office-hours tables, JSON-LD (`LocalBusiness`/`Hospital`) with lat/long in `areaServed.geoMidpoint`
  and `openingHours`. "Located at ... and part of ..." tagline gives parent building and institute.
- Types: `<option value="/locations?f%5B0%5D=type%3A<id>">Label (n)</option>` on /locations.
  Services: JSON map `"Label (n)":"\/locations?f%5B0%5D=service%3A<id>"`. The script fetches
  each filter's listing pages to tag locations. Type counts must match the option counts
  (a warning is raised otherwise). Two service labels exist twice under different ids - harmless.
- The site resets connections above ~4 concurrent requests. Keep workers at 3.

## Quest Diagnostics - `scripts/quest.py`
- `https://www.questdiagnostics.com/sitemap.xml` -> `locations-sitemap.xml` (~2,350 URLs:
  `/locations/detail.html/<SITECODE>/<ZIP>/75/1` for US, slugs for Mexico/Brazil/Ireland).
  One URL is listed twice; the script de-duplicates.
- Detail page HTML: `#loc-title`, `div.address` (lines split by `<br>`), `.phone-num`, `.fax-num`,
  hidden `div.latitude` / `div.longitude`, `div.week-time-content` hours, `Landmark :` note,
  "Schedule Online" link. The tests-offered block is commented out on the site (template filler) - ignored.
- Search page results are rendered client-side; don't try to scrape `/locations/search`.
- ~49 sitemap URLs render empty (closed sites) -> Excluded tab.
- Not every row is Quest-branded: Sonora Quest and Diagnostic Laboratory of Oklahoma are Quest
  joint ventures; other names are partner hospitals/collection sites. `Location Type` classifies them.

## Labcorp - `scripts/labcorp.py`
- `https://locations.labcorp.com/sitemap_index.xml` -> `sitemap_0.xml` (state, city and location
  URLs). Locations match `/<st>/<city>/<numeric id>/` (~2,270).
- Each page has schema.org `MedicalBusiness` JSON-LD: name (`Labcorp #<id> City, ST` or
  `Labcorp at Walgreens #...`), address, geo, telephone, `openingHoursSpecification`
  (00:00-00:00 = closed), `specialOpeningHoursSpecification` (holidays), `makesOffer` (services).
  Fax is only in page text (`Fax: +1 ...`).
- Only patient service centers are published here; in-hospital/in-office draw sites are not.
