import * as fs from 'fs';
import * as path from 'path';

/**
 * AWS Solution identity for the CDK app: the stack Description that deployment counting matches, and the
 * AWSSOLUTION/<id>/<version> user-agent token the agent and the Lambdas append to their AWS SDK calls.
 *
 * A port of pidtwin/src/pidtwin/solution.py (see its docstring for why each guard exists); both read the
 * `solution` block of solution.json at the repository root, and pidtwin/tests/test_solution.py checks they
 * agree. Missing or malformed, the block degrades the token to '' but makes stackDescription() throw, because a
 * stack deployed without the id in its description is never counted as an install.
 */

export const CONFIG_PATH = path.join(__dirname, '..', '..', 'solution.json');

/** CloudFormation caps a template Description at 1024 bytes. */
const DESCRIPTION_MAX_BYTES = 1024;

interface Identity { id?: string; name?: string; version?: string }

function identity(): Identity {
  try {
    const block = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')).solution;
    return block && typeof block === 'object' && !Array.isArray(block) ? block : {};
  } catch {
    return {}; // stackDescription() below still throws
  }
}

/** The AWSSOLUTION/<id>/<version> token, or '' if it cannot be built. */
export function userAgentString(): string {
  const { id, version } = identity();
  return id && version ? `AWSSOLUTION/${id}/${version}` : '';
}

/**
 * Environment the agent runtime and the Lambdas need to attribute their AWS SDK calls (USER_AGENT_STRING,
 * read by pidtwin.solution and the DispatchSheet Lambda); empty when there is no token to pass on.
 */
export function userAgentEnvironment(): { [key: string]: string } {
  const token = userAgentString();
  return token ? { USER_AGENT_STRING: token } : {};
}

/**
 * `(<id>) - <name>. Version <version>`, or `(<id>-<idSuffix>) - <name> - <component>. Version <version>`.
 *
 * Only the stack at the top of the dependency graph (the application stack, which consumes the network
 * stack) carries the bare id; a supporting stack passes `idSuffix`, or one install counts as two.
 */
export function stackDescription(component?: string, idSuffix?: string): string {
  const { id, name, version } = identity();
  if (!(id && name && version)) {
    throw new Error(`cannot build a stack description: the 'solution' block in ${CONFIG_PATH} must define id, `
      + `name and version (got id=${id}, name=${name}, version=${version}). Deploying without the id in the `
      + 'description means the stack is never counted as an install.');
  }
  if (!/^SO\d+$/.test(id)) {
    throw new Error(`solution id ${id} is not of the form SO<digits>; deployment counting matches on the literal `
      + "'(SO' prefix, so a differently-shaped id is silently never counted");
  }
  let ident = id;
  // `!== undefined`, not truthiness: '' must be rejected, or a supporting stack would carry the bare id
  if (idSuffix !== undefined) {
    if (!/^[A-Za-z0-9-]+$/.test(idSuffix)) {
      throw new Error(`stack id suffix '${idSuffix}' must match [A-Za-z0-9-]+`);
    }
    ident = `${id}-${idSuffix}`;
  }
  // '' / whitespace-only mean "no component", not a dangling ' - .' separator
  const label = (component ?? '').trim();
  const subject = label ? `${name} - ${label}` : name;
  const desc = `(${ident}) - ${subject}. Version ${version}`;
  const size = Buffer.byteLength(desc, 'utf8');
  if (size > DESCRIPTION_MAX_BYTES) {
    throw new Error(`stack description is ${size} bytes; CloudFormation caps Description at `
      + `${DESCRIPTION_MAX_BYTES}: ${desc.slice(0, 120)}...`);
  }
  return desc;
}
