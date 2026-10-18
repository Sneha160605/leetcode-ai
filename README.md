# Socratic — LeetCode Clone with AI Hints

A polished coding-practice workspace for learning problem-solving through progressive hints, code submissions, and complexity feedback. The project includes a static frontend, AWS Lambda API, queue-based judge workers, sandbox harnesses, AWS CDK infrastructure, and a GitHub Actions pipeline.

## What changed in this update

- Redesigned the frontend with a responsive dark workspace, overview dashboard, problem filters, coding workspace, progressive hint panel, complexity review, and leaderboard.
- Added a **local demo mode** so the interface can be explored without AWS credentials or Cognito setup. Demo submissions are illustrative only; they do **not** execute code or verify correctness.
- Kept the existing AWS API integration available through `frontend/config.js` when an API URL and Cognito app client are configured.
- Added security response headers and explicit preflight handling in the API handler.
- Made the sandbox module importable on Windows for development/testing while ensuring submissions are never executed on the Windows host. Real sandbox execution belongs in the isolated Linux worker container.
- Documented the local and AWS workflows more clearly.

## Quick start — Windows

You do not need AWS credentials to preview the interface.

1. Extract the ZIP file.
2. Open the extracted `leetcode-ai` folder in VS Code.
3. Open **Terminal → New Terminal**.
4. Run:

   ```powershell
   cd frontend
   python -m http.server 8080
   ```

5. Open <http://localhost:8080> in your browser.
6. Leave the terminal open while using the site. Press `Ctrl+C` to stop the server.

The app opens in **Demo Mode** by default. It stores drafts and demo progress in your browser. Demo-mode submission verdicts are illustrative UI demonstrations and must not be presented as real code execution results.

## Connect the live AWS backend

Edit `frontend/config.js` after the AWS resources are deployed:

```js
window.CONFIG = {
  apiUrl: "https://YOUR_API_ID.execute-api.YOUR_REGION.amazonaws.com/YOUR_STAGE",
  region: "YOUR_COGNITO_REGION",
  clientId: "YOUR_COGNITO_APP_CLIENT_ID",
  demoMode: false
};
```

Use the real API base URL and Cognito app client ID from your deployment. These are public client configuration values; **never add AWS secret access keys or credentials to frontend files**. The Cognito app client must support the authentication flow used by the frontend (`USER_PASSWORD_AUTH`) and email confirmation as configured in Cognito. API Gateway authorizer claims must match the Lambda handler's expectations.

## Backend tests

Use Python 3.12 (or another supported Python 3.10+ version) for the backend. From the project root:

```powershell
cd backend
python -m unittest discover -s tests -t .
```

On Windows, sandbox integration tests are skipped because the production sandbox relies on POSIX resource limits and process controls. This does **not** mean sandbox execution works on Windows. Run sandbox self-tests inside Linux/Docker:

```bash
python -m judge.selftest
LANGUAGE=javascript python -m judge.selftest
```

Install backend dependencies only when needed:

```bash
python -m pip install -r requirements.txt
```

## AWS architecture

The existing CDK project describes API Gateway, Cognito, Lambda, DynamoDB, SQS queues/dead-letter queues, ECR worker images, Fargate worker services, Bedrock-based hints/reviews, and CloudWatch/X-Ray observability. Definitions in source code are not proof that a service has been deployed or is working; verify each resource and run an end-to-end test in the target AWS account and region.

### Deploy (AWS environment required)

Prerequisites: AWS CLI configured with an appropriate deployment role, Node.js/npm, Docker, CDK bootstrap in the target account/region, enabled Bedrock model access if using Bedrock, and a reviewed cost/security plan.

Follow the existing deployment workflow in `infra/` and `.github/workflows/ci.yml`. Do not deploy until account, region, IAM permissions, environment context, container image tags, and expected costs have been checked.

## Safety notes

- Never run untrusted code directly on your personal computer.
- The secure judge must run in its intended isolated Linux/container environment with resource limits, timeouts, and restricted networking.
- Treat local demo results and simulated load tests as demonstrations, not production validation.
- Review IAM permissions, network isolation, task-role credential exposure, CORS origins, logs, and billing before a public deployment.

## Main directories

- `frontend/` — responsive web app and configuration
- `backend/api/` — Lambda REST API handler
- `backend/judge/` — judge, sandbox and worker processing
- `backend/shared/` — AI integration, problems and persistence layer
- `infra/` — AWS CDK stacks
- `.github/workflows/` — CI/CD pipeline
- `loadtest/` — queue simulation and k6 load test
- `scripts/` — staged rollout helpers
