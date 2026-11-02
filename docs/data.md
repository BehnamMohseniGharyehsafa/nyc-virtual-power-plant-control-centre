# Data, geography and time conventions

## Observed, derived, assumed and synthetic

| Attribute | Classification | Processing |
|---|---|---|
| Polygon and BIN | Observed public-source record | NYC OTI footprint query; no invented shapes |
| Roof height | Observed, or flagged assumption | Source feet × 0.3048; missing/invalid height explicitly assigned 12 m |
| Footprint area | Derived | Shapely projected EPSG:32618 area |
| Floors | Derived estimate | Rounded roof height / 3.3 m, minimum one; four floors when height absent |
| Floor area | Derived estimate | Footprint × estimated floors; never duplicates a whole lot's reported area across buildings |
| Building use | Derived from observed lot data | Normalised integer BBL join; PLUTO land-use category; explicit unmatched assumption |
| Address | Observed lot label | PLUTO address; not a verified entrance for every footprint |
| Energy, HVAC, PV, BESS, EV | Assumed | Area-scaled archetypes and installations; no metered 15-minute claim |
| Feeder, transformers, interconnections | Synthetic | Explicit electrical assumptions, not a Con Edison topology |

The normaliser accepts decimal BBL representations such as `3000380001.0000000000`. Tax-lot land use is not a verified individual building use. Multiple footprints may share BBLs and addresses. The cache contains 1,000 unique BINs; the downloader rejects duplicated BINs pending an explicit dissolve decision. Tiny footprints under 60 m² and invalid polygons are excluded.

`data/cache/provenance.json` records source URLs, institutions, source units/resolution, acquisition time, content hashes, processing, missing-value policy and licence information. Every run additionally hashes the actual cached files and stores its building geometry, weather, device states and environment versions. The public building snapshot is current at download, while the default market/weather period is July 2024. This temporal difference is disclosed.

## Acquisition

```bash
python -m data.download --date 2024-07-17 --buildings 1000
python -m data.download --date 2024-07-18 --skip-buildings
```

The downloader uses the source behind the supplied NYC map, not the map's empty column list. It performs exact BBL joins to PLUTO in batches, with resumable raw chunks and retries for transient HTTP errors. No acquisition failure triggers synthetic data. A failed refresh preserves the earlier processed cache.

NYISO older daily files may be unavailable. The downloader then opens the documented monthly ZIP archive and extracts the specific day's CSV. It verifies `Name = N.Y.C.` and `PTID = 61761`. The default day has 24 hourly DA records and 300 native RT records, demonstrating why RT intervals must not be assumed uniformly five minutes long.

NYISO DA prices apply to interval starts. The native five-minute/irregular `realtime` files use interval ends. RT observations are mapped over the preceding actual interval, beginning at New York local midnight. The integral of price × interval duration is preserved when averaging onto 15-minute periods. Native files remain cached. No linear price interpolation is used. This is an analytical hypothetical exposure calculation, not a complete NYISO settlement implementation. The hourly integrated P-4A report is a related official reference; the code downloads the native `realtime` archive.

## Weather

Default: Open-Meteo historical gridded reanalysis at 40.703, −73.989, with temperature, humidity, GHI, DNI, DHI, 10 m wind and pressure. This is an alternative to credentialed NSRDB access, not an NSRDB dataset. Weather is acquired from the preceding day through four days after the simulation date, providing forecast history. Simulations longer than the cache require explicit additional acquisition.

Radiation values are preceding-hour means. They are assigned to their interval start and held constant over four 15-minute intervals, preserving hourly irradiance energy. Temperature and other state variables use time interpolation. Missing input observations, duplicate timestamps and negative irradiance fail validation. Hourly disaggregation cannot reconstruct measured intra-hour cloud variability; midpoint solar geometry remains an approximation.

EPW and CSV import are available:

```bash
python -m data.weather_import NewYork.epw --date 2024-07-17 --mode tmy --source-url https://your-provider.example/source
```

Supply an actual provider URL; the example URL is a command placeholder. EPW import uses pvlib, checks geographic proximity, retains local **standard-time** offset, converts to UTC and declares calendar reassignment. A TMY paired with calendar market prices is recorded as a hybrid scenario. TMY is not silently presented as contemporaneous observed weather. An EPW import needs a complete enough period for previous-day forecasts; start-of-file horizons can legitimately fail coverage checks. The importer is implemented but no licensed EPW file is bundled or used in the validation experiments. Direct NSRDB API acquisition is not implemented.

CSV schema: `timestamp_utc,temperature_2m,relative_humidity_2m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,wind_speed_10m,surface_pressure`, units °C, %, W/m², W/m², W/m², m/s, hPa. Timestamps must carry explicit offsets; irradiance is interval-end hourly mean.

## Time and causal information

The canonical time axis is UTC. Every exported observation also carries an offset-aware `America/New_York` timestamp. Spring/autumn local days can contain 92/100 quarter hours; leap years are not discarded. `steps=96` means 24 elapsed hours, not necessarily one DST-transition local day. Set the requested count for the intended local interval.

Weather forecasts use observations strictly before the origin. Known illustrative archetype/EV schedules are assumptions, not future meter observations. Wholesale forecasts use completed 15-minute settlement intervals only; the first forecast explicitly assumes $50/MWh because no prior RT day is required. Future realised DA/RT prices are never handed to the optimiser. DA data are displayed and compared, but not used as an availability-certified predictive product. Market publication-time certification is not implemented.

## Rights and attribution

Software MIT licensing does not relicense datasets. NYC OTI and NYC DCP are credited for footprint/PLUTO records under NYC Open Data terms. NYISO retains rights in its public market reports; no separate permissive dataset licence is asserted. Open-Meteo weather requires CC BY 4.0 attribution, including ECMWF attribution as appropriate. Raw acquisition chunks are excluded from Git. Review source-specific terms before a new public dataset redistribution. No API credentials are stored or required by the default acquisition routes.

LL84 records are **not matched** in this implementation. Every building carries an unmatched benchmark flag. Annual energy calibration, verified building-level HVAC/roof inventories and historical geometry snapshots remain outstanding.
