import * as cdk from 'aws-cdk-lib';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

const ROOT = path.join(__dirname, '..', '..');
/** The shared pidtwin package (digitizer + plant graph), bundled into the agent and the Lambdas. */
export const PIDTWIN_SRC = path.join(ROOT, 'pidtwin', 'src', 'pidtwin');

export const PYTHON_VERSION = '3.13';

export interface PythonBundleOptions {
  /** Directory with the handler / entrypoint and, if it has dependencies, a requirements.txt. */
  readonly sourceDir: string;
  /** Also copy the pidtwin package into the bundle. */
  readonly includePidtwin?: boolean;
}

/**
 * Asset path and options that package a Python directory with its dependencies as Linux arm64
 * wheels (AgentCore Runtime and the Lambdas both run on arm64).
 *
 * Bundles locally with uv when it is installed (no Docker needed); otherwise falls back to a
 * Docker build image, which gets the repository root mounted so it can reach pidtwin/.
 */
export function pythonBundle(opts: PythonBundleOptions): { path: string; options: cdk.AssetOptions } {
  const requirements = path.join(opts.sourceDir, 'requirements.txt');
  const hasRequirements = fs.existsSync(requirements);
  const copySources = (outputDir: string) => {
    for (const f of fs.readdirSync(opts.sourceDir)) {
      if (f === 'requirements.txt' || f === '__pycache__') continue;
      fs.cpSync(path.join(opts.sourceDir, f), path.join(outputDir, f), { recursive: true });
    }
    if (opts.includePidtwin) {
      fs.cpSync(PIDTWIN_SRC, path.join(outputDir, 'pidtwin'), {
        recursive: true,
        filter: (src) => !src.includes('__pycache__'),
      });
    }
  };
  const rel = path.relative(ROOT, opts.sourceDir);
  const dockerSteps = [
    ...(hasRequirements ? [`pip install -r ${rel}/requirements.txt -t /asset-output --only-binary=:all:`] : []),
    `cp -r ${rel}/. /asset-output/`,
    'rm -f /asset-output/requirements.txt',
    ...(opts.includePidtwin ? ['cp -r pidtwin/src/pidtwin /asset-output/pidtwin'] : []),
  ];
  const options: cdk.AssetOptions = {
    // hash the inputs, not the output, so unchanged code does not re-upload
    assetHashType: cdk.AssetHashType.CUSTOM,
    assetHash: hashInputs([opts.sourceDir, ...(opts.includePidtwin ? [PIDTWIN_SRC] : [])]),
    bundling: {
      image: cdk.DockerImage.fromRegistry(`public.ecr.aws/sam/build-python${PYTHON_VERSION}:latest-arm64`),
      platform: 'linux/arm64',
      command: ['bash', '-c', dockerSteps.join(' && ')],
      local: {
        tryBundle(outputDir: string): boolean {
          if (hasRequirements) {
            try {
              execFileSync('uv', ['--version'], { stdio: 'ignore' });
            } catch {
              return false; // no uv: use Docker
            }
            execFileSync('uv', [
              'pip', 'install', '--quiet',
              '--python-platform', 'aarch64-manylinux2014',
              '--python-version', PYTHON_VERSION,
              '--only-binary=:all:',
              '--target', outputDir,
              '-r', requirements,
            ], { stdio: 'inherit' });
          }
          copySources(outputDir);
          return true;
        },
      },
    },
  };
  return { path: ROOT, options };
}

function hashInputs(dirs: string[]): string {
  const crypto = require('crypto') as typeof import('crypto');
  const h = crypto.createHash('sha256');
  const walk = (p: string) => {
    for (const f of fs.readdirSync(p).sort()) {
      if (f === '__pycache__' || f.endsWith('.pyc')) continue;
      const full = path.join(p, f);
      if (fs.statSync(full).isDirectory()) {
        walk(full);
      } else {
        h.update(path.relative(ROOT, full));
        h.update(fs.readFileSync(full));
      }
    }
  };
  dirs.forEach(walk);
  return h.digest('hex');
}
