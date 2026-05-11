# Building Assets

Comaney's CSS and JavaScript are compiled from source files in `build/` and output to `static/dist/`. The compiled files are committed to the repository, so you only need to run the build if you change the source files.

## Running the build

```bash
./build/build-assets.sh
```

This is the only supported way to build assets. Do not run `npm` directly on your host machine.

## Why Docker

The build script runs `npm install && npm run build` inside a `node:25.9.0-slim linux/amd64` Docker container. This ensures the output is compatible with the production target. Alpine.js requires `--target=es2020` in esbuild; lower targets break its async evaluator, and the containerised build enforces this. It also avoids saving architecture-specific binary versions to `package-lock.json`.

## What gets built

There are two independent JS bundles:

**`expenses.js`**: powers the expense list page. Handles live search, bulk selection, and the running sum of selected expenses. Built with Alpine.js v3.

**`dashboard.js`**: powers the dashboard. Handles card fetching, the CSS Grid layout, drag-to-reorder, resize, Chart.js chart rendering, and the CodeMirror 6 YAML editor. Built with Alpine.js v3.

Both bundles are compiled from source in `build/js/` to `static/dist/`.

The single CSS bundle is compiled from SCSS source in `build/scss/` to `static/dist/main.css`.

## CSS theming

Light and dark mode are implemented with CSS custom properties (`var(--color-name)`). Do not replace these with SCSS `$variables` for anything theme-related. SCSS variables are resolved at compile time and cannot respond to the user's browser preference or the in-page theme toggle; only CSS custom properties work at runtime.

## Production

The production Docker image runs the build as part of `docker buildx build`. Node.js and `node_modules` are not present in the final image; only the compiled output in `static/dist/` is kept.
