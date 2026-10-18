import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as ddb from 'aws-cdk-lib/aws-dynamodb';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cw from 'aws-cdk-lib/aws-cloudwatch';
import * as appscaling from 'aws-cdk-lib/aws-applicationautoscaling';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';

export const LANGUAGES = ['python', 'javascript'] as const;
type Lang = (typeof LANGUAGES)[number];

/** ECR repositories (one per language runtime) with scan-on-push. Deployed first by CI. */
export class RegistryStack extends cdk.Stack {
  readonly repos: Record<Lang, ecr.Repository>;
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const mk = (l: Lang) =>
      new ecr.Repository(this, `Repo-${l}`, {
        repositoryName: `leetai/judge-${l}`,
        imageScanOnPush: true,
        imageTagMutability: ecr.TagMutability.IMMUTABLE,
        lifecycleRules: [{ maxImageCount: 30 }],
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });
    this.repos = { python: mk('python'), javascript: mk('javascript') };
  }
}

interface PlatformProps extends cdk.StackProps {
  repos: Record<Lang, ecr.IRepository>;
  stableTag: string;
  canaryTag?: string;
  canaryPercent: number;
  maxTasks: number;
  bedrockModelId: string;
}

export class PlatformStack extends cdk.Stack {
  constructor(scope: Construct, id: string, p: PlatformProps) {
    super(scope, id, p);

    // ------------------------------------------------------------ data + auth
    const table = new ddb.Table(this, 'Table', {
      partitionKey: { name: 'pk', type: ddb.AttributeType.STRING },
      sortKey: { name: 'sk', type: ddb.AttributeType.STRING },
      billingMode: ddb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    table.addGlobalSecondaryIndex({
      indexName: 'gsi1',
      partitionKey: { name: 'gsi1pk', type: ddb.AttributeType.STRING },
      sortKey: { name: 'gsi1sk', type: ddb.AttributeType.STRING },
    });

    const pool = new cognito.UserPool(this, 'Users', {
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: { minLength: 10, requireDigits: true, requireLowercase: true, requireUppercase: false, requireSymbols: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    new cognito.CfnUserPoolGroup(this, 'AdminGroup', { userPoolId: pool.userPoolId, groupName: 'admins' });
    const client = pool.addClient('Web', {
      authFlows: { userPassword: true, userSrp: true },
      generateSecret: false,
      preventUserExistenceErrors: true,
    });

    // ------------------------------------------------------------ network: isolated, no internet route at all
    const vpc = new ec2.Vpc(this, 'Vpc', {
      availabilityZones: ['us-east-1a', 'us-east-1b'],
      natGateways: 0,
      subnetConfiguration: [{ name: 'sandbox', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }],
    });
    vpc.addGatewayEndpoint('S3', { service: ec2.GatewayVpcEndpointAwsService.S3 }); // ECR layers live in S3
    vpc.addGatewayEndpoint('Ddb', { service: ec2.GatewayVpcEndpointAwsService.DYNAMODB });
    for (const [name, service] of Object.entries({
      Ecr: ec2.InterfaceVpcEndpointAwsService.ECR,
      EcrDkr: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Sqs: ec2.InterfaceVpcEndpointAwsService.SQS,
      Logs: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      Bedrock: new ec2.InterfaceVpcEndpointAwsService('bedrock-runtime'),
    })) vpc.addInterfaceEndpoint(`Vpce${name}`, { service });

    const taskSg = new ec2.SecurityGroup(this, 'TaskSg', { vpc, allowAllOutbound: false, description: 'Judge workers: HTTPS to VPC endpoints only' });
    taskSg.addEgressRule(ec2.Peer.ipv4(vpc.vpcCidrBlock), ec2.Port.tcp(443));

    // ------------------------------------------------------------ queues + services per language
    const cluster = new ecs.Cluster(this, 'Cluster', { vpc, containerInsightsV2: ecs.ContainerInsights.ENABLED });
    const bedrockPolicy = new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:Converse'],
      resources: ['arn:aws:bedrock:*::foundation-model/*', `arn:aws:bedrock:*:${this.account}:inference-profile/*`],
    });
    const queues: Record<string, sqs.Queue> = {};
    const dlqs: sqs.Queue[] = [];

    for (const lang of LANGUAGES) {
      const dlq = new sqs.Queue(this, `Dlq-${lang}`, { retentionPeriod: cdk.Duration.days(14), encryption: sqs.QueueEncryption.SQS_MANAGED });
      const queue = new sqs.Queue(this, `Queue-${lang}`, {
        visibilityTimeout: cdk.Duration.minutes(3),
        encryption: sqs.QueueEncryption.SQS_MANAGED,
        deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
      });
      queues[lang] = queue;
      dlqs.push(dlq);

      const taskRole = new iam.Role(this, `TaskRole-${lang}`, { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
      queue.grantConsumeMessages(taskRole);
      table.grantReadWriteData(taskRole);
      taskRole.addToPolicy(bedrockPolicy);

      const mkTask = (variant: string, tag: string) => {
        const td = new ecs.FargateTaskDefinition(this, `Task-${lang}-${variant}`, {
          cpu: 512, memoryLimitMiB: 1024, taskRole,
          runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.X86_64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
        });
        td.addVolume({ name: 'sandbox' });
        const lp = new ecs.LinuxParameters(this, `Lp-${lang}-${variant}`, { initProcessEnabled: true });
        // Fargate cannot ADD capabilities, so drop everything the judge does not need.
        // Kept: SETUID/SETGID (drop to uid 65534 per test case), KILL (kill the process group), CHOWN.
        lp.dropCapabilities(ecs.Capability.NET_RAW, ecs.Capability.MKNOD, ecs.Capability.SYS_CHROOT, ecs.Capability.SETFCAP,
          ecs.Capability.SETPCAP, ecs.Capability.AUDIT_WRITE, ecs.Capability.NET_BIND_SERVICE, ecs.Capability.FSETID);
        const c = td.addContainer('judge', {
          image: ecs.ContainerImage.fromEcrRepository(p.repos[lang], tag),
          readonlyRootFilesystem: true,
          linuxParameters: lp,
          stopTimeout: cdk.Duration.seconds(60),
          logging: ecs.LogDrivers.awsLogs({ streamPrefix: `judge-${lang}-${variant}`, logRetention: logs.RetentionDays.TWO_WEEKS }),
          environment: {
            LANGUAGE: lang, QUEUE_URL: queue.queueUrl, TABLE_NAME: table.tableName, SANDBOX_ROOT: '/sandbox',
            IMAGE_TAG: tag, BEDROCK_MODEL_ID: p.bedrockModelId, AWS_REGION: this.region,
          },
        });
        c.addMountPoints({ containerPath: '/sandbox', sourceVolume: 'sandbox', readOnly: false });
        return td;
      };

      /**
       * Staged rollout for queue workers (no ALB, so no weighted target groups): a `stable` and a `canary`
       * service consume the SAME queue. Canary gets canaryPercent of the task budget; promotion = redeploy
       * with stableTag=<new> and no canaryTag (scripts/rollout.sh drives this and gates on alarms).
       */
      const variants: Array<[string, string, number]> = [];
      const hasCanary = !!p.canaryTag && p.canaryPercent > 0;
      const canaryMax = hasCanary ? Math.max(1, Math.ceil((p.maxTasks * p.canaryPercent) / 100)) : 0;
      variants.push(['stable', p.stableTag, Math.max(1, p.maxTasks - canaryMax)]);
      if (hasCanary) variants.push(['canary', p.canaryTag!, canaryMax]);

      for (const [variant, tag, max] of variants) {
        const svc = new ecs.FargateService(this, `Svc-${lang}-${variant}`, {
          cluster, taskDefinition: mkTask(variant, tag), desiredCount: 1,
          vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED }, securityGroups: [taskSg],
          circuitBreaker: { rollback: true }, minHealthyPercent: 100, maxHealthyPercent: 200,
          enableExecuteCommand: false,
        });
        const backlog = new cw.MathExpression({
          expression: 'visible + inflight', period: cdk.Duration.minutes(1),
          usingMetrics: {
            visible: queue.metricApproximateNumberOfMessagesVisible({ period: cdk.Duration.minutes(1) }),
            inflight: queue.metricApproximateNumberOfMessagesNotVisible({ period: cdk.Duration.minutes(1) }),
          },
        });
        svc.autoScaleTaskCount({ minCapacity: 1, maxCapacity: max }).scaleOnMetric(`Backlog-${variant}`, {
          metric: backlog, adjustmentType: appscaling.AdjustmentType.CHANGE_IN_CAPACITY, cooldown: cdk.Duration.seconds(45),
          scalingSteps: [
            { upper: 0, change: -1 }, { lower: 5, change: +1 }, { lower: 25, change: +3 }, { lower: 80, change: +8 },
          ],
        });
      }
    }

    // ------------------------------------------------------------ API: API Gateway + Lambda (X-Ray on)
    const apiFn = new lambda.Function(this, 'ApiFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'api.handler.handler',
      code: lambda.Code.fromAsset('../backend', { exclude: ['tests', 'judge', 'Dockerfile', '.dockerignore', '__pycache__', '**/__pycache__'] }),
      timeout: cdk.Duration.seconds(25), memorySize: 512, tracing: lambda.Tracing.ACTIVE,
      logRetention: logs.RetentionDays.TWO_WEEKS,
      environment: {
        TABLE_NAME: table.tableName, BEDROCK_MODEL_ID: p.bedrockModelId,
        QUEUE_URL_PYTHON: queues.python.queueUrl, QUEUE_URL_JAVASCRIPT: queues.javascript.queueUrl,
      },
    });
    table.grantReadWriteData(apiFn);
    Object.values(queues).forEach((q) => q.grantSendMessages(apiFn));
    apiFn.addToRolePolicy(bedrockPolicy);

    const api = new apigw.RestApi(this, 'Api', {
      restApiName: 'leetai-api',
      deployOptions: { stageName: 'prod', tracingEnabled: true, metricsEnabled: true, throttlingRateLimit: 50, throttlingBurstLimit: 100 },
      defaultCorsPreflightOptions: { allowOrigins: apigw.Cors.ALL_ORIGINS, allowMethods: ['GET', 'POST', 'OPTIONS'], allowHeaders: ['Authorization', 'Content-Type'] },
    });
    const authorizer = new apigw.CognitoUserPoolsAuthorizer(this, 'Auth', { cognitoUserPools: [pool] });
    const integ = new apigw.LambdaIntegration(apiFn);
    const opts = { authorizer, authorizationType: apigw.AuthorizationType.COGNITO };
    const proxy = api.root.addResource('{proxy+}');
    proxy.addMethod('GET', integ, opts);
    proxy.addMethod('POST', integ, opts);
    for (const seg of ['problems', 'submissions', 'leaderboard']) {
      const r = api.root.addResource(seg);
      r.addMethod('GET', integ, opts);
      if (seg === 'submissions') r.addMethod('POST', integ, opts);
    }

    // ------------------------------------------------------------ frontend hosting
    const site = new s3.Bucket(this, 'Site', { blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, removalPolicy: cdk.RemovalPolicy.DESTROY, autoDeleteObjects: true, enforceSSL: true });
    const cdn = new cloudfront.Distribution(this, 'Cdn', {
      defaultRootObject: 'index.html',
      defaultBehavior: { origin: origins.S3BucketOrigin.withOriginAccessControl(site), viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS },
    });
    new s3deploy.BucketDeployment(this, 'SiteDeploy', {
      destinationBucket: site, distribution: cdn,
      sources: [
        s3deploy.Source.asset('../frontend', { exclude: ['config.js'] }),
        s3deploy.Source.data('config.js', `window.CONFIG=${cdk.Fn.toJsonString({ apiUrl: api.url.replace(/\/$/, ''), region: this.region, clientId: client.userPoolClientId })};`),
      ],
    });

    // ------------------------------------------------------------ observability
    const age = (l: string) => queues[l].metricApproximateAgeOfOldestMessage({ period: cdk.Duration.minutes(1), statistic: 'Maximum' });
    const alarms = [
      ...dlqs.map((d, i) => new cw.Alarm(this, `DlqAlarm${i}`, { metric: d.metricApproximateNumberOfMessagesVisible(), threshold: 1, evaluationPeriods: 1, alarmDescription: 'Submissions failing repeatedly (poison / crashing worker)' })),
      ...LANGUAGES.map((l) => new cw.Alarm(this, `AgeAlarm-${l}`, { metric: age(l), threshold: 120, evaluationPeriods: 3, alarmDescription: `Autoscaling is not keeping up (${l})`, treatMissingData: cw.TreatMissingData.NOT_BREACHING })),
      new cw.Alarm(this, 'Api5xx', { metric: api.metricServerError({ period: cdk.Duration.minutes(1) }), threshold: 5, evaluationPeriods: 2 }),
    ];
    new cw.CompositeAlarm(this, 'Health', { compositeAlarmName: 'leetai-judge-health', alarmRule: cw.AlarmRule.anyOf(...alarms) });

    const judgeMetric = (name: string, l: string, stat: string) => new cw.Metric({ namespace: 'LeetAI/Judge', metricName: name, dimensionsMap: { Language: l }, statistic: stat, period: cdk.Duration.minutes(1) });
    new cw.Dashboard(this, 'Dash', {
      dashboardName: 'leetai',
      widgets: [
        [new cw.GraphWidget({ title: 'Queue backlog', left: LANGUAGES.map((l) => queues[l].metricApproximateNumberOfMessagesVisible()), width: 8 }),
         new cw.GraphWidget({ title: 'Oldest message age (s)', left: LANGUAGES.map(age), width: 8 }),
         new cw.GraphWidget({ title: 'Dead-letter depth', left: dlqs.map((d) => d.metricApproximateNumberOfMessagesVisible()), width: 8 })],
        [new cw.GraphWidget({ title: 'Judge duration p95 (ms)', left: LANGUAGES.map((l) => judgeMetric('JudgeDurationMs', l, 'p95')), width: 8 }),
         new cw.GraphWidget({ title: 'Time-limit-exceeded submissions', left: LANGUAGES.map((l) => judgeMetric('TimeLimitExceeded', l, 'Sum')), width: 8 }),
         new cw.GraphWidget({ title: 'API latency p95 / 5xx', left: [api.metricLatency({ statistic: 'p95' })], right: [api.metricServerError()], width: 8 })],
      ],
    });

    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
    new cdk.CfnOutput(this, 'SiteUrl', { value: `https://${cdn.distributionDomainName}` });
    new cdk.CfnOutput(this, 'UserPoolId', { value: pool.userPoolId });
    new cdk.CfnOutput(this, 'ClientId', { value: client.userPoolClientId });
    new cdk.CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
  }
}
