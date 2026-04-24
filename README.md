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