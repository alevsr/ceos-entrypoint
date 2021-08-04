# README

```sh
CEOS_64=64 CEOS_EDITION=lab CEOS_VERSION=4.26.1F
docker build \
  --build-arg "CEOS_64=${CEOS_64}" \
  --build-arg "CEOS_EDITION=${CEOS_EDITION}" \
  --build-arg "CEOS_VERSION=${CEOS_VERSION}" \
  --tag arista-ceos:${CEOS_EDITION}${CEOS_64}-${CEOS_VERSION} \
  --tag arista-ceos:latest .
```
