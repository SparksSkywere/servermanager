# Language / localization files

Put custom Server Manager UI language packs here (e.g. `en.json`, `fr.json`).

.NET framework satellite assemblies (`cs/`, `de/`, `fr/`, … next to the EXE) are no longer shipped —
the app runs in English. Do not move runtime `*.resources.dll` folders into this directory;
.NET will not load them from `Lang/`.
