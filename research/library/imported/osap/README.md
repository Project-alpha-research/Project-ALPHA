# Imported records: Open Source Cross-Sectional Asset Pricing

One facts-only record per published predictor signal in the project's signal table, release 2026.10 (212 records).
They are `tier = "imported"`. The 28 hand-checked records in `../../published/` are `tier = "checked"`. The two never mix.

**Source.** Andrew Y. Chen and Tom Zimmermann, "Open Source Cross-Sectional Asset Pricing", openassetpricing.com;
data on Hugging Face as `OpenSourceAP/CrossSection`, branch `Data-Release-2026.10`, file `SignalDoc.csv`. The dataset
card states the licence CC BY 4.0, which allows redistribution with attribution. This folder is that attribution.
Please cite the paper if you use the facts.

**What a record holds.** Only facts from the table: the source's id and short acronym, authors, year, journal code,
category, data category, predicted sign, sample years and the release. `idea` is a neutral label built from the name
and category. `mechanism_claimed` says the paper must be read. The table's description and definition text is not copied.

**Refresh.** Run the two commands in `../../README.md` (fetch the file, then `import-catalogue`). A release replaces
this folder's records; the `release` field says which one it holds. Placebo and dropped rows are not imported.
