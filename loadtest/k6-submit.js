// k6 run -e API=https://xxx/prod -e CLIENT_ID=... -e REGION=us-east-1 -e USERNAME=... -e PASSWORD=... loadtest/k6-submit.js
// Floods the execution queue and checks (a) API stays fast, (b) every submission is judged ACCEPTED within the SLO.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const e2e = new Trend('judge_e2e_ms', true);
const judged = new Rate('judged_ok');
const API = __ENV.API;
const CODE = 'def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return sorted([seen[target - n], i])\n        seen[n] = i\n';

export const options = {
  scenarios: {
    burst: { executor: 'ramping-arrival-rate', startRate: 2, timeUnit: '1s', preAllocatedVUs: 50, maxVUs: 300,
      stages: [{ target: 5, duration: '1m' }, { target: 30, duration: '3m' }, { target: 30, duration: '2m' }, { target: 0, duration: '1m' }] },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:submit}': ['p(95)<800'],
    judge_e2e_ms: ['p(95)<30000'],
    judged_ok: ['rate>0.99'],
  },
};

export function setup() {
  const r = http.post(`https://cognito-idp.${__ENV.REGION}.amazonaws.com/`, JSON.stringify({
    AuthFlow: 'USER_PASSWORD_AUTH', ClientId: __ENV.CLIENT_ID,
    AuthParameters: { USERNAME: __ENV.USERNAME, PASSWORD: __ENV.PASSWORD } }),
    { headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth' } });
  return { token: r.json('AuthenticationResult.IdToken') };
}

export default function (data) {
  const h = { headers: { Authorization: data.token, 'Content-Type': 'application/json' } };
  const t0 = Date.now();
  const s = http.post(`${API}/submissions`, JSON.stringify({ problemId: 'two-sum', language: 'python', code: CODE }), { ...h, tags: { name: 'submit' } });
  if (!check(s, { 'accepted 202': (r) => r.status === 202 })) { judged.add(false); return; }
  const id = s.json('id');
  for (let i = 0; i < 60; i++) {
    sleep(1);
    const g = http.get(`${API}/submissions/${id}`, { ...h, tags: { name: 'poll' } });
    if (g.status === 200 && g.json('status') === 'DONE') {
      e2e.add(Date.now() - t0);
      judged.add(g.json('verdict') === 'ACCEPTED');
      return;
    }
  }
  judged.add(false);
}
