# AWS Lambda container image. Builds the package (with the [lambda] extra:
# mangum + boto3) into the Lambda task root and points at the Mangum handler.
#
# Built and pushed by you / CI to the ECR repo the Terraform module creates:
#   docker build -f deploy/aws-lambda/Dockerfile -t <ecr-url>:<tag> .
#   docker push <ecr-url>:<tag>
# then: terraform apply -var image_tag=<tag>

ARG PYTHON_VERSION=3.13
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}

# Copy the project source, then install it (+ lambda extra) into the task root.
COPY pyproject.toml README.md LICENSE /build/
COPY src /build/src
RUN pip install --no-cache-dir "/build[lambda]" -t "${LAMBDA_TASK_ROOT}" && rm -rf /build

ENV AWS_LAMBDA_LOG_FORMAT=JSON

# Lambda discovers the Mangum handler by module path.
CMD ["managed_agents_mcp.lambda_handler.handler"]
