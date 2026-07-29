# Azure and AWS Terraform roots

These roots are deliberately account/subscription agnostic. Supply identifiers, state backend, existing AWS networking, image tags, and secrets at deployment time. Do not put `terraform.tfvars` containing credentials in Git.

- `azure/` provides Container Apps API plus staging, ACR, Log Analytics, user-assigned identity/RBAC, Azure AI chat/embedding deployments, Static Web App, and optional alert recipient. Key Vault access is scoped to the two referenced secrets rather than the whole vault. The reconciled Bicep template owns Mongo vCore parity due to ARM version/region variability.
- `aws/` provides ECR, ECS/Fargate, CloudWatch, S3/CloudFront and Bedrock runtime selection. A DocumentDB-compatible endpoint may be injected as `MONGO_URI`; no database password is created or stored.

Use `profile = "parity"` for observed Entangle topology or `"economy"` for reduced capacity. Run `terraform fmt -check` and `terraform validate` before a separately approved plan; these roots contain no apply automation.
