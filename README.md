# [[EXPERIMENTAL / IN-DEV]]
# Comaney
A no-BS, zero-effort budgetting software as a self-hostable django web application.  
Readme to be done.


## Dev zone
### Building docker file
```
docker buildx build \
  --platform linux/amd64 \
  -f Deployment/Dockerfile \
  -t leonetienne/comaney:0.1.0<change version!!> \
  --push \
  .
```

### Building SCSS
```
npm install
npm run build:css      # one-off compile → static/dist/main.css
npm run watch:css      # recompile on every save
```
Source files live in `build/scss/`. The compiled output at `static/dist/main.css` is what Django serves.

### Running tests
```
pip install -r requirements-test.txt
pytest tests/test_e2e.py -vsx
```
