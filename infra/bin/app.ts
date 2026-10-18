#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { RegistryStack, PlatformStack } from '../lib/stacks';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION };

// Stack 1 exists so CI can create the ECR repos BEFORE the first image is pushed.
const registry = new RegistryStack(app, 'LeetAI-Registry', { env });

// Context: -c stableTag=<tag> [-c canaryTag=<tag> -c canaryPercent=10] [-c maxTasks=20] [-c bedrockModelId=...]
new PlatformStack(app, 'LeetAI-Platform', {
  env,
  repos: registry.repos,
  stableTag: app.node.tryGetContext('stableTag') ?? 'latest',
  canaryTag: app.node.tryGetContext('canaryTag'),
  canaryPercent: Number(app.node.tryGetContext('canaryPercent') ?? 10),
  maxTasks: Number(app.node.tryGetContext('maxTasks') ?? 20),
  bedrockModelId: app.node.tryGetContext('bedrockModelId') ?? 'anthropic.claude-3-haiku-20240307-v1:0',
});
