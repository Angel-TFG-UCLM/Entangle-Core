# Entangle Core preservation and restore

## Deterministic offline mode

No provider is auto-detected. Start the bundled safe fixture with no Mongo, GitHub, Azure AI, or Tavily:

```powershell
docker compose --profile offline up --build
# GET http://localhost:8000/api/v1/health shows data_mode and selected providers
```

Use a captured private bundle by setting `ENTANGLE_SNAPSHOT_PATH`, `ENTANGLE_DATA_MODE=snapshot`, `ENTANGLE_DATABASE_PROVIDER=portable-mongo`, `ENTANGLE_AI_PROVIDER=offline`, `ENTANGLE_SEARCH_PROVIDER=disabled`, and `ENTANGLE_GITHUB_PROVIDER=github`. The last value documents that ingestion remains an explicit GitHub API dependency; snapshot browsing never calls it.

`portable` Compose starts local Mongo. Add `--profile ollama` only when an explicitly selected OpenAI-compatible endpoint is required.

## Export, encryption, and restore

Snapshots are versioned manifests plus BSON Extended JSON collections and SHA-256 checksums. Export only from an authorized environment; scripts never inspect environment files or export credentials:

```powershell
$env:MONGO_URI = 'mongodb://authorized-host:27017/'
python scripts/export_snapshot.py --output C:\secure\entangle-snapshot.tar.gz --redact-field email
python scripts/verify_snapshot.py C:\secure\entangle-snapshot.tar.gz
# Authorized target only; replacement is intentionally explicit.
python scripts/import_snapshot.py C:\secure\entangle-snapshot.tar.gz
```

The import writes a new database and prints its name; set `MONGO_DB_NAME` to that name only after review, preserving rollback to the old database. Keep bundles outside Git. Encrypt them before transfer, for example `age -p -o entangle-snapshot.tar.gz.age entangle-snapshot.tar.gz`, and verify after decryption before import. The checked-in fixture is synthetic only.

## Providers and unavoidable dependencies

- `azure-openai`: local development may use Azure developer credentials; production requires the specific `AZURE_MANAGED_IDENTITY_CLIENT_ID` and Bicep/Terraform grant it AI RBAC.
- `bedrock`: uses the runtime task/pod IAM role and `AWS_REGION` / `AI_MODEL`.
- `openai-compatible`: requires explicit `AI_BASE_URL`, `AI_MODEL`, and `AI_API_KEY` (Ollama/vLLM compatible).
- `offline` and `disabled`: make no AI call. `tavily` and GitHub remain optional/external and report their configured state through health.

## Infrastructure validation (no deployment)

```powershell
python -m pytest tests/test_preservation.py tests/test_config.py tests/test_agent_helpers.py
python -m compileall src scripts
black --check src scripts
flake8 src scripts
docker compose config
# If installed: helm template entangle deploy/helm/entangle-core
# If installed: terraform -chdir=infra/terraform/azure fmt -check; terraform -chdir=infra/terraform/azure validate
# If installed: terraform -chdir=infra/terraform/aws fmt -check; terraform -chdir=infra/terraform/aws validate
# If Azure CLI/Bicep is installed: az bicep build --file infra/main.bicep --stdout
```

Terraform is account/subscription agnostic and intentionally contains no backend, credentials, or apply command. Azure parity is split across Terraform and the reconciled Bicep: Container Apps API/staging, ACR, Log Analytics, AI/chat+embeddings, Static Web App, identity/RBAC, and alerts are represented; Mongo vCore remains Bicep because its ARM API is region-sensitive. `parity` retains observed regions/topology; `economy` lowers replicas/model capacity. Unrelated rg-entangle VM/VNet/Bastion resources are deliberately excluded.
