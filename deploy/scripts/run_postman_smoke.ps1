param(
  [string]$RootUrl = "http://host.docker.internal:8080"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$postmanDir = Join-Path $root "postman"
$normalizedRootUrl = $RootUrl.TrimEnd("/")
$baseUrl = "$normalizedRootUrl/api/v1"

docker run --rm `
  --add-host=host.docker.internal:host-gateway `
  -v "${postmanDir}:/etc/newman:ro" `
  postman/newman:alpine `
  run /etc/newman/it-architect-assistant-smoke.postman_collection.json `
  -e /etc/newman/local.postman_environment.json `
  --env-var "rootUrl=$normalizedRootUrl" `
  --env-var "baseUrl=$baseUrl"

if ($LASTEXITCODE -ne 0) {
  throw "Newman smoke tests failed with exit code $LASTEXITCODE"
}
