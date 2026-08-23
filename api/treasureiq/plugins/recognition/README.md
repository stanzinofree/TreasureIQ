# Recognition plugin workspace

This directory is the only application area intended for new BASE, AT and
SERVICE_PORTAL recognition plugins.

Plugins implement `RecognitionPlugin` from
`treasureiq.catalog.recognition_plugins`. They receive an already fetched
`RecognitionObservation` and return `RecognitionPluginResult`.

They must not perform network I/O, read/write `data-live`, import chat code,
start connectors, change the query planner, or choose `keep`/`rediscover`.
