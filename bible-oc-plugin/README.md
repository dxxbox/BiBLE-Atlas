# bible-oc-plugin

OpenClaw native plugin for remote BiBLE Atlas integration.

The plugin registers:

- a `context-engine` named `bible-atlas`
- session lifecycle hooks for capture and bounded flush
- seven core `bible_*` agent tools
- `openclaw bible setup` and `openclaw bible status`

## Development

```bash
npm install
npm run build
npm run test
npm run verify:contracts
```

## Local Install

```bash
node scripts/install-local.mjs --write
openclaw bible setup --base-url http://127.0.0.1:5555 --write
openclaw bible status
```

`install-local.mjs` only links the local plugin path and checks build artifacts.
It does not contact BiBLE Atlas or enable the `contextEngine` slot. `setup --write`
performs the remote health check and writes runtime configuration.
