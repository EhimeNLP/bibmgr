import { readFileSync } from 'node:fs';

const [reportPath, lockfilePath] = process.argv.slice(2);
const { auditReportVersion, error, vulnerabilities, metadata } = JSON.parse(readFileSync(reportPath, 'utf8'));
const { packages } = JSON.parse(readFileSync(lockfilePath, 'utf8'));
if (error || auditReportVersion !== 2 || !vulnerabilities || !packages || !metadata?.vulnerabilities) {
  throw new Error('npm audit did not return a valid vulnerability report');
}

// Remove this exception when the fixed version is pinned. It expires at the end of December 2 in JST.
const advisoryUrl = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf';
const expiresAt = Date.parse('2026-12-03T00:00:00+09:00');
const blocking = (severity) => severity === 'high' || severity === 'critical';

function allowsDevelopmentException(name, ancestors = new Set()) {
  const finding = vulnerabilities[name];
  if (finding?.severity !== 'high' || ancestors.has(name) || !finding.nodes.length ||
      !finding.nodes.every((path) => packages[path]?.dev === true)) return false;

  // npm also assigns high severity to dependents. Every blocking cause in
  // such a chain must lead to the same dev-only advisory.
  const chain = new Set([...ancestors, name]);
  let foundBlockingCause = false;
  for (const cause of finding.via) {
    if (typeof cause === 'string') {
      if (!Object.hasOwn(vulnerabilities, cause)) return false;
      if (!blocking(vulnerabilities[cause].severity)) continue;
      if (!allowsDevelopmentException(cause, chain)) return false;
    } else {
      if (!blocking(cause.severity)) continue;
      if (cause.severity !== 'high' || cause.name !== 'picomatch' || cause.url !== advisoryUrl) return false;
    }
    foundBlockingCause = true;
  }
  return foundBlockingCause;
}

const findings = Object.entries(vulnerabilities).filter(([, finding]) => blocking(finding.severity));
const { high, critical } = metadata.vulnerabilities;
if (findings.length !== high + critical) throw new Error('npm audit counts do not match the report');

const expired = Date.now() >= expiresAt;
const rejected = findings.filter(([name]) => expired || !allowsDevelopmentException(name));
if (rejected.length) {
  const causes = rejected.map(([name, { via }]) =>
    `${name}: ${via.map((cause) => typeof cause === 'string' ? cause : cause.url).join(', ')}`);
  console.error(`Blocking npm audit findings:\n${causes.join('\n')}`);
  process.exitCode = 1;
} else if (findings.length) {
  console.warn(`::warning::Temporarily allowing dev-only picomatch advisory ${advisoryUrl} through 2026-12-02 JST.`);
} else {
  console.log('npm audit reported no high or critical findings.');
}
