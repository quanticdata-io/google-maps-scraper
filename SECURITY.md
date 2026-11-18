# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Email **hello@quanticdata.io** with the subject "Security: google-maps-scraper" and include a description, steps to reproduce and the version you use. We acknowledge reports within 3 business days and keep you informed until a fix is released.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## API keys and proxies

Never commit an API key or proxy credentials. The tool reads `QUANTICDATA_API_KEY` from the environment and sends it only in the `Authorization` header to the API base URL. Proxy credentials passed with `--proxy` are used only by the local browser and the email fetcher. If a key leaks, rotate it on the API keys page of the QuanticData dashboard.
