# AWS Lambda container image. Builds the package (with the [lambda] extra:
# mangum + boto3) into the Lambda task root and points at the Mangum handler.
#
# Built and pushed by you / CI to the ECR repo the Terraform module creates:
#   docker build -f deploy/aws-lambda/Dockerfile -t <ecr-url>:<tag> .
#   docker push <ecr-url>:<tag>
# then: terraform apply -var image_tag=<tag>

# Base image pinned by immutable digest (not just the mutable tag) so a moved or
# compromised tag can't swap the base out from under a build. Dependabot bumps the
# tag + digest together.
FROM public.ecr.aws/lambda/python:3.13@sha256:f48813386e87ea5be92aa57844fb90f5a9db618ffd3a6fee86d432497cd787b4

# Copy the project source, then install it (+ lambda extra) into the task root.
COPY pyproject.toml README.md LICENSE /build/
COPY src /build/src
RUN pip install --no-cache-dir "/build[lambda]" -t "${LAMBDA_TASK_ROOT}" && rm -rf /build

ENV AWS_LAMBDA_LOG_FORMAT=JSON

# Lambda discovers the Mangum handler by module path.
CMD ["managed_agents_mcp.lambda_handler.handler"]
